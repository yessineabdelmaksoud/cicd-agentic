"""
Reaper (fix.md FIX-7) — closes out sandbox pipelines that never call back.

/callback is the primary trigger for Run B; this is only a safety net for
the case where validate.yml itself never ran or its callback step was
dropped (infra hiccup, runner died, etc.) — GitLab's own pipeline status is
ground truth. Self re-schedules via RQ's built-in scheduler (worker.py runs
with_scheduler=True), so no separate cron/sidecar is needed.
"""

import os
from datetime import timedelta
import structlog
from redis import Redis
from rq import Queue

from services.state_store import list_pending_sandbox_ids, load_run_a_state

log = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REAP_INTERVAL_SECONDS = int(os.getenv("REAP_INTERVAL_SECONDS", "600"))


def reap_stuck_sandboxes() -> None:
    """Check every pending Run-A state against GitLab's real pipeline status;
    close out anything that finished but never triggered /callback."""
    from services.gitlab_client import get_gitlab_client
    from core.graph import run_continuation_job

    ids = list_pending_sandbox_ids()
    if not ids:
        return

    client = get_gitlab_client()
    for sandbox_pipeline_id in ids:
        state = load_run_a_state(sandbox_pipeline_id)
        if not state:
            continue
        try:
            pipeline = client.get_pipeline(project_id=state["project_id"], pipeline_id=sandbox_pipeline_id)
        except Exception as e:
            log.warning("reaper.pipeline_lookup_failed", sandbox_pipeline_id=sandbox_pipeline_id, error=str(e))
            continue

        status = pipeline.get("status")
        if status in ("success", "failed", "canceled"):
            log.warning("reaper.closing_stuck_sandbox", sandbox_pipeline_id=sandbox_pipeline_id, status=status)
            run_continuation_job(sandbox_pipeline_id, status)


def _reap_and_reschedule() -> None:
    try:
        reap_stuck_sandboxes()
    finally:
        redis_conn = Redis.from_url(REDIS_URL)
        schedule_reaper(Queue("agent-jobs", connection=redis_conn))


def schedule_reaper(queue: Queue) -> None:
    queue.enqueue_in(timedelta(seconds=REAP_INTERVAL_SECONDS), _reap_and_reschedule)
