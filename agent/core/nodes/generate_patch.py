"""
Node — generate_patch (fix.md FIX-1, v5 §7.1/§8.3)

Edits REAL content from state.repo_context (fetched by fetch_repo_context) —
never invents `original`/`replacement` text. Returns full new file content
per path (GitLab Files API "update" action), not a substring find/replace.

Two paths:
  1. Deterministic rule fix (e.g. checksum substitution) — mechanical string
     substitution on the real fetched content, ZERO LLM calls.
  2. LLM path — small files are inlined in full and the LLM returns the
     complete fixed file; files over LARGE_FILE_LINE_THRESHOLD lines are
     shown as a line-numbered excerpt around the failure and the LLM returns
     only the replacement block for that line range, which is spliced back
     into the real original content here (never truncates the rest of a
     large file).

On a repair retry (review_patch rejected for a fixable reason), the
reviewer's concerns are appended to the prompt via state.repair_feedback.
"""

import structlog
from pydantic import BaseModel, Field
from typing import List, Optional

from core.state import AgentState
from services.openrouter_client import get_openrouter_client
from services.metrics import node_duration, llm_latency

log = structlog.get_logger()

LARGE_FILE_LINE_THRESHOLD = 250
WINDOW_RADIUS = 40


class FileModification(BaseModel):
    path: str = Field(..., description="Relative path of the file to modify — MUST be one of the files shown below")
    operation: str = Field(default="modify", description="modify|create")
    new_content: str = Field(..., description="Full fixed file content, or the replacement block when edit_start_line/edit_end_line are set")
    edit_start_line: Optional[int] = Field(default=None, description="Set only when replacing a line range in a large file")
    edit_end_line: Optional[int] = Field(default=None, description="Set only when replacing a line range in a large file")


class PatchProposal(BaseModel):
    files_to_modify: List[FileModification] = Field(..., description="List of file changes")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in the patch 0.0-1.0")
    explanation: str = Field(..., description="Technical explanation of the patch")


PROMPT_TEMPLATE = """You are an expert embedded systems patch generator specializing in {build_type} builds.

## Diagnosis
**Root cause:** {root_cause}
**Fix type:** {fix_type}

## Error
{error_line}
{feedback_block}
## Real file content (fetched directly from the repository — this is exactly what's there)
{files_section}

## Task
Generate a concrete patch. Return a JSON object with exactly:
- `files_to_modify`: Array of objects, each with:
  - `path`: One of the file paths shown above — do not invent a new path
  - `operation`: "modify" (default) or "create" (only if the diagnosis clearly requires a new file)
  - `new_content`: the full fixed file content for small files, OR just the replacement block
    for large files where an excerpt + line range was shown
  - `edit_start_line` / `edit_end_line`: ONLY set these when you were shown an excerpt (a large
    file) — copy the exact line numbers given. Leave both null for full-file edits.
- `confidence`: Float 0.0-1.0 (your confidence this patch will fix the build)
- `explanation`: Technical explanation of what the patch does and why it fixes the issue

Change as little as possible beyond what's needed to fix the root cause.
Respond ONLY with valid JSON. No markdown fences.
"""


def _file_prompt_section(path: str, content: str, error_line_number: Optional[int]):
    lines = content.splitlines()
    n = len(lines)
    if n <= LARGE_FILE_LINE_THRESHOLD:
        return (
            f"### FILE: {path} ({n} lines) — FULL CONTENT\n```\n{content}\n```\n"
            f"Return the COMPLETE fixed content for this file in `new_content`; "
            f"leave `edit_start_line`/`edit_end_line` null.\n"
        )
    center = error_line_number if error_line_number and 1 <= error_line_number <= n else n // 2
    start = max(1, center - WINDOW_RADIUS)
    end = min(n, center + WINDOW_RADIUS)
    excerpt = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start - 1, end))
    return (
        f"### FILE: {path} ({n} lines total — too large to inline fully) — EXCERPT lines {start}-{end}\n"
        f"```\n{excerpt}\n```\n"
        f"Return ONLY the replacement text for lines {start}-{end} (no line-number prefixes) in "
        f"`new_content`, and set edit_start_line={start}, edit_end_line={end}.\n"
    )


