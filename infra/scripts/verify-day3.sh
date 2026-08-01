#!/usr/bin/env bash
# =============================================================================
# verify-day3.sh — Validate all Jour 3 criteria
# =============================================================================
set -euo pipefail

AGENT_URL="${AGENT_URL:-http://localhost:8000}"
REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
PASS=0
FAIL=0
TOTAL=0

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✅ $1${NC}"; PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); }
fail() { echo -e "${RED}❌ $1${NC}"; FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); }
info() { echo -e "${CYAN}ℹ️  $1${NC}"; }

echo ""
echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}  AI-CICD — Vérification Jour 3${NC}"
echo -e "${YELLOW}============================================${NC}"
echo ""

# ---------------------------------------------------------------------------
# 1. GET /health → {"status":"ok","models":{...}}
# ---------------------------------------------------------------------------
info "Test 1: GET $AGENT_URL/health"
HEALTH=$(curl -sf "$AGENT_URL/health" 2>/dev/null || echo "")
if echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['status']=='ok'; assert 'models' in d" 2>/dev/null; then
    MODELS=$(echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d['models'], indent=2))" 2>/dev/null)
    ok "GET /health → {\"status\":\"ok\",\"models\":{...}}"
    echo "   Models: $MODELS"
else
    fail "GET /health failed or invalid JSON (got: ${HEALTH:0:200})"
fi

# ---------------------------------------------------------------------------
# 2. POST /webhook → 202
# ---------------------------------------------------------------------------
info "Test 2: POST $AGENT_URL/webhook → 202"
WEBHOOK_RESP=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$AGENT_URL/webhook" \
    -H "Content-Type: application/json" \
    -d '{
        "pipeline_id": 999,
        "project_id": 1,
        "commit_sha": "test-sha-day3-'"$(date +%s)"'",
        "branch": "main",
        "build_type": "yocto",
        "failed_job_id": 999
    }' 2>/dev/null || echo "000")

if [ "$WEBHOOK_RESP" = "202" ]; then
    ok "POST /webhook → 202 accepted"
else
    fail "POST /webhook returned HTTP $WEBHOOK_RESP (expected 202)"
fi

# ---------------------------------------------------------------------------
# 3. Redis — Job visible in queue
# ---------------------------------------------------------------------------
info "Test 3: Checking Redis queue for enqueued job"
sleep 1  # Give time for enqueue
REDIS_QUEUED=$( (redis-cli -u "${REDIS_URL}" LLEN rq:queue:agent-jobs 2>/dev/null || echo "-1") | grep -o "[0-9]\+" | head -n1 || echo "-1" )
if [ "$REDIS_QUEUED" -gt "0" ] 2>/dev/null; then
    ok "Redis queue 'agent-jobs' has $REDIS_QUEUED job(s)"
else
    # Try alternative: check if any job keys exist
    JOB_COUNT=$( (redis-cli -u "${REDIS_URL}" KEYS "rq:job:*" 2>/dev/null || true) | wc -l )
    if [ "$JOB_COUNT" -gt "0" ]; then
        ok "Redis has $JOB_COUNT job key(s) (job may have already started processing)"
    else
        fail "No jobs found in Redis queue (LLEN=0, no rq:job keys)"
    fi
fi

# ---------------------------------------------------------------------------
# 4. Attempt Cap — MAX_ATTEMPTS=2 everywhere (fix.md FIX-12)
# ---------------------------------------------------------------------------
info "Test 4: Attempt cap (same SHA, cap=2)"
SHA_CAP="cap-test-sha-$(date +%s)"
# First call — attempt 1/2
curl -sf -X POST "$AGENT_URL/webhook" \
    -H "Content-Type: application/json" \
    -d "{\"pipeline_id\":1001,\"project_id\":1,\"commit_sha\":\"$SHA_CAP\",\"branch\":\"main\",\"build_type\":\"yocto\",\"failed_job_id\":1001}" \
    > /dev/null 2>&1 || true

