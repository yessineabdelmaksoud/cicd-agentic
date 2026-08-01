"""
Prometheus Metrics — Custom metrics for the AI agent (fix.md FIX-14).

Beyond raw success/latency, these answer the two questions a team actually
trusts: "how often does this help?" (MR merged rate, not just opened) and
"what does it cost?" (cost per remediation, gate-rejection breakdown, queue
depth).
"""

from prometheus_client import Histogram, Counter, Gauge

# ---------------------------------------------------------------------------
# LLM Latency (per agent role and model)
# ---------------------------------------------------------------------------
llm_latency = Histogram(
    "agent_llm_duration_seconds",
    "Duration of LLM API calls",
    ["agent_role", "model"],
    buckets=[1, 2, 5, 10, 20, 30, 45, 60, 90, 120],
)

# ---------------------------------------------------------------------------
# LLM cost (fix.md FIX-14 — cost per remediation, derived via rate()/count() in Grafana)
# ---------------------------------------------------------------------------
llm_cost_usd_total = Counter(
    "agent_llm_cost_usd_total",
    "Cumulative estimated USD cost of LLM calls",
    ["agent_role", "model"],
)


def record_llm_cost(agent_role: str, model: str, cost_usd: float) -> None:
    llm_cost_usd_total.labels(agent_role=agent_role, model=model).inc(max(0.0, cost_usd))


# ---------------------------------------------------------------------------
# Node execution duration
# ---------------------------------------------------------------------------
node_duration = Histogram(
    "agent_node_duration_seconds",
    "Duration of each LangGraph node execution",
    ["node"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300],
)

# ---------------------------------------------------------------------------
# Fix attempt outcomes
# ---------------------------------------------------------------------------
FIX_OUTCOMES = [
    "diagnosed_by_rule", "diagnosed_by_llm",
    "pass", "fail", "low_confidence", "manual_review", "timeout",
]

fix_attempts = Counter(
    "agent_fix_attempts_total",
    "Total fix attempts by outcome",
    ["outcome"],
)

# ---------------------------------------------------------------------------
# Objective gate rejections (fix.md FIX-6/FIX-14 — which hard check fails most)
# ---------------------------------------------------------------------------
gate_rejection_total = Counter(
    "agent_gate_rejection_total",
    "Objective gate hard-check failures by check name",
    ["check"],  # paths_exist | content_changed | diff_confined | reviewer_approved
)

# ---------------------------------------------------------------------------
# Reviewer confidence distribution
# ---------------------------------------------------------------------------
reviewer_confidence_hist = Histogram(
    "agent_reviewer_confidence",
    "Reviewer confidence score distribution",
    buckets=[0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0],
)

# ---------------------------------------------------------------------------
# Webhook counter
# ---------------------------------------------------------------------------
webhooks_received = Counter(
    "agent_webhooks_total",
    "Total webhooks received",
    ["build_type"],
)

# ---------------------------------------------------------------------------
# MR lifecycle — "acceptance" must mean merged, not opened (fix.md FIX-14)
# ---------------------------------------------------------------------------
mr_opened_total = Counter("agent_mr_opened_total", "AI-opened merge requests")
mr_merged_total = Counter("agent_mr_merged_total", "AI-opened merge requests actually merged by a human")

# ---------------------------------------------------------------------------
# Active jobs / queue depth
# ---------------------------------------------------------------------------
active_jobs = Gauge(
    "agent_active_jobs",
    "Number of agent jobs currently processing",
)

queue_depth = Gauge(
    "agent_queue_depth",
    "Number of jobs currently waiting in the Redis agent-jobs queue",
)


def init_metrics():
    """Pre-initialize metric label combinations so they appear in Prometheus from startup."""
    for outcome in FIX_OUTCOMES:
        fix_attempts.labels(outcome=outcome)
    for build_type in ["yocto", "zephyr", "qnx"]:
        webhooks_received.labels(build_type=build_type)
    for check in ["paths_exist", "content_changed", "diff_confined", "reviewer_approved"]:
        gate_rejection_total.labels(check=check)