def _apply_windowed_edit(original_content: str, replacement_block: str, start_line: int, end_line: int) -> str:
    lines = original_content.splitlines(keepends=True)
    block_lines = replacement_block.splitlines(keepends=True)
    if block_lines and not block_lines[-1].endswith("\n") and end_line < len(lines):
        block_lines[-1] += "\n"
    spliced = lines[:max(0, start_line - 1)] + block_lines + lines[end_line:]
    return "".join(spliced)


def _apply_checksum_rule_fix(repo_context: dict, existing_files: list, rule_fix: dict) -> Optional[dict]:
    old_sum, new_sum = rule_fix.get("old_sum"), rule_fix.get("new_sum")
    if not old_sum or not new_sum:
        return None
    for path in existing_files:
        content = repo_context.get(path, "")
        if old_sum in content:
            return {
                "files_to_modify": [{
                    "path": path,
                    "operation": "modify",
                    "new_content": content.replace(old_sum, new_sum, 1),
                }],
                "confidence": 0.95,
                "explanation": (
                    f"Deterministic checksum fix: replaced stale {rule_fix.get('sum_type', 'checksum')} "
                    f"{old_sum} with the actual downloaded {new_sum} (rules-engine match, no LLM call)."
                ),
            }
    return None


async def generate_patch(state: AgentState) -> AgentState:
    """Generate a patch grounded in real fetched file content — rules-first, LLM-second."""
    with node_duration.labels(node="generate_patch").time():
        diagnosis = state.get("diagnosis", {})
        error_ctx = state.get("error_context", {})
        repo_context = state.get("repo_context", {})
        existing_files = state.get("existing_files", [])
        repair_feedback = state.get("repair_feedback")

        # --- Deterministic mechanical fix: zero LLM calls ---
        rule_fix = error_ctx.get("rule_fix")
        if error_ctx.get("deterministic") and rule_fix and rule_fix.get("type") == "checksum_substitution":
            patch = _apply_checksum_rule_fix(repo_context, existing_files, rule_fix)
            if patch:
                log.info("generate_patch.rule_short_circuit", files=[f["path"] for f in patch["files_to_modify"]])
                return {
                    **state,
                    "patch_proposal": patch,
                    "review_verdict": {
                        "approved": True,
                        "confidence": 0.95,
                        "concerns": "",
                        "mr_type": "normal",
                        "auto_approved": True,
                    },
                }
            log.warning("generate_patch.rule_fix_did_not_apply", rule_fix=rule_fix)
            # fall through to the LLM path — the category hint is still in error_ctx

        if not repo_context:
            log.warning("generate_patch.no_repo_context")
            return {
                **state,
                "patch_proposal": {"files_to_modify": [], "confidence": 0.0, "explanation": "No real file content was available to edit"},
            }

        error_line_number = error_ctx.get("error_line_number")
        file_sections = "\n\n".join(
            _file_prompt_section(path, repo_context[path], error_line_number) for path in existing_files
        )

        feedback_block = ""
        if repair_feedback:
            feedback_block = f"\n## Your previous patch was rejected on review\n**Reviewer concerns:** {repair_feedback}\nFix these specifically.\n"

        prompt = PROMPT_TEMPLATE.format(
            build_type=state["build_type"],
            root_cause=diagnosis.get("root_cause", "Unknown"),
            fix_type=diagnosis.get("fix_type", "generic"),
            error_line=error_ctx.get("error_line", ""),
            feedback_block=feedback_block,
            files_section=file_sections,
        )

        messages = [
            {"role": "system", "content": "You are a precise embedded systems patch generator. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        client = get_openrouter_client()

        with llm_latency.labels(agent_role="patch_generator", model=client.model_for("patch_generator")).time():
            result: PatchProposal = await client.call(
                agent_role="patch_generator",
                messages=messages,
                schema=PatchProposal,
            )

        files_to_modify = []
        for fm in result.files_to_modify:
            if fm.edit_start_line and fm.edit_end_line and fm.path in repo_context:
                full_content = _apply_windowed_edit(repo_context[fm.path], fm.new_content, fm.edit_start_line, fm.edit_end_line)
            else:
                full_content = fm.new_content
            files_to_modify.append({"path": fm.path, "operation": fm.operation, "new_content": full_content})

        log.info(
            "generate_patch.result",
            files_count=len(files_to_modify),
            confidence=result.confidence,
            explanation=result.explanation[:100],
        )

        return {
            **state,
            "patch_proposal": {
                "files_to_modify": files_to_modify,
                "confidence": result.confidence,
                "explanation": result.explanation,
            },
        }
