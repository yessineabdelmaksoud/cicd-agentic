"""
API Routes — /webhook, /webhook/mr, /callback, /health, /metrics (prometheus)
"""

import os
import uuid
import structlog
from fastapi import APIRouter, HTTPException, Header, Request
from redis import Redis
from rq import Queue

from api.schemas import WebhookPayload, WebhookResponse, CallbackPayload, HealthResponse
from services.openrouter_client import AGENT_MODELS
from services.metrics import webhooks_received, mr_opened_total, mr_merged_total, queue_depth

log = structlog.get_logger()

router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "2"))  # fix.md FIX-12 — 2 everywhere, not 3
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


def _get_redis() -> Redis:
    return Redis.from_url(REDIS_URL)


def _verify_webhook_secret(x_gitlab_token: str | None) -> None:
    """fix.md FIX-13 — reject unmatched tokens so a forged failure on the
    network can't spend LLM budget or create branches."""
    if not WEBHOOK_SECRET:
        log.warning("webhook.secret_not_configured")
        return
    if x_gitlab_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Gitlab-Token")


# ---------------------------------------------------------------------------
# POST /webhook — Receives failed-build notifications from GitLab CI
# ---------------------------------------------------------------------------
@router.post("/webhook", response_model=WebhookResponse, status_code=202)
async def receive_webhook(payload: WebhookPayload, x_gitlab_token: str | None = Header(default=None)):
    """
    Accepts a build-failure webhook from GitLab CI's notify job.
    Enqueues Run A (core.graph.run_graph_job) in Redis and returns 202 immediately.
    """
    _verify_webhook_secret(x_gitlab_token)

    redis_conn = _get_redis()
    webhooks_received.labels(build_type=payload.build_type).inc()

    attempt_key = f"remediation:{payload.commit_sha}"
    attempt_count = redis_conn.incr(attempt_key)
    redis_conn.expire(attempt_key, 86400)  # 24h TTL

    if attempt_count > MAX_ATTEMPTS:
        log.warning("webhook.attempt_cap", sha=payload.commit_sha, count=attempt_count)
        raise HTTPException(
            status_code=429,
            detail=f"Max remediation attempts ({MAX_ATTEMPTS}) reached for commit {payload.commit_sha}. Manual review required.",
        )

    if not payload.log_path:
        payload.log_path = f"pipeline-{payload.pipeline_id}-job-{payload.failed_job_id}.log"

    job_id = str(uuid.uuid4())
    queue = Queue("agent-jobs", connection=redis_conn)

    job_payload = payload.model_dump()
    job_payload["job_id"] = job_id
    job_payload["attempt_count"] = attempt_count

    queue.enqueue(
        "core.graph.run_graph_job",
        job_payload,
        job_id=job_id,
        # Run A only diagnoses + triggers — no sandbox wait. 600s gives the
        # LLM fallback chain (3 LLM-calling nodes, each walking multiple
        # models on failure) real headroom without going back to "worker
        # parked for hours" — if it's ever hit, run_graph_job's own
        # try/except still degrades to post_comment rather than a bare
        # RQ timeout with no trace on the commit.
        job_timeout=600,
        result_ttl=3600,
    )

    log.info(
        "webhook.accepted",
        job_id=job_id,
        pipeline_id=payload.pipeline_id,
        commit_sha=payload.commit_sha,
        build_type=payload.build_type,
        attempt=attempt_count,
    )

    return WebhookResponse(
        status="accepted",
        job_id=job_id,
        message=f"Remediation queued (attempt {attempt_count}/{MAX_ATTEMPTS})",
    )


# ---------------------------------------------------------------------------
# POST /callback — validate.yml result on the sandbox branch (Run B trigger)
# ---------------------------------------------------------------------------
@router.post("/callback", status_code=202)
async def receive_callback(payload: CallbackPayload, x_gitlab_token: str | None = Header(default=None)):
    """
    Resumes Run B (evaluate_result → open_mr/post_comment) by enqueueing
    core.graph.run_continuation_job with the saved Run-A state. Never polls —
    this IS the trigger.
    """
    _verify_webhook_secret(x_gitlab_token)

    redis_conn = _get_redis()
    queue = Queue("agent-jobs", connection=redis_conn)

    job_id = f"continuation-{payload.sandbox_pipeline_id}"
    queue.enqueue(
        "core.graph.run_continuation_job",
        payload.sandbox_pipeline_id,
        payload.status,
        job_id=job_id,
        job_timeout=120,
        result_ttl=3600,
    )

    log.info(
        "callback.received",
        sandbox_pipeline_id=payload.sandbox_pipeline_id,
        branch=payload.sandbox_branch,
        status=payload.status,
    )
    return {"received": True, "sandbox_pipeline_id": payload.sandbox_pipeline_id, "status": payload.status}


# ---------------------------------------------------------------------------
# POST /webhook/mr — GitLab Merge Request Hook (fix.md FIX-14: acceptance = merged)
# ---------------------------------------------------------------------------
@router.post("/webhook/mr", status_code=200)
async def receive_mr_webhook(request: Request, x_gitlab_token: str | None = Header(default=None)):
    """
    GitLab's Merge Request Hook fires on every MR state change. This is the
    authoritative source for "was an AI-fix MR actually opened / merged" —
    more reliable than trusting our own create_merge_request() call succeeded
    without a race, and it's the only way to observe a human merging it.
    """
    _verify_webhook_secret(x_gitlab_token)

    body = await request.json()
    if body.get("object_kind") != "merge_request":
        return {"ignored": True}

    attrs = body.get("object_attributes", {})
    labels = [l.get("title") for l in body.get("labels", []) or []]
    if "ai-fix" not in labels:
        return {"ignored": True, "reason": "not an ai-fix MR"}

    action = attrs.get("action")
    if action == "open":
        mr_opened_total.inc()
    elif action == "merge":
        mr_merged_total.inc()

    log.info("webhook.mr", action=action, iid=attrs.get("iid"))
    return {"received": True, "action": action}


# ---------------------------------------------------------------------------
# GET /health — Liveness + readiness check
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthResponse)
async def health():
    """Returns service health including Redis, MinIO, model config, and queue depth."""
    try:
        redis_conn = _get_redis()
        redis_conn.ping()
        redis_status = "ok"
        depth = Queue("agent-jobs", connection=redis_conn).count
        queue_depth.set(depth)
    except Exception as e:
        redis_status = f"error: {e}"
        depth = None

    try:
        from services.minio_client import get_minio_client
        client = get_minio_client()
        client.list_buckets()
        minio_status = "ok"
    except Exception as e:
        minio_status = f"error: {e}"

    return HealthResponse(
        status="ok",
        models=dict(AGENT_MODELS),
        redis=redis_status,
        minio=minio_status,
        queue_depth=depth,
    )
