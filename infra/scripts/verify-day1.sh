#!/bin/bash
# =============================================================================
# verify-day1.sh — Vérifie que tous les services Jour 1 sont opérationnels
# Usage: ./infra/scripts/verify-day1.sh
# =============================================================================
set -euo pipefail

PASS=0
FAIL=0

check() {
  local name="$1"
  local cmd="$2"
  if eval "$cmd" > /dev/null 2>&1; then
    echo "✅ $name"
    PASS=$((PASS + 1))
  else
    echo "❌ $name"
    FAIL=$((FAIL + 1))
  fi
}

echo "============================================"
echo " Vérification Jour 1 — AI-CICD-EMBEDDED"
echo "============================================"
echo ""

# Services K3s
echo "📦 Kubernetes (K3s) services"
check "GitLab CE (health)" "curl -sf http://localhost/users/sign_in"
check "MinIO API (health)" "kubectl get pods -l io.kompose.service=minio | grep -q Running"
check "MinIO Console" "kubectl get pods -l io.kompose.service=minio | grep -q Running"
check "Redis (ping)" "kubectl exec deployment/redis -- redis-cli ping | grep -q PONG"
check "Prometheus" "kubectl get pods -l io.kompose.service=prometheus | grep -q Running"
check "Grafana" "kubectl get pods -l io.kompose.service=grafana | grep -q Running"
check "Loki" "kubectl get pods -l io.kompose.service=loki | grep -q Running"

echo ""

# Buckets MinIO
echo "🪣 MinIO Buckets"
check "Bucket build-logs" "kubectl get pods | grep minio-init | grep -q Completed"

echo ""

# GitLab Runner
echo "🏃 GitLab Runner"
check "Runner pod running" "kubectl get pods -l io.kompose.service=gitlab-runner | grep -q Running"

echo ""

# RAM
echo "💾 Ressources"
FREE_MEM=$(free -m | awk '/^Mem:/ {print $7}')
echo "   RAM libre système       : ${FREE_MEM} MiB"

echo ""
echo "============================================"
echo " Résultat : $PASS ✅  $FAIL ❌"
echo "============================================"

if [[ $FAIL -gt 0 ]]; then
  echo ""
  echo "   Pour débugger : kubectl get pods -A"
  echo "   Ou : kubectl logs deployment/<service>"
  exit 1
fi
