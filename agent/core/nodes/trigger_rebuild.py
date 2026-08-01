"""
Node 7 — trigger_rebuild
Triggers a GitLab pipeline on the sandbox branch and stores the pipeline ID in state.
"""

import structlog
from core.state import AgentState
from services.gitlab_client import get_gitlab_client
from services.metrics import node_duration

log = structlog.get_logger()


async def trigger_rebuild(state: AgentState) -> AgentState:
    """Trigger CI pipeline on the sandbox branch."""
    with node_duration.labels(node="trigger_rebuild").time():
        project_id = state["project_id"]
        sandbox_branch = state["sandbox_branch"]

        client = get_gitlab_client()

        try:
            pipeline = client.trigger_pipeline(
                project_id=project_id,
                ref=sandbox_branch,
                variables={
                    "AI_FIX": "true",
                    "ORIGINAL_PIPELINE": str(state["pipeline_id"]),
                },
            )

            sandbox_pipeline_id = pipeline.get("id", 0)
            log.info(
                "trigger_rebuild.success",
                sandbox_pipeline_id=sandbox_pipeline_id,
                branch=sandbox_branch,
            )

            return {
                **state,
                "sandbox_pipeline_id": sandbox_pipeline_id,
            }

        except Exception as e:
            log.error("trigger_rebuild.error", error=str(e), branch=sandbox_branch)
            return {
                **state,
                "sandbox_pipeline_id": 0,
                "error_message": str(e),
            }
