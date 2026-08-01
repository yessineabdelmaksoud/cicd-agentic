"""
LangGraph StateGraph — Run A / Run B split (fix.md FIX-7)

Run A (webhook → sandbox trigger): fetch_logs → parse_error → diagnose →
fetch_repo_context → generate_patch → review_patch → evaluate_gate →
apply_patch → trigger_rebuild. Ends there — run_graph_job saves the final
state to Redis keyed by sandbox_pipeline_id and returns; the worker is never
parked waiting for the sandbox build.

Run B (validate.yml callback → MR/comment): evaluate_result → open_mr /
post_comment. Resumed by run_continuation_job from /callback, never polling.

Both graphs route to post_comment on any explicit no-match / no-file /
rejected / gate-failed edge — nothing is dropped silently.
"""

import asyncio
import structlog
from langgraph.graph import StateGraph, END

from core.state import AgentState
from core.nodes.fetch_logs import fetch_logs
from core.nodes.parse_error import parse_error
from core.nodes.diagnose import diagnose
from core.nodes.fetch_repo_context import fetch_repo_context
from core.nodes.generate_patch import generate_patch
from core.nodes.review_patch import review_patch
from core.nodes.evaluate_gate import evaluate_gate
from core.nodes.apply_patch import apply_patch
from core.nodes.trigger_rebuild import trigger_rebuild
from core.nodes.evaluate_result import evaluate_result
from core.nodes.open_mr import open_mr
from core.nodes.post_comment import post_comment

log = structlog.get_logger()

MAX_REPAIR_RETRIES = 1


# ---------------------------------------------------------------------------
# Routing functions (conditional edges)
# ---------------------------------------------------------------------------

def route_after_parse(state: AgentState) -> str:
    if not state.get("error_context"):
        log.info("graph.route", node="parse_error", decision="post_comment", reason="no_match")
        return "post_comment"
    return "diagnose"


def route_after_fetch_context(state: AgentState) -> str:
    if not state.get("existing_files"):
        log.info("graph.route", node="fetch_repo_context", decision="post_comment", reason="no_files_found")
        return "post_comment"
    return "generate_patch"


def route_after_review(state: AgentState) -> str:
    verdict = state.get("review_verdict", {})
    if verdict.get("approved"):
        return "evaluate_gate"

    retry_count = state.get("repair_retry_count", 0)
    if verdict.get("retryable") and retry_count < MAX_REPAIR_RETRIES:
        log.info("graph.route", node="review_patch", decision="repair_retry", retry_count=retry_count + 1)
        return "repair_retry"

    log.info("graph.route", node="review_patch", decision="post_comment", approved=False)
    return "post_comment"


def route_after_gate(state: AgentState) -> str:
    if state.get("gate_decision", {}).get("passed"):
        return "apply_patch"
    return "post_comment"


def route_after_evaluate(state: AgentState) -> str:
    return "open_mr" if state.get("sandbox_outcome") == "pass" else "post_comment"


async def _repair_retry(state: AgentState) -> AgentState:
    """Bump the retry counter and hand the reviewer's concerns to generate_patch
    as feedback before looping back — the bounded "smarter agent" improvement:
    one cheap extra hop instead of a full self-healing sandbox loop."""
    verdict = state.get("review_verdict", {})
    return {
        **state,
        "repair_retry_count": state.get("repair_retry_count", 0) + 1,
        "repair_feedback": verdict.get("concerns", ""),
    }


# ---------------------------------------------------------------------------
# Run A — diagnosis → sandbox trigger
# ---------------------------------------------------------------------------