# Second call — attempt 2/2, still accepted
RESP2=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$AGENT_URL/webhook" \
    -H "Content-Type: application/json" \
    -d "{\"pipeline_id\":1002,\"project_id\":1,\"commit_sha\":\"$SHA_CAP\",\"branch\":\"main\",\"build_type\":\"yocto\",\"failed_job_id\":1002}" \
    2>/dev/null || echo "000")
if [ "$RESP2" = "202" ]; then
    ok "Second attempt for same SHA accepted (attempt 2/2)"
else
    fail "Second attempt returned $RESP2"
fi

# Third call — should be rejected (429), cap exceeded
RESP3=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$AGENT_URL/webhook" \
    -H "Content-Type: application/json" \
    -d "{\"pipeline_id\":1003,\"project_id\":1,\"commit_sha\":\"$SHA_CAP\",\"branch\":\"main\",\"build_type\":\"yocto\",\"failed_job_id\":1003}" \
    2>/dev/null || echo "000")
if [ "$RESP3" = "429" ]; then
    ok "3rd attempt for same SHA rejected with 429 (cap=2 enforced)"
else
    fail "Expected 429 for attempt cap, got $RESP3"
fi

# ---------------------------------------------------------------------------
# 5. GET /metrics — Prometheus endpoint
# ---------------------------------------------------------------------------
info "Test 5: GET $AGENT_URL/metrics → Prometheus format"
METRICS=$(curl -sfL "$AGENT_URL/metrics" 2>/dev/null | head -5 || echo "")
if echo "$METRICS" | grep -q "^#"; then
    ok "GET /metrics → Prometheus text format detected"
else
    fail "GET /metrics failed or no Prometheus output"
fi

# ---------------------------------------------------------------------------
# 6. File structure check
# ---------------------------------------------------------------------------
info "Test 6: Agent file structure completeness"
AGENT_DIR="${AGENT_DIR:-$(dirname "$0")/../../agent}"
REQUIRED_FILES=(
    "main.py" "worker.py" "requirements.txt" "Dockerfile"
    "api/__init__.py" "api/routes.py" "api/schemas.py"
    "core/__init__.py" "core/state.py" "core/graph.py"
    "core/nodes/__init__.py"
    "core/nodes/fetch_logs.py" "core/nodes/parse_error.py"
    "core/nodes/diagnose.py" "core/nodes/fetch_repo_context.py"
    "core/nodes/generate_patch.py" "core/nodes/review_patch.py"
    "core/nodes/evaluate_gate.py" "core/nodes/apply_patch.py"
    "core/nodes/trigger_rebuild.py" "core/nodes/evaluate_result.py"
    "core/nodes/open_mr.py" "core/nodes/post_comment.py"
    "core/rules/__init__.py" "core/rules/base.py"
    "core/rules/yocto_rules.py" "core/rules/zephyr_rules.py" "core/rules/qnx_rules.py"
    "services/__init__.py" "services/openrouter_client.py"
    "services/minio_client.py" "services/gitlab_client.py"
    "services/metrics.py" "services/state_store.py" "services/reaper.py"
)
MISSING=0
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$AGENT_DIR/$f" ]; then
        echo -e "  ${RED}Missing: $f${NC}"
        ((MISSING++))
    fi
done
if [ "$MISSING" -eq 0 ]; then
    ok "All ${#REQUIRED_FILES[@]} required agent files present"
else
    fail "$MISSING files missing from agent/ structure"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}============================================${NC}"
echo -e "  Results: ${GREEN}$PASS ✅${NC}  ${RED}$FAIL ❌${NC}  (total $TOTAL)"
echo -e "${YELLOW}============================================${NC}"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}🎉 Jour 3 validé ! Agent opérationnel.${NC}"
    exit 0
else
    echo -e "${RED}⚠️  $FAIL critères échoués. Vérifier les logs : make agent-logs${NC}"
    exit 1
fi
