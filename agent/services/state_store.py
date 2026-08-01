"""
Redis-backed state persistence for the Run A → Run B split (fix.md FIX-7).

Run A ends at trigger_rebuild and the RQ worker returns immediately — no
worker is ever parked for the duration of a sandbox build. `validate.yml`'s
`/callback` later resumes Run B by loading the state saved here, keyed by
`sandbox_pipeline_id`.
"""

import json
import os
from redis import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STATE_TTL_SECONDS = 6 * 3600       # v5 §8.5
MR_OPENED_TTL_SECONDS = 24 * 3600  # idempotency guard window


def _redis() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


def save_run_a_state(sandbox_pipeline_id: int, state: dict) -> None:
    _redis().setex(f"state:{sandbox_pipeline_id}", STATE_TTL_SECONDS, json.dumps(state, default=str))


def load_run_a_state(sandbox_pipeline_id: int) -> dict | None:
    raw = _redis().get(f"state:{sandbox_pipeline_id}")
    return json.loads(raw) if raw else None


def delete_run_a_state(sandbox_pipeline_id: int) -> None:
    _redis().delete(f"state:{sandbox_pipeline_id}")


def try_claim_mr_opened(sandbox_pipeline_id: int) -> bool:
    """Idempotency guard (fix.md FIX-7): True on the first claim (proceed to
    open the MR), False if already claimed — a duplicate callback is a no-op."""
    return bool(_redis().set(f"mr_opened:{sandbox_pipeline_id}", "1", nx=True, ex=MR_OPENED_TTL_SECONDS))


def list_pending_sandbox_ids() -> list:
    """Sandbox pipelines with saved Run-A state that hasn't been consumed yet —
    used by the reaper to find pipelines that never called back."""
    ids = []
    for key in _redis().keys("state:*"):
        try:
            ids.append(int(key.split(":", 1)[1]))
        except (IndexError, ValueError):
            continue
    return ids