def build_run_a_graph():
    graph = StateGraph(AgentState)

    graph.add_node("fetch_logs", fetch_logs)
    graph.add_node("parse_error", parse_error)
    graph.add_node("diagnose", diagnose)
    graph.add_node("fetch_repo_context", fetch_repo_context)
    graph.add_node("generate_patch", generate_patch)
    graph.add_node("review_patch", review_patch)
    graph.add_node("repair_retry", _repair_retry)
    graph.add_node("evaluate_gate", evaluate_gate)
    graph.add_node("apply_patch", apply_patch)
    graph.add_node("trigger_rebuild", trigger_rebuild)
    graph.add_node("post_comment", post_comment)

    graph.set_entry_point("fetch_logs")
    graph.add_edge("fetch_logs", "parse_error")

    graph.add_conditional_edges(
        "parse_error", route_after_parse,
        {"diagnose": "diagnose", "post_comment": "post_comment"},
    )
    graph.add_edge("diagnose", "fetch_repo_context")
    graph.add_conditional_edges(
        "fetch_repo_context", route_after_fetch_context,
        {"generate_patch": "generate_patch", "post_comment": "post_comment"},
    )
    graph.add_edge("generate_patch", "review_patch")
    graph.add_conditional_edges(
        "review_patch", route_after_review,
        {"evaluate_gate": "evaluate_gate", "repair_retry": "repair_retry", "post_comment": "post_comment"},
    )
    graph.add_edge("repair_retry", "generate_patch")
    graph.add_conditional_edges(
        "evaluate_gate", route_after_gate,
        {"apply_patch": "apply_patch", "post_comment": "post_comment"},
    )
    graph.add_edge("apply_patch", "trigger_rebuild")

    # Run A ends here — no polling, no waiting on the sandbox build.
    graph.add_edge("trigger_rebuild", END)
    graph.add_edge("post_comment", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Run B — sandbox result → MR / comment (resumed by /callback)
# ---------------------------------------------------------------------------

def build_run_b_graph():
    graph = StateGraph(AgentState)

    graph.add_node("evaluate_result", evaluate_result)
    graph.add_node("open_mr", open_mr)
    graph.add_node("post_comment", post_comment)

    graph.set_entry_point("evaluate_result")
    graph.add_conditional_edges(
        "evaluate_result", route_after_evaluate,
        {"open_mr": "open_mr", "post_comment": "post_comment"},
    )
    graph.add_edge("open_mr", END)
    graph.add_edge("post_comment", END)

    return graph.compile()


_run_a_graph = None
_run_b_graph = None


def get_run_a_graph():
    global _run_a_graph
    if _run_a_graph is None:
        _run_a_graph = build_run_a_graph()
    return _run_a_graph


def get_run_b_graph():
    global _run_b_graph
    if _run_b_graph is None:
        _run_b_graph = build_run_b_graph()
    return _run_b_graph


# Backwards-compatible alias used by a couple of older call sites/tests.
def get_graph():
    return get_run_a_graph()


# ---------------------------------------------------------------------------
# Entry points called by the RQ worker
# ---------------------------------------------------------------------------

def _initial_state(payload: dict) -> AgentState:
    return {
        "job_id": payload.get("job_id", ""),
        "pipeline_id": payload["pipeline_id"],
        "project_id": payload["project_id"],
        "commit_sha": payload["commit_sha"],
        "branch": payload["branch"],
        "build_type": payload["build_type"],
        "failed_job_id": payload["failed_job_id"],
        "log_path": payload.get("log_path", ""),
        "task_log_path": payload.get("task_log_path"),
        "raw_log": "",
        "task_log": "",
        "error_context": {},
        "diagnosis": {},
        "repo_context": {},
        "existing_files": [],
        "missing_files": [],
        "patch_proposal": {},
        "review_verdict": {},
        "gate_decision": {},
        "sandbox_branch": "",
        "sandbox_pipeline_id": 0,
        "sandbox_outcome": "",
        "outcome": "",
        "attempt_count": payload.get("attempt_count", 1),
        "repair_retry_count": 0,
        "repair_feedback": None,
        "error_message": None,
    }


def run_graph_job(payload: dict):
    """
    RQ entry point for Run A. Runs fetch_logs → ... → trigger_rebuild and
    returns immediately — never blocks on the sandbox build. If a sandbox
    pipeline was actually triggered, the final state is saved to Redis for
    the /callback-driven Run B continuation to pick up.

    An unhandled exception anywhere in the graph (e.g. every configured LLM —
    including the paid fallback — failing) must never vanish into a crashed
    RQ job with no trace on the failing commit. Fall back to post_comment
    directly so the failure is always visible where a human will look.
    """
    from services.state_store import save_run_a_state

    log.info("graph.run_a.start", pipeline_id=payload.get("pipeline_id"))

    initial_state = _initial_state(payload)
    graph = get_run_a_graph()

    try:
        final_state = asyncio.run(graph.ainvoke(initial_state))
    except Exception as e:
        log.error("graph.run_a.crashed", pipeline_id=payload.get("pipeline_id"), error=str(e))
        crashed_state = {**initial_state, "error_message": f"Agent error: {e}"}
        final_state = asyncio.run(post_comment(crashed_state))
        log.info(
            "graph.run_a.complete",
            pipeline_id=payload.get("pipeline_id"),
            sandbox_pipeline_id=0,
            outcome=final_state.get("outcome"),
            crashed=True,
        )
        return final_state

    sandbox_pipeline_id = final_state.get("sandbox_pipeline_id")
    if sandbox_pipeline_id:
        save_run_a_state(sandbox_pipeline_id, dict(final_state))
        log.info("graph.run_a.state_saved", sandbox_pipeline_id=sandbox_pipeline_id)
    else:
        log.info("graph.run_a.no_sandbox", pipeline_id=payload.get("pipeline_id"), outcome=final_state.get("outcome"))

    log.info(
        "graph.run_a.complete",
        pipeline_id=payload.get("pipeline_id"),
        sandbox_pipeline_id=sandbox_pipeline_id,
        outcome=final_state.get("outcome"),
    )
    return final_state


def run_continuation_job(sandbox_pipeline_id: int, sandbox_status: str):
    """
    RQ entry point for Run B, enqueued by /callback. Loads the Run-A state
    saved for this sandbox pipeline and resumes evaluate_result → open_mr /
    post_comment.
    """
    from services.state_store import load_run_a_state, delete_run_a_state

    log.info("graph.run_b.start", sandbox_pipeline_id=sandbox_pipeline_id, status=sandbox_status)

    saved_state = load_run_a_state(sandbox_pipeline_id)
    if saved_state is None:
        log.warning("graph.run_b.no_saved_state", sandbox_pipeline_id=sandbox_pipeline_id)
        return None

    status_map = {"success": "pass", "failed": "fail", "canceled": "fail"}
    saved_state["sandbox_outcome"] = status_map.get(sandbox_status, "fail")

    graph = get_run_b_graph()
    final_state = asyncio.run(graph.ainvoke(saved_state))

    delete_run_a_state(sandbox_pipeline_id)

    log.info(
        "graph.run_b.complete",
        sandbox_pipeline_id=sandbox_pipeline_id,
        outcome=final_state.get("outcome"),
    )
    return final_state
