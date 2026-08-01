"""
Node — evaluate_gate (fix.md FIX-6, v5 §7.4)

Objective, computed-for-free checks decide whether a sandbox build gets
spent — NOT the reviewer's self-reported confidence, which is miscalibrated
by construction (it's the model grading its own homework). Any HARD check
failing is an automatic reject with no sandbox spend; this is exactly the
check that catches a hallucinated path or an edit outside the investigated
files, which the old confidence-only gate could not.

`reviewer_confidence` only nudges Draft vs Normal within the passed band —
it never by itself authorizes a sandbox build.
"""

import difflib
import structlog
from core.state import AgentState
from services.metrics import node_duration, gate_rejection_total

log = structlog.get_logger()

DIFF_LINE_SOFT_LIMIT = 40


def _changed_line_count(original: str, new: str) -> int:
    diff = difflib.unified_diff(original.splitlines(), new.splitlines(), lineterm="")
    return sum(1 for line in diff if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))


async def evaluate_gate(state: AgentState) -> AgentState:
    """Compute the objective pass/fail + Draft/Normal decision."""
    with node_duration.labels(node="evaluate_gate").time():
        patch = state.get("patch_proposal", {})
        verdict = state.get("review_verdict", {})
        error_ctx = state.get("error_context", {})
        diagnosis = state.get("diagnosis", {})
        repo_context = state.get("repo_context", {})
        existing_files = set(state.get("existing_files", []))
        missing_files = state.get("missing_files", [])

        files_to_modify = patch.get("files_to_modify", [])
        modified_paths = [f.get("path") for f in files_to_modify]
        allowed_paths = existing_files | set(error_ctx.get("extracted_files", [])) | set(diagnosis.get("candidate_files", []))

        checks = {}

        # Hard: every modified path was actually fetched as real content (or is an
        # explicit, in-frame "create" — never a path outside what was investigated).
        checks["paths_exist"] = bool(files_to_modify) and all(
            (p in existing_files) or (f.get("operation") == "create" and p in allowed_paths)
            for f, p in zip(files_to_modify, modified_paths)
        )

        # Hard: the patch must actually change something (a no-op "fix" is a failure mode)
        checks["content_changed"] = bool(files_to_modify) and all(
            f.get("operation") == "create" or repo_context.get(p) != f.get("new_content")
            for f, p in zip(files_to_modify, modified_paths)
        )

        # Hard: no file outside the set that was actually investigated
        checks["diff_confined"] = bool(modified_paths) and all(p in allowed_paths for p in modified_paths)

        # Soft: overall diff size
        total_changed_lines = sum(
            _changed_line_count(repo_context.get(p, ""), f.get("new_content", ""))
            for f, p in zip(files_to_modify, modified_paths)
        )
        checks["diff_small"] = total_changed_lines <= DIFF_LINE_SOFT_LIMIT

        # Soft: rules engine recognized the failure category
        checks["known_category"] = error_ctx.get("matched_category", "unknown") != "unknown"

        # Reviewer approval is required (hard), but its confidence is a tiebreaker only
        checks["reviewer_approved"] = bool(verdict.get("approved"))

        hard_checks = ["paths_exist", "content_changed", "diff_confined", "reviewer_approved"]
        failed_hard = [c for c in hard_checks if not checks[c]]
        passed = not failed_hard

        for c in failed_hard:
            gate_rejection_total.labels(check=c).inc()

        mr_type = "none"
        if passed:
            reviewer_confidence = verdict.get("confidence", 0.0)
            strong_signal = checks["known_category"] and checks["diff_small"]
            mr_type = "normal" if (strong_signal and reviewer_confidence >= 0.7) else "draft"

        gate_decision = {
            "passed": passed,
            "mr_type": mr_type,
            "failed_checks": failed_hard,
            "checks": checks,
            "total_changed_lines": total_changed_lines,
            "missing_files": missing_files,
        }

        log.info("evaluate_gate.result", passed=passed, mr_type=mr_type, failed_checks=failed_hard, checks=checks)

        return {**state, "gate_decision": gate_decision}
