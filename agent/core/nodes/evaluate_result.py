"""
Node — evaluate_result (Run B entry, fix.md FIX-7)

No polling. `state.sandbox_outcome` was already set by
core.graph.run_continuation_job from the `/callback` payload before this
graph was invoked — this node just records the outcome metric and passes it
through to the route_after_evaluate conditional edge.
"""

import structlog
from core.state import AgentState
from services.metrics import node_duration, fix_attempts

log = structlog.get_logger()


async def evaluate_result(state: AgentState) -> AgentState:
    with node_duration.labels(node="evaluate_result").time():
        sandbox_outcome = state.get("sandbox_outcome", "fail")
        sandbox_pipeline_id = state.get("sandbox_pipeline_id", 0)

        log.info("evaluate_result.outcome", pipeline_id=sandbox_pipeline_id, outcome=sandbox_outcome)
        fix_attempts.labels(outcome=sandbox_outcome if sandbox_outcome in ("pass", "fail", "timeout") else "fail").inc()

        return {**state, "outcome": sandbox_outcome}
