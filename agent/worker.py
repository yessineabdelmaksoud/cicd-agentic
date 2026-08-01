"""
Worker — Redis Queue Consumer (RQ)
Consumes jobs from the 'agent-jobs' queue: Run A (run_graph_job), Run B
continuations (run_continuation_job, triggered by /callback), and the
self-rescheduling reaper (fix.md FIX-7).

Every LangGraph node metric (node_duration, fix_attempts, gate_rejection,
llm_cost, reviewer_confidence) is incremented from code that only ever runs
inside THIS process, not the FastAPI agent process — prometheus_client's
default registry is per-process, and the agent/worker are separate pods with
no shared filesystem for multiprocess mode. Without its own scrape endpoint,
every one of those metrics stays permanently at zero on the agent's
/metrics (confirmed live: a real end-to-end run left agent_fix_attempts_total
at 0 everywhere). start_http_server gives this process its own endpoint.
"""

import os
import structlog
from redis import Redis
from rq import Worker, Queue
from prometheus_client import start_http_server

from services.reaper import schedule_reaper
from services.metrics import init_metrics

log = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Fixed, not env-configurable: Kubernetes auto-injects a same-named
# WORKER_METRICS_PORT=tcp://<ip>:9100 service-discovery variable for any
# Service named "worker-metrics" in this namespace, which collides with and
# shadows an env-var-based port here (hit this live — os.getenv returned the
# k8s-injected "tcp://10.43.x.x:9100" string instead of an int).
WORKER_METRICS_PORT = 9100


def main():
    init_metrics()
    start_http_server(WORKER_METRICS_PORT)
    log.info("worker.metrics_server_started", port=WORKER_METRICS_PORT)

    redis_conn = Redis.from_url(REDIS_URL)
    queue = Queue("agent-jobs", connection=redis_conn)

    schedule_reaper(queue)

    log.info("worker.start", redis=REDIS_URL, queues=["agent-jobs"])

    worker = Worker([queue], connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
