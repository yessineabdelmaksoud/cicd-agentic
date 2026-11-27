# AI-Driven CI/CD Build Platform — Embedded Projects

> Stage KPIT | v5.0 — K3s · GitLab CE · LangGraph · OpenRouter
> Implements `doc/Implementation plan v5.md` + `doc/fix.md` (Tier 1–3). This file
> is the single source of truth for the platform as actually deployed — the
> other planning docs under `doc/` are historical and superseded (see §11).

A self-hosted CI/CD platform for embedded projects (Yocto / Zephyr / QNX-style).
When a build fails, an AI agent reads the real log, locates the real error,
fetches the real file from GitLab, writes a real patch, validates it in a
sandbox pipeline, and opens a GitLab Merge Request — **never auto-merged, a
human always approves.**

---

## Table of contents

1. [Architecture](#1-architecture)
2. [Data flow — Run A / Run B](#2-data-flow--run-a--run-b)
3. [Repository structure](#3-repository-structure)
4. [One-time setup on a new machine](#4-one-time-setup-on-a-new-machine)
5. [Day-to-day commands](#5-day-to-day-commands)
6. [Running a real end-to-end test](#6-running-a-real-end-to-end-test)
7. [Networking model](#7-networking-model)
8. [Security](#8-security)
9. [Observability](#9-observability)
10. [Troubleshooting](#10-troubleshooting)
11. [Docs index](#11-docs-index)
12. [Known limitations / backlog](#12-known-limitations--backlog)

---

## 1. Architecture

Everything runs as K3s pods in the `default` namespace on a single machine.

```
Machine (24 GB RAM target)
├── K3s                 → single-node Kubernetes
├── GitLab CE            → source control + CI/CD                (svc: gitlab, port 80)
├── GitLab Runner        → Kubernetes executor, ephemeral build pods
├── MinIO                → build-log / artifact storage           (svc: minio, port 9000)
├── Redis                → job queue + saved Run-A state          (svc: redis, port 6379)
├── AI Agent (FastAPI)   → webhook / callback receiver             (svc: agent, port 8000)
├── AI Worker (RQ)       → runs the LangGraph pipeline + reaper    (svc: worker-metrics, port 9100)
├── Prometheus           → metrics                                 (port 9090)
├── Grafana              → dashboards                               (port 3000)
└── Loki + Promtail      → aggregated pod logs                      (port 3100)
```

**Why the Agent and Worker are two separate deployments:** the FastAPI Agent
only ever does two cheap things — accept a webhook and enqueue a job, or
accept a callback and enqueue a continuation. The Worker is what actually
runs the (potentially slow, LLM-bound) LangGraph pipeline. Splitting them
means a slow LLM call never blocks webhook ingestion, and either can restart
independently. **They are separate processes with separate in-memory
Prometheus registries** — that's why the Worker runs its own metrics HTTP
server on port 9100 rather than sharing the Agent's `/metrics`.

**Models** (`agent/services/openrouter_client.py — AGENT_MODELS`):

| Role | Primary | Fallback chain (tried in order on failure) |
|---|---|---|
| Diagnostician | `qwen/qwen3-coder:free` | `qwen/qwen3-coder` → `google/gemma-4-31b-it:free` → `nvidia/nemotron-3-super-120b-a12b:free` |
| Patch Generator | `deepseek/deepseek-chat-v3-0324` | `nvidia/nemotron-3-super-120b-a12b:free` → `openai/gpt-oss-20b:free` |
| Reviewer | `anthropic/claude-sonnet-4-5` | `openai/gpt-oss-20b:free` → `google/gemma-4-31b-it:free` |

The chain exists because live testing showed OpenRouter's free tier rate-limits
**per upstream provider, not per model** (several unrelated `:free` models
failed together), and paid billing can intermittently 402 even with credits
present. Mixing providers/tiers in the chain survives either failure mode.

**Rules-first, LLM-second** (`agent/core/rules/`): a regex signature table
classifies the failure *before* any LLM call. A few categories (currently:
Yocto checksum mismatches) carry a fully deterministic fix extracted straight
from the log — those resolve with **zero LLM calls**. Everything else still
gets a narrowed, primed prompt instead of a blank slate.

---

## 2. Data flow — Run A / Run B

The pipeline is split into two LangGraph graphs joined by a GitLab CI
callback, so a worker is never blocked waiting on a sandbox build.

### Run A — diagnosis → sandbox trigger (webhook-triggered, ends in seconds–tens of seconds)

```
GitLab pipeline fails
  → notify job uploads build.log (+ task log) to MinIO
  → POSTs /webhook (X-Gitlab-Token: WEBHOOK_SECRET) to the Agent
       │
       ▼ 202, enqueue on Redis
  ┌─────────────────────────────────────────────────────────────────┐
  │ fetch_logs → parse_error (rules engine) ─┬─ no match ──→ post_comment
  │                                          │
  │                    ┌── deterministic rule fix: skip LLM ──┐
  │                    ▼                                      │
  │                 diagnose ───────────────────────────────► │
  │                    │                                      │
  │                    ▼                                      │
  │           fetch_repo_context ─┬─ no candidate file exists ─→ post_comment
  │                    │          (never invents file content)
  │                    ▼
  │            generate_patch  ◄──────────────┐ (repair retry, max 1)
  │                    │                       │
  │                    ▼                       │
  │             review_patch ──── rejected, retryable ────────┘
  │                    │
  │           ┌── approved ──┐── rejected, not retryable ──→ post_comment
  │           ▼
  │       evaluate_gate (OBJECTIVE checks — not LLM confidence)
  │           │
  │      ┌─ passed ─┐── failed any hard check ──→ post_comment (no sandbox spent)
  │      ▼
  │  apply_patch → trigger_rebuild → [state saved to Redis]  ◄── WORKER ENDS HERE
  └─────────────────────────────────────────────────────────────────┘
```

`evaluate_gate`'s **hard** checks (any failing = reject, no sandbox build):
`paths_exist` (every edited file was actually fetched — a hallucinated path
is rejected here), `content_changed` (not a no-op), `diff_confined` (no file
outside what was investigated), `reviewer_approved`. **Soft** checks
(`diff_small`, `known_category`) only decide Draft vs Normal MR. The
reviewer's self-reported confidence is a tiebreaker, never the sole gate.

### Run B — sandbox result → MR / comment (resumed by `/callback`, not polling)

```
validate.yml runs on ai-fix/<pipeline_id>, POSTs /callback with the result
  → Agent enqueues run_continuation_job(sandbox_pipeline_id, status)
       │
       ▼
  evaluate_result ─┬─ pass ─→ open_mr (idempotent — duplicate callback = no-op)
                    └─ fail ─→ post_comment + delete the sandbox branch
```

A **reaper** (`agent/services/reaper.py`) runs inside the Worker and
re-schedules itself every `REAP_INTERVAL_SECONDS`; it checks any saved Run-A
state whose sandbox pipeline finished on GitLab's side but never called back
(infra hiccup) and closes it out — so nothing is ever left hanging forever.

---

## 3. Repository structure

```
ai-cicd-embedded/
├── agent/                      # The AI agent (FastAPI + RQ worker)
│   ├── main.py                 # FastAPI app entry point
│   ├── worker.py               # RQ worker entry point + its own /metrics:9100
│   ├── Dockerfile               # Single image; agent vs worker = same image,
│   │                            # different container `args` (see k8s manifests)
│   ├── requirements.txt         # Pinned for Python 3.11 (matches the Dockerfile base)
│   ├── pytest.ini
│   ├── api/
│   │   ├── routes.py            # /webhook, /callback, /webhook/mr, /health
│   │   └── schemas.py           # Pydantic request/response models
│   ├── core/
│   │   ├── state.py             # AgentState — the TypedDict threaded through every node
│   │   ├── graph.py             # Builds Run A / Run B LangGraph graphs + RQ entry points
│   │   ├── nodes/                # One file per pipeline step (see §2 diagram)
│   │   └── rules/                # Rules-first classification (yocto/zephyr/qnx signature tables)
│   └── services/
│       ├── gitlab_client.py     # GitLab REST v4 wrapper (branches, files, MRs, pipelines)
│       ├── minio_client.py      # Build log / task log download
│       ├── openrouter_client.py # LLM client: model chain, structured output, cost tracking
│       ├── metrics.py           # All Prometheus metric definitions
│       ├── state_store.py       # Redis-backed Run-A state save/load + MR idempotency
│       └── reaper.py            # Self-rescheduling orphaned-sandbox closer
│
├── docker/                      # Build-environment images for the demo projects
│   ├── yocto/Dockerfile
│   ├── zephyr/Dockerfile        # Downloads `mc` (MinIO client) at build time
│   └── qnx/Dockerfile           # Cross-compiled C stand-in (no QNX SDP license)
│
├── pipelines/templates/         # Reusable GitLab CI job templates (fix.md)
│   ├── notify.yml               # `.notify_on_failure` — upload log, POST /webhook
│   └── validate.yml             # `.validate_on_ai_fix_branch` — POST /callback
│                                 # (demo projects inline these — see §6, they're
│                                 #  separate GitLab repos and can't `include: local:`
│                                 #  a file living in this repo)
│
├── infra/
│   ├── k3s/                     # Raw Kubernetes manifests, applied with `kubectl apply -R`
│   │   ├── core/env-configmap.yaml   # Non-secret config (URLs, ports)
│   │   ├── agent/                    # Agent + Worker Deployments/Services
│   │   ├── gitlab/                   # GitLab CE + Runner
│   │   ├── storage/                  # MinIO + Redis
│   │   └── observability/            # Prometheus/Grafana/Loki/Promtail Deployments
│   │       # (their actual CONFIG files, e.g. prometheus.yml, live in
│   │       #  ../../observability/ at the repo root, hostPath-mounted in — see below)
│   └── scripts/                 # Setup/verify scripts, see §5
│
├── observability/                # Actual config files mounted into the pods above
│   ├── prometheus/prometheus.yml
│   ├── grafana/{dashboards,provisioning}/
│   ├── loki/loki-config.yaml
│   └── promtail/promtail-config.yaml
│
├── scripts/                      # Top-level operator scripts (see §5)
├── tests/
│   ├── unit/                     # Rules engine, parse_error, evaluate_gate — no network
│   └── integration/              # Full Run A/Run B graphs, LLM/GitLab/MinIO mocked
├── .env.example                  # Copy to .env and fill in
├── Makefile                      # `make help` for the full command list
└── README.md                     # This file
```

**Things intentionally NOT in this repo (moved/removed during cleanup):**
- `docker/zephyr/mc` — was a committed binary; now downloaded in the
  Dockerfile at build time instead.
- `infra/observability/`, `infra/grafana/`, `infra/gitlab/` — stray duplicate
  directories never referenced by any script or manifest; deleted.
- `zephyr-test/` — was a local git clone of the live `zephyr-demo` GitLab
  project with a plaintext token embedded in `.git/config`; deleted (redundant
  with the project that already lives in GitLab).
- `step1.md`…`step4.md`, `command.md` — day-by-day recap docs describing the
  pre-redesign 9-node pipeline; archived to `doc/history/`, content folded
  into this README.

---

## 4. One-time setup on a new machine

There is **no single fully-automated one-click command** — a couple of steps
need `sudo` for a real interactive password (installing K3s, importing Docker
images into K3s' separate containerd store), which can't be scripted around.
Everything else is one `make` command each.

```bash
# 0. Prerequisites: Ubuntu 22.04+, Docker, 24 GB RAM recommended, 50 GB+ disk
git clone <this-repo> ai-cicd-embedded && cd ai-cicd-embedded
cp .env.example .env
# Edit .env: fill in OPENROUTER_API_KEY. Generate WEBHOOK_SECRET with:
#   openssl rand -hex 32 >> .env   (as WEBHOOK_SECRET=<value>)
# Leave GITLAB_PROJECT_TOKEN / GITLAB_PROJECT_ID empty for now — filled in step 3.

# 1. Cluster + full stack (installs K3s if missing, applies every manifest,
#    creates the env-secret K8s Secret from .env)
make up
watch kubectl get pods     # wait for everything Running (GitLab takes ~3-5 min)

# 2. GitLab bootstrap
kubectl exec deployment/gitlab -- cat /etc/gitlab/initial_root_password
# Visit http://localhost, sign in as root (this file is only valid for 24h
# after GitLab's first boot — reset the password via the Rails console if
# it's expired: kubectl exec -it deployment/gitlab -- gitlab-rails console)
make setup-gitlab          # creates the "platform" project + API token via GitLab's Rails console
#   → copy the printed GITLAB_PROJECT_TOKEN into .env
make register-runner       # registers the K3s Kubernetes-executor runner

# 3. Embedded build images (SUDO REQUIRED — imports into K3s' containerd,
#    separate from Docker's own image store: imagePullPolicy is `Never`)
make build-images

# 4. Agent (rebuilds the image, imports it — SUDO REQUIRED — and rolls out)
make apply-secret          # (re)creates env-secret from the now-complete .env
make build-agent

# 5. Verify
make verify-day1           # infra health
make verify-day3           # agent health, webhook, attempt cap, /metrics
curl http://localhost:8000/health   # if port-forwarded, or from inside a pod
```

**About the `sudo` steps:** `k3s ctr images import` requires root because
K3s' embedded containerd socket is root-owned (`/run/k3s/containerd/containerd.sock`,
mode 660). If you're driving this through an automation tool that can't
supply an interactive password (this is how this repo's own AI-assisted
upgrade was deployed), those two commands are the exact points where you'll
need to run them yourself in a real terminal.

---

## 5. Day-to-day commands

Run `make help` for the live list (auto-generated from the Makefile). Full reference:

| Command | What it does |
|---|---|
| `make up` | First deploy: installs K3s if needed, applies all manifests, creates `env-secret` |
| `make stop` | **End of day**: stops the k3s systemd service. All data (GitLab/MinIO/Redis) persists on disk — nothing is deleted. |
| `make start` | **Next morning**: starts k3s back up, waits for pods, restarts CoreDNS (see box below), re-verifies |
| `make down` | Deletes all K3s pods and re-applies-required manifests (keeps PVC data) — heavier than `stop`, not for daily use |
| `make clean` | **Destructive** — deletes pods AND volumes (GitLab/MinIO/Redis data). Asks to confirm. |
| `make status` | `kubectl get pods` |
| `make logs s=<service>` | Tail logs for one deployment, e.g. `make logs s=worker` |
| `make register-runner` | Registers the GitLab Kubernetes-executor runner |
| `make setup-gitlab` | Creates the GitLab project + API token (interactive) |
| `make apply-secret` | (Re)creates the `env-secret` K8s Secret from `.env` — run after editing secrets |
| `make build-images` | Builds + imports (sudo) the 3 embedded build images |
| `make import-images` | Re-imports already-built images into K3s containerd (e.g. after a k3s restart) |
| `make build-agent` | Rebuilds the agent/worker image, imports it (sudo), rolls out both deployments |
| `make agent-logs` | Tails agent + worker logs together |
| `make run-agent-local` | Runs the FastAPI agent on your host (not in K3s) for fast iteration |
| `make verify-day1` | Infra health check script |
| `make verify-day3` | Agent health/webhook/attempt-cap/metrics check script |
| `make test` / `test-unit` / `test-integration` | Runs the pytest suite (mocked — no live cluster needed) |
| `make demo` | Scripted demo: inject an error, wait, check for an MR |
| `make inject-error p=<project> type=<src_uri\|compile>` | Pushes a broken commit to a demo project (`yocto-demo`, `zephyr-demo`, `qnx-demo`; defaults: `yocto-demo`, `src_uri`) |

**Daily routine, once set up:** `make stop` at the end of the day, `make
start` the next morning — that's it. Grafana/Prometheus/GitLab are all
reachable immediately by hostname (§9), no `kubectl port-forward` needed.
Imported images (`make build-images`/`make build-agent`) persist across a
`stop`/`start` cycle since K3s' containerd data lives on regular disk
(`/var/lib/rancher/k3s`), not tmpfs; if one ever goes missing, `make
import-images` re-imports what's already built without rebuilding.

Direct `kubectl`/`docker` equivalents when you need finer control:

```bash
export KUBECONFIG=~/.kube/config     # needed once per shell — see §10 if this fails
kubectl get pods -o wide
kubectl logs -f deployment/worker    # this is where the LangGraph node logs actually are
kubectl exec deployment/agent -- curl -sL http://localhost:8000/health
kubectl rollout restart deployment agent worker   # after an image re-import
```

---

## 6. Running a real end-to-end test

This is exactly the flow used to verify the v5 redesign live (see the result:
`http://localhost/embedded/zephyr-demo/-/merge_requests/2`).

```bash
# 1. Make sure a demo project's CI is wired to the new agent (webhook secret +
#    /callback). Set the shared secret as a CI/CD variable on the project:
source .env
curl -s --header "PRIVATE-TOKEN: $GITLAB_PROJECT_TOKEN" \
  --form "key=WEBHOOK_SECRET" --form "value=${WEBHOOK_SECRET}" --form "masked=true" \
  "http://localhost/api/v4/projects/<project-id>/variables"

# The project's .gitlab-ci.yml needs the notify/validate logic from
# pipelines/templates/{notify,validate}.yml, inlined (see zephyr-demo's
# .gitlab-ci.yml in GitLab, or that project's git history, for the exact
# working version this repo's own tests were run against).

# 2. Clone the demo project and push a real, deterministic error
git clone "http://oauth2:${GITLAB_PROJECT_TOKEN}@localhost/embedded/zephyr-demo.git" /tmp/demo
cd /tmp/demo
# e.g. a real compile error: remove a semicolon, reference an undeclared symbol
sed -i 's/int x = 5;/int x = 5/' main.c
git commit -am "inject compile error" && git push

# 3. Watch it happen
export KUBECONFIG=~/.kube/config
kubectl logs -f deployment/worker | grep -E \
  "graph\.run_a\.|parse_error\.|diagnose\.|generate_patch\.|review_patch\.|evaluate_gate\.|apply_patch\.|trigger_rebuild\.|graph\.run_b\.|open_mr\."

# 4. Check the result
#   - A new branch ai-fix/<pipeline_id> with the real fix committed
#   - A sandbox pipeline that rebuilds it
#   - On success: an MR at .../merge_requests, labeled ai-fix, NOT auto-merged
#   - On any rejection: a comment on the original failing commit explaining why
```

**What "real" means here, concretely** — every one of these was independently
verified against the live cluster, not assumed from reading the code:
- `parse_error` anchors on the actual compiler error line, not a fixed window.
- `fetch_repo_context` pulls the byte-for-byte real file from GitLab at the
  failing commit; if the diagnosis names a file that doesn't exist there, the
  pipeline stops at that node and posts a comment — it never reaches the LLM
  patch step with invented content.
- `generate_patch`'s output is a full corrected file, diffed against what was
  actually fetched — in the verified run, exactly a 2-line change (`int x = 5`
  → `int x = 5;`), nothing else touched.
- `evaluate_gate` computed all six checks from real data (`paths_exist`,
  `content_changed`, `diff_confined`, `diff_small`, `known_category`,
  `reviewer_approved`) — not a stubbed pass.
- The sandbox pipeline is a real second GitLab pipeline run on the `ai-fix/*`
  branch, not a skip.

To exercise the **zero-LLM-call rules path** instead (faster, doesn't depend
on OpenRouter at all): push a Yocto recipe with a wrong `SRC_URI[sha256sum]`
to `yocto-demo` — `diagnose` and `generate_patch` will both skip the LLM
entirely and you'll see `review_verdict.auto_approved: true` in the logs.

---

## 7. Networking model

GitLab runs **as a K3s pod**, not on the host — everything communicates via
cluster service DNS. This deployment lives entirely in the `default`
namespace, so short service names resolve without a full FQDN.

| From | To | Address |
|---|---|---|
| Build pod / Runner | GitLab | `http://gitlab` (runner's `--clone-url`) |
| Agent / Worker | GitLab | `http://gitlab` (`GITLAB_EXTERNAL_URL`) |
| Build pod / Agent | MinIO | `http://minio:9000` |
| GitLab CI `notify` job | Agent | `http://agent:8000/webhook` |
| `validate.yml` | Agent | `http://agent:8000/callback` |
| Prometheus | Worker metrics | `http://worker-metrics:9100/metrics` |
| Prometheus | Agent metrics | `http://agent:8000/metrics` |

`host.docker.internal` / `localhost` / `127.0.0.1` must **never** appear
inside a pod's config — only in scripts that run on the *host* (e.g.
`make setup-gitlab`, `inject-error.sh`), which reach GitLab through the K3s
ingress on the host's own port 80. Verify with:

```bash
grep -rn "host.docker.internal" agent/ infra/ pipelines/ observability/   # should be empty
```

---

## 8. Security

- **Webhook authenticity**: `/webhook`, `/callback`, and `/webhook/mr` all
  reject requests whose `X-Gitlab-Token` header doesn't match `WEBHOOK_SECRET`
  — a forged failure on the network can't spend LLM budget or create branches.
- **Secrets live in a K8s Secret**, not a committed ConfigMap
  (`infra/scripts/apply-env-secret.sh` builds it from `.env` imperatively —
  real values are never written into a manifest file).
- **`.env` is gitignored.** If you ever see real credentials in a diff before
  committing, stop and rotate them rather than committing anyway.
- **The LLM never drives a shell command.** Build logs are attacker/error
  -controlled text fed into prompts; the blast radius stays bounded because
  (a) no model output is ever executed, (b) writes only ever land on a
  disposable `ai-fix/*` sandbox branch, (c) merging is always a human action.
- **Project-scoped GitLab token** (`api`, `read_repository`,
  `write_repository`) — not a personal admin token.

---

## 9. Observability

Both dashboards are reachable **by hostname through the same Traefik ingress
that already serves GitLab on port 80** — no `kubectl port-forward` needed,
ever. `grafana.localhost` / `prometheus.localhost` resolve to loopback
automatically on Linux (RFC 6761 `.localhost` handling), so this works with
zero `/etc/hosts` edits. The ingress objects (`infra/k3s/observability/
grafana-ingress.yaml`, `prometheus-ingress.yaml`) are ordinary cluster
state — they survive a `k3s` restart on their own; nothing to re-run.

- **Grafana** (`http://grafana.localhost`, default `admin`/value of
  `GRAFANA_ADMIN_PASSWORD`): `agent-metrics` dashboard — LLM latency, reviewer
  confidence distribution, fix outcomes, sandbox pass rate, **MR merged rate**
  (not just opened — see `agent_mr_merged_total` / `agent_mr_opened_total`,
  populated from GitLab's own Merge Request Hook via `/webhook/mr`), rules-first
  short-circuit rate, objective-gate rejection breakdown, estimated
  cost-per-remediation, queue depth.
- **Prometheus** (`http://prometheus.localhost`): scrapes `agent:8000/metrics`
  (API-level counters) and `worker-metrics:9100/metrics` (every LangGraph node
  metric — these only ever increment inside the Worker process, so they will
  read zero forever if you only look at the Agent's own `/metrics`).
- **Loki + Promtail**: aggregated pod logs, queryable from Grafana's Explore view.

If you're on a machine where `*.localhost` doesn't auto-resolve (check with
`getent hosts grafana.localhost` — should print `::1` or `127.0.0.1`), add it
once to `/etc/hosts` instead:
```
127.0.0.1 grafana.localhost prometheus.localhost
```

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| `kubectl` says "permission denied" reading `/etc/rancher/k3s/k3s.yaml` | Use `export KUBECONFIG=~/.kube/config` instead of the default path |
| GitLab slow to start | Normal — wait 3–5 min. `kubectl logs -f deployment/gitlab` |
| Runner can't reach GitLab | Check the `gitlab` Service exists and the runner's `--clone-url` is `http://gitlab`, not `localhost` |
| `/webhook` returns 401 | `X-Gitlab-Token` doesn't match `WEBHOOK_SECRET` — check the CI/CD variable on the project and the `env-secret` K8s Secret |
| `/webhook` returns 429 | Attempt cap (2 per commit SHA, `MAX_ATTEMPTS`) reached — this is by design, not a bug; push a new commit to reset it |
| Diagnostician/Patch/Reviewer all fail with a DNS error (`Temporary failure in name resolution`) | CoreDNS resolves internal cluster names but fails on external ones after a k3s restart/extended uptime — `make start` already restarts CoreDNS for you; manually: `kubectl rollout restart deployment/coredns -n kube-system` |
| Diagnostician/Patch/Reviewer all fail with `429`/`402` (not a DNS error) | Check `kubectl logs deployment/worker` for the fallback chain — OpenRouter free-tier rate limits are provider-wide and paid billing can 402 even with credits; the agent posts a "manual review" comment instead of crashing either way |
| Worker's Prometheus metrics all read zero | You're looking at the Agent's `/metrics`, not the Worker's — see §9 |
| Sandbox never validated | Check `validate.yml` actually ran on `ai-fix/*` and POSTed `/callback`; the reaper closes out orphaned ones after `REAP_INTERVAL_SECONDS` but only if GitLab shows the pipeline as finished |
| Worker pod crash-loops after a resource-limit change | Check for a K8s auto-injected `<SERVICE_NAME>_PORT` env var colliding with one of your own env var names (hit this live with a `worker-metrics` Service — see `agent/worker.py`'s comment) |
| A pod's job hangs for a long time then the RQ job vanishes with "Work-horse terminated unexpectedly" | Likely OOM-killed by its container's memory limit, not a hang in the code — check `kubectl describe pod` and raise `resources.limits.memory` in the deployment |
| Everything above looks fine but pods still can't reach each other / the API server | Possible node-level networking flakiness (seen live after ~100 min of uptime with a fleet-wide kube-system pod restart) — try `kubectl rollout restart deployment/coredns -n kube-system` first (fixes DNS specifically, seconds); `sudo systemctl restart k3s` as a last resort (restarts everything, takes minutes) |
| `http://grafana.localhost` / `http://prometheus.localhost` don't load | Check `getent hosts grafana.localhost` resolves to a loopback address — if not, add `127.0.0.1 grafana.localhost prometheus.localhost` to `/etc/hosts`; also check `kubectl get ingress` shows both with an `ADDRESS` |

---

## 11. Docs index

| File | What it is |
|---|---|
| `doc/Implementation plan v5.md` | The pinned architecture spec this README implements |
| `doc/fix.md` | The Tier 1/2/3 fix list this codebase was upgraded against |
| `doc/plan.md`, `doc/implementation_plan_v4.1.md`, `doc/Implementation_Guide_AI_Driven_CICD.md` | Superseded historical versions — kept for context, marked superseded at the top of each |
| `doc/history/step1.md`…`step4.md`, `doc/history/command.md` | Archived day-by-day recaps from before the v5 redesign |
| `to-add.md` | Forward-looking backlog (RAG/vector-DB retrieval, diff-only ±50-line patches, blast-radius control, dry-run mode) — explicitly out of scope for the current implementation, not started |

---

## 12. Known limitations / backlog

- **RAG / vector-DB context, dry-run mode, blast-radius control** (`to-add.md`)
  — not implemented. The Diagnostician currently only sees the error span +
  files it names itself, not a semantic index of the whole codebase.
- **Diff-only ±50-line patches** — not implemented; `generate_patch` inlines
  full file content for files under ~250 lines and falls back to a
  line-range excerpt/splice only above that threshold.
- **Multi-node (Yocto sstate-cache PVC, recipe-scoped real-Yocto validation)**
  — the real Yocto swap-in described in the v5 plan §9 hasn't been done; the
  Yocto build image exists but demo testing so far has focused on Zephyr.
- **Stale runner registrations** accumulated in GitLab from repeated past
  test runs (`Settings > CI/CD > Runners`) — harmless, cleanup optional.
