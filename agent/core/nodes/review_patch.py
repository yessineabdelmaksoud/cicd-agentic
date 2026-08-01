"""
Node — review_patch (v5 §7.1)
Reviewer LLM — a critical check before the OBJECTIVE gate (evaluate_gate),
not the gate itself (fix.md FIX-6: reviewer.confidence is a tiebreaker only,
never the sole authorization for a sandbox build).

Skips the LLM call entirely when generate_patch already produced an
auto-approved deterministic fix (review_verdict.auto_approved) — there's
nothing subjective to review in a mechanical checksum substitution; the
objective gate downstream still checks it like any other patch.
"""

import structlog
from pydantic import BaseModel, Field

from core.state import AgentState
from services.openrouter_client import get_openrouter_client
from services.metrics import node_duration, llm_latency, reviewer_confidence_hist

log = structlog.get_logger()


class ReviewVerdict(BaseModel):
    approved: bool = Field(..., description="Whether the patch is technically correct and safe")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Reviewer confidence 0.0-1.0")
    concerns: str = Field(default="", description="Concerns or reasons for rejection")
    retryable: bool = Field(
        default=False,
        description="True if a corrected patch addressing these concerns could plausibly pass "
        "(precision/formatting issue) — false if the diagnosis/approach itself is wrong "
        "(no point retrying without new information)",
    )


PROMPT_TEMPLATE = """You are a senior embedded systems code reviewer acting as a critical check before an automated fix proceeds to a sandbox build.

## Original Failure
**Build type:** {build_type}
**Error:** {error_line}

## Diagnosis
**Root cause:** {root_cause}
**Fix type:** {fix_type}

## Proposed Patch
{patch_details}

## Review Criteria
1. **Correctness**: Does it actually fix the stated root cause?
2. **Safety**: No regressions, no breaking changes to other components
3. **Scope**: No unnecessary changes beyond what's needed
4. **Plausibility**: Does the new content look like valid {build_type} source/config, not garbled or truncated?

## Task
Return a JSON object with exactly:
- `approved`: boolean — true only if the patch is correct and safe
- `confidence`: float 0.0-1.0 representing your confidence level
- `concerns`: String listing any specific concerns (empty if approved with high confidence)
- `retryable`: boolean — true only if a corrected patch addressing your concerns could plausibly
  pass (e.g. patch is imprecise/incomplete); false if the underlying diagnosis is wrong and a
  retry with the same root cause would not help

Respond ONLY with valid JSON. No markdown fences.
"""


def _format_patch(patch_proposal: dict) -> str:
    files = patch_proposal.get("files_to_modify", [])
    lines = [f"**Explanation:** {patch_proposal.get('explanation', 'N/A')}\n"]
    for i, f in enumerate(files, 1):
        lines.append(f"**File {i}: {f.get('path', 'unknown')}** ({f.get('operation', 'modify')})")
        lines.append(f"NEW CONTENT:\n```\n{f.get('new_content', '')[:2000]}\n```\n")
    return "\n".join(lines)


async def review_patch(state: AgentState) -> AgentState:
    """Call Reviewer LLM (claude-sonnet) — skipped for auto-approved deterministic fixes."""
    with node_duration.labels(node="review_patch").time():
        existing_verdict = state.get("review_verdict", {})
        if existing_verdict.get("auto_approved"):
            log.info("review_patch.skipped_auto_approved")
            return state

        patch = state.get("patch_proposal", {})
        if not patch.get("files_to_modify"):
            log.warning("review_patch.empty_patch")
            return {
                **state,
                "review_verdict": {
                    "approved": False,
                    "confidence": 0.0,
                    "concerns": "No patch was generated",
                    "retryable": False,
                },
            }

        diagnosis = state.get("diagnosis", {})
        error_ctx = state.get("error_context", {})

        prompt = PROMPT_TEMPLATE.format(
            build_type=state["build_type"],
            error_line=error_ctx.get("error_line", "N/A"),
            root_cause=diagnosis.get("root_cause", "N/A"),
            fix_type=diagnosis.get("fix_type", "N/A"),
            patch_details=_format_patch(patch),
        )

        messages = [
            {"role": "system", "content": "You are a strict, precise embedded systems code reviewer. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        client = get_openrouter_client()

        with llm_latency.labels(agent_role="reviewer", model=client.model_for("reviewer")).time():
            result: ReviewVerdict = await client.call(
                agent_role="reviewer",
                messages=messages,
                schema=ReviewVerdict,
            )

        reviewer_confidence_hist.observe(result.confidence)

        log.info(
            "review_patch.result",
            approved=result.approved,
            confidence=result.confidence,
            retryable=result.retryable,
            concerns=result.concerns[:100] if result.concerns else "",
        )

        return {
            **state,
            "review_verdict": result.model_dump(),
        }
