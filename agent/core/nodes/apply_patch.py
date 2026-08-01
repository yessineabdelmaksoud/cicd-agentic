"""
Node — apply_patch (fix.md FIX-1/FIX-6)
Creates the sandbox branch and commits each file's FULL new content via the
GitLab Files API (create/update). No substring find-and-replace, no
"couldn't find the original text so overwrite the whole file" fallback —
generate_patch already reconstructed the complete file content, grounded in
what fetch_repo_context actually fetched.

Only reached after evaluate_gate.passed — the attempt cap itself lives in
api/routes.py (Redis counter keyed by commit SHA, max 2); this node doesn't
duplicate that check.
"""

import structlog
from core.state import AgentState
from services.gitlab_client import get_gitlab_client
from services.metrics import node_duration

log = structlog.get_logger()


async def apply_patch(state: AgentState) -> AgentState:
    """Create ai-fix/<pipeline_id> and commit the gate-approved patch as full file content."""
    with node_duration.labels(node="apply_patch").time():
        pipeline_id = state["pipeline_id"]
        project_id = state["project_id"]
        base_branch = state["branch"]
        patch = state.get("patch_proposal", {})
        files_to_modify = patch.get("files_to_modify", [])

        sandbox_branch = f"ai-fix/{pipeline_id}"
        client = get_gitlab_client()

        try:
            client.create_branch(project_id=project_id, branch_name=sandbox_branch, ref=base_branch)
            log.info("apply_patch.branch_created", branch=sandbox_branch)
        except Exception as e:
            if "already exists" in str(e).lower():
                log.warning("apply_patch.branch_exists", branch=sandbox_branch)
            else:
                log.error("apply_patch.branch_error", error=str(e))
                return {**state, "sandbox_branch": sandbox_branch, "error_message": str(e)}

        applied = 0
        errors = []
        for file_mod in files_to_modify:
            file_path = file_mod.get("path", "")
            operation = file_mod.get("operation", "modify")
            new_content = file_mod.get("new_content", "")

            try:
                if operation == "create":
                    client.create_file(
                        project_id=project_id,
                        branch=sandbox_branch,
                        file_path=file_path,
                        content=new_content,
                        commit_message=f"[AI Fix] Create {file_path}",
                    )
                else:
                    client.update_file(
                        project_id=project_id,
                        branch=sandbox_branch,
                        file_path=file_path,
                        content=new_content,
                        commit_message=f"[AI Fix] Fix {file_path}",
                    )
                applied += 1
                log.info("apply_patch.file_applied", file=file_path, operation=operation)
            except Exception as e:
                log.error("apply_patch.file_error", file=file_path, error=str(e))
                errors.append(f"{file_path}: {e}")

        log.info("apply_patch.complete", branch=sandbox_branch, applied=applied, errors=len(errors))

        return {
            **state,
            "sandbox_branch": sandbox_branch,
            "error_message": "; ".join(errors) if errors else None,
        }
