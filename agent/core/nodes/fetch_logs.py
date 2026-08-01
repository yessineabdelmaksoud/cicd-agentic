"""
Node — fetch_logs
Downloads the build log (and, for Yocto, the per-task log.do_* if the CI
notify step uploaded one) from MinIO. The task log lets parse_error anchor on
the real BitBake failure instead of the top-level ERROR: summary (fix.md
FIX-5).
"""

import structlog
from core.state import AgentState
from services.minio_client import get_minio_client
from services.metrics import node_duration

log = structlog.get_logger()

BUCKET = "build-logs"


def _download(client, bucket: str, path: str) -> str:
    response = client.get_object(bucket, path)
    try:
        return response.read().decode("utf-8", errors="replace")
    finally:
        response.close()
        response.release_conn()


async def fetch_logs(state: AgentState) -> AgentState:
    """Download build log (+ optional per-task log) from MinIO."""
    with node_duration.labels(node="fetch_logs").time():
        log_path = state["log_path"]
        task_log_path = state.get("task_log_path")
        log.info("fetch_logs.start", log_path=log_path, task_log_path=task_log_path)

        client = get_minio_client()

        try:
            raw_log = _download(client, BUCKET, log_path)
            log.info("fetch_logs.success", bytes=len(raw_log))
        except Exception as e:
            log.error("fetch_logs.error", error=str(e), log_path=log_path)
            return {**state, "raw_log": f"ERROR: Could not fetch log: {e}", "task_log": "", "error_message": str(e)}

        task_log = ""
        if task_log_path:
            try:
                task_log = _download(client, BUCKET, task_log_path)
                log.info("fetch_logs.task_log_success", bytes=len(task_log))
            except Exception as e:
                log.warning("fetch_logs.task_log_missing", error=str(e), task_log_path=task_log_path)

        return {**state, "raw_log": raw_log, "task_log": task_log}
