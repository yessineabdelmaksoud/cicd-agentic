"""
Node — diagnose (v5 §7.1/§8.2)
Diagnostician LLM. Now emits `candidate_files` (files it thinks need editing)
so fetch_repo_context knows what to pull.

If parse_error found a DETERMINISTIC rule fix (e.g. a checksum substitution
whose old/new values were extracted straight from the log), this node skips
the LLM entirely and synthesizes the diagnosis — rules-first, LLM-second
(fix.md FIX-4). If the rule only matched a category, the LLM still runs but
reasons inside that narrowed frame instead of from a blank slate.
"""

import structlog
from pydantic import BaseModel, Field
from typing import List

from core.state import AgentState
from services.openrouter_client import get_openrouter_client
from services.metrics import node_duration, llm_latency, fix_attempts

log = structlog.get_logger()


class DiagnosisResult(BaseModel):
    root_cause: str = Field(..., description="Root cause of the build failure")
    fix_type: str = Field(..., description="Category of fix: recipe|compile|dependency|config|link|fetch|checksum|missing_include|generic")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    candidate_files: List[str] = Field(default_factory=list, description="Files that likely need to be modified to fix this")


PROMPT_TEMPLATE = """You are an expert embedded systems build engineer specializing in {build_type} builds.

## Build Failure Context
**Build type:** {build_type}
**Rules-engine category:** {matched_category} {rule_hint}
**Failing task/recipe:** {failing_task_info}

**Error line:**
{error_line}

**Lines before error:**
{lines_before}

**Lines after error:**
{lines_after}

**Files already spotted in the log:** {extracted_files}

## Task
Analyze this build failure and return a JSON object with exactly these fields:
- `root_cause`: A precise technical description of what caused the failure (1-2 sentences)
- `fix_type`: One of: recipe, compile, dependency, config, link, fetch, checksum, missing_include, generic
- `confidence`: Float 0.0-1.0 indicating your confidence in the diagnosis
- `candidate_files`: List of file paths (relative to repo root) that most likely need to be
  modified to fix this. Prefer files already spotted in the log when they're the right ones.
  Be precise — every path you list will be fetched from the repository; an invented path that
  doesn't exist blocks the whole fix.

Respond ONLY with valid JSON. No explanation, no markdown fences.
"""


def _describe_rule_fix(matched_category: str, rule_fix: dict) -> str:
    if rule_fix.get("type") == "checksum_substitution":
        return (
            f"The recipe's {rule_fix['sum_type']} is {rule_fix['old_sum']}, but the content "
            f"actually fetched hashes to {rule_fix['new_sum']} — the recipe checksum is stale."
        )
    return f"Rule-matched {matched_category} failure."


async def diagnose(state: AgentState) -> AgentState:
    """Diagnose the failure — rules-first short-circuit, LLM (qwen3-coder) otherwise."""
    with node_duration.labels(node="diagnose").time():
        error_ctx = state.get("error_context", {})

        if not error_ctx:
            log.warning("diagnose.no_error_context")
            return {
                **state,
                "diagnosis": {
                    "root_cause": "Could not extract error context from build log",
                    "fix_type": "generic",
                    "confidence": 0.1,
                    "candidate_files": [],
                },
            }

        # --- Rules-first short-circuit: deterministic fix, zero LLM calls ---
        if error_ctx.get("deterministic") and error_ctx.get("rule_fix"):
            rule_fix = error_ctx["rule_fix"]
            candidate_files = error_ctx.get("extracted_files", [])[:3]
            diagnosis = {
                "root_cause": _describe_rule_fix(error_ctx["matched_category"], rule_fix),
                "fix_type": error_ctx["matched_category"],
                "confidence": 0.95,
                "candidate_files": candidate_files,
                "auto_diagnosed": True,
            }
            log.info("diagnose.rule_short_circuit", fix_type=diagnosis["fix_type"], candidate_files=candidate_files)
            fix_attempts.labels(outcome="diagnosed_by_rule").inc()
            return {**state, "diagnosis": diagnosis}

        matched_category = error_ctx.get("matched_category", "unknown")
        rule_hint = ""
        if matched_category != "unknown":
            rule_hint = f"(rules engine narrowed this to '{matched_category}' — reason within that frame unless the evidence clearly says otherwise)"

        failing_task_info = "N/A"
        if error_ctx.get("failing_recipe") or error_ctx.get("failing_task"):
            failing_task_info = f"{error_ctx.get('failing_recipe', '?')} / {error_ctx.get('failing_task', '?')}"

        prompt = PROMPT_TEMPLATE.format(
            build_type=state["build_type"],
            matched_category=matched_category,
            rule_hint=rule_hint,
            failing_task_info=failing_task_info,
            error_line=error_ctx.get("error_line", ""),
            lines_before="\n".join(error_ctx.get("lines_before", [])[-12:]),
            lines_after="\n".join(error_ctx.get("lines_after", [])[:12]),
            extracted_files=", ".join(error_ctx.get("extracted_files", [])) or "none",
        )

        messages = [
            {"role": "system", "content": "You are an expert embedded build engineer. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        client = get_openrouter_client()

        with llm_latency.labels(agent_role="diagnostician", model=client.model_for("diagnostician")).time():
            result: DiagnosisResult = await client.call(
                agent_role="diagnostician",
                messages=messages,
                schema=DiagnosisResult,
            )

        log.info(
            "diagnose.result",
            root_cause=result.root_cause[:100],
            fix_type=result.fix_type,
            confidence=result.confidence,
            candidate_files=result.candidate_files,
        )

        fix_attempts.labels(outcome="diagnosed_by_llm").inc()

        return {
            **state,
            "diagnosis": result.model_dump(),
        }
