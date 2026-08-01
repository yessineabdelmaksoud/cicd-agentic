#!/bin/bash
# =============================================================================
# apply-env-secret.sh — Creates/updates the `env-secret` K8s Secret from .env
#
# fix.md security §14: secrets must be K8s Secrets, not committed in a plain
# ConfigMap. This script reads .env (never committed) and applies the
# sensitive subset as a Secret imperatively — no real values ever get written
# into a manifest file that could end up in version control.
#
# Usage: ./infra/scripts/apply-env-secret.sh [path-to-.env]
# =============================================================================
set -euo pipefail

ENV_FILE="${1:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ $ENV_FILE not found. Copy .env.example to .env and fill in your values first."
  exit 1
fi

SECRET_KEYS=(
  GITLAB_ROOT_PASSWORD
  GITLAB_RUNNER_TOKEN
  GITLAB_PROJECT_TOKEN
  OPENROUTER_API_KEY
  MINIO_ROOT_PASSWORD
  GRAFANA_ADMIN_PASSWORD
  WEBHOOK_SECRET
)

ARGS=()
for key in "${SECRET_KEYS[@]}"; do
  value=$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-)
  if [[ -n "$value" ]]; then
    ARGS+=(--from-literal="${key}=${value}")
  else
    echo "⚠️  $key is empty in $ENV_FILE — skipping (agent will fail to start if it's required)"
  fi
done

if [[ ${#ARGS[@]} -eq 0 ]]; then
  echo "❌ No secret values found in $ENV_FILE — nothing to apply"
  exit 1
fi

kubectl create secret generic env-secret "${ARGS[@]}" --dry-run=client -o yaml | kubectl apply -f -
echo "✅ env-secret applied ($(( ${#ARGS[@]} )) keys)"
