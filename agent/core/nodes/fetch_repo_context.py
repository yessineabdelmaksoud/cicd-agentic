"""
Node — fetch_repo_context (fix.md FIX-1 — the #1 correctness blocker)

Pulls the REAL content of every candidate file from GitLab at the failing
commit SHA before any patch is generated. The model must never edit text it
hasn't seen: a patch built on invented `original_content` either fails to
apply or silently overwrites a real file with fabricated content — this was
the single biggest correctness gap in the pre-v5 pipeline.

Placement: diagnose → fetch_repo_context → generate_patch.
If none of the candidate files exist at commit_sha, the graph routes straight
to post_comment (core/graph.py route_after_fetch_context) — the patch
generator never gets a chance to invent a path.
"""

import structlog
from core.state import AgentState
from services.gitlab_client import get_gitlab_client
from services.metrics import node_duration

log = structlog.get_logger()

# A diagnosis proposing more than this many files is almost certainly wrong —
# cap it rather than fan out into a huge, unfocused fetch.
MAX_CANDIDATE_FILES = 6


async def fetch_repo_context(state: AgentState) -> AgentState:
    """Fetch real file content for the union of extracted + diagnosed candidate files."""
    with node_duration.labels(node="fetch_repo_context").time():
        project_id = state["project_id"]
        commit_sha = state["commit_sha"]
        error_ctx = state.get("error_context", {})
        diagnosis = state.get("diagnosis", {})

        candidates = list(dict.fromkeys(
            (error_ctx.get("extracted_files") or []) + (diagnosis.get("candidate_files") or [])
        ))[:MAX_CANDIDATE_FILES]

        if not candidates:
            log.warning("fetch_repo_context.no_candidates")
            return {
                **state,
                "repo_context": {},
                "existing_files": [],
                "missing_files": [],
                "error_message": "No candidate files were identified from the error log or diagnosis",
            }

        client = get_gitlab_client()
        repo_context: dict = {}
        existing_files: list = []
        missing_files: list = []

        for path in candidates:
            try:
                content = client.get_raw_file(project_id=project_id, file_path=path, ref=commit_sha)
            except Exception as e:
                log.error("fetch_repo_context.fetch_error", file=path, error=str(e))
                content = None

            if content is None:
                missing_files.append(path)
            else:
                repo_context[path] = content
                existing_files.append(path)

        log.info(
            "fetch_repo_context.result",
            candidates=candidates,
            existing=existing_files,
            missing=missing_files,
        )

        result = {
            **state,
            "repo_context": repo_context,
            "existing_files": existing_files,
            "missing_files": missing_files,
        }

        if not existing_files:
            log.warning("fetch_repo_context.no_files_found", candidates=candidates)
            result["error_message"] = (
                f"None of the candidate files exist in the repository at {commit_sha[:8]}: "
                f"{', '.join(candidates)} — manual review required"
            )

        return result
