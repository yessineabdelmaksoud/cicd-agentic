"""
Node — post_comment
The shared "ask a human" exit for every explicit no-match / no-file /
rejected / gate-failed edge in the graph, plus a failed sandbox build. Every
early-out in the pipeline routes here instead of dropping silently
(fix.md FIX-5's "explicit no-match edge").

On a failed sandbox build (v5 §6 Run B), the dead ai-fix/<id> branch is
cleaned up here too.
"""

import structlog
from core.state import AgentState
from services.gitlab_client import get_gitlab_client
from services.metrics import node_duration

log = structlog.get_logger()


async def post_comment(state: AgentState) -> AgentState:
    """Post a diagnostic comment on the GitLab commit and settle the terminal outcome."""
    with node_duration.labels(node="post_comment").time():
        project_id = state["project_id"]
        commit_sha = state["commit_sha"]

        comment, outcome = _build_comment_and_outcome(state)

        client = get_gitlab_client()
        try:
            client.post_commit_comment(project_id=project_id, commit_sha=commit_sha, note=comment)
            log.info("post_comment.success", commit=commit_sha[:8], outcome=outcome)
        except Exception as e:
            log.error("post_comment.error", error=str(e))

        sandbox_branch = state.get("sandbox_branch")
        if sandbox_branch and state.get("sandbox_outcome") == "fail":
            try:
                client.delete_branch(project_id=project_id, branch_name=sandbox_branch)
                log.info("post_comment.sandbox_branch_deleted", branch=sandbox_branch)
            except Exception as e:
                log.warning("post_comment.sandbox_branch_delete_failed", branch=sandbox_branch, error=str(e))

        return {**state, "outcome": outcome}


def _build_comment_and_outcome(state: AgentState):
    error_ctx = state.get("error_context", {})
    existing_files = state.get("existing_files", [])
    diagnosis = state.get("diagnosis", {})
    verdict = state.get("review_verdict", {})
    gate = state.get("gate_decision", {})
    patch = state.get("patch_proposal", {})
    sandbox_outcome = state.get("sandbox_outcome", "")

    header = f"**Pipeline:** #{state['pipeline_id']} | **Branch:** `{state['branch']}` | **Build type:** `{state['build_type']}`"
    footer = "\n\n---\n*AI-CICD-Embedded Agent v5.0*"

    if not error_ctx:
        return (
            "## 🤖 AI Agent — Manual Review Required\n\n"
            "The AI agent could not locate a parseable error in the build log for this pipeline.\n\n"
            f"{header}\n\n**Detail:** {state.get('error_message') or 'No error span matched any known pattern.'}\n\n"
            "Please review the build logs manually." + footer,
            "manual_review",
        )

    if not existing_files:
        return (
            "## 🤖 AI Agent — Manual Review Required\n\n"
            "The AI agent diagnosed the failure but could not locate any of the candidate files "
            "in the repository at the failing commit — it will not invent file content, so no "
            "patch was generated.\n\n"
            f"{header}\n\n### 🔍 Diagnosis\n- **Root cause:** {diagnosis.get('root_cause', 'N/A')}\n"
            f"- **Candidate files checked:** {', '.join(state.get('missing_files', [])) or 'none'}" + footer,
            "manual_review",
        )

    if verdict and not verdict.get("approved"):
        return (
            f"## 🤖 AI Agent — Fix Rejected on Review\n\n{header}\n\n"
            f"### 🔍 Diagnosis\n- **Root cause:** {diagnosis.get('root_cause', 'N/A')}\n"
            f"- **Fix type:** `{diagnosis.get('fix_type', 'N/A')}`\n\n"
            f"### ❌ Reviewer Decision\n- **Approved:** No\n- **Confidence:** {verdict.get('confidence', 0.0):.0%}\n"
            f"- **Concerns:** {verdict.get('concerns', 'N/A')}\n\n"
            "**Action required:** Manual investigation needed." + footer,
            "low_confidence",
        )

    if gate and not gate.get("passed"):
        return (
            f"## 🤖 AI Agent — Objective Gate Rejected the Patch\n\n{header}\n\n"
            f"### 🔍 Diagnosis\n- **Root cause:** {diagnosis.get('root_cause', 'N/A')}\n\n"
            f"### 🚧 Gate\n- **Failed checks:** {', '.join(gate.get('failed_checks', [])) or 'N/A'}\n"
            f"- **All checks:** {gate.get('checks', {})}\n\n"
            "This is a safety rejection — no sandbox build was spent." + footer,
            "manual_review",
        )

    if sandbox_outcome == "fail":
        files_modified = [f.get("path", "?") for f in patch.get("files_to_modify", [])]
        return (
            f"## 🤖 AI Agent — Sandbox Build Failed\n\n{header}\n"
            f"**Sandbox branch:** `{state.get('sandbox_branch', 'N/A')}` (deleted)\n\n"
            f"### 🔍 Diagnosis\n- **Root cause:** {diagnosis.get('root_cause', 'N/A')}\n\n"
            f"### 🔧 Applied Patch\n- **Files modified:** {', '.join(f'`{f}`' for f in files_modified) or 'N/A'}\n"
            f"- **Explanation:** {patch.get('explanation', 'N/A')}\n\n"
            "The generated patch did not build in the sandbox. The branch has been removed; "
            "manual investigation needed." + footer,
            "fail",
        )

    return (
        f"## 🤖 AI Agent — Manual Review Required\n\n{header}\n\n"
        f"**Error:** {state.get('error_message') or 'Unknown error'}" + footer,
        "manual_review",
    )
