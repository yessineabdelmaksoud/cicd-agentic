#!/bin/bash
# =============================================================================
# wait-gitlab.sh — Attend que GitLab CE soit complètement démarré
# Usage: ./infra/scripts/wait-gitlab.sh
# =============================================================================
set -euo pipefail

GITLAB_URL="${GITLAB_EXTERNAL_URL:-http://localhost}"
MAX_WAIT=300  # 5 minutes max
INTERVAL=10
elapsed=0

echo "⏳ Attente du démarrage de GitLab CE..."
echo "   URL: $GITLAB_URL"
echo "   Timeout: ${MAX_WAIT}s"
echo ""

until curl -sf "$GITLAB_URL/users/sign_in" > /dev/null 2>&1; do
  if [[ $elapsed -ge $MAX_WAIT ]]; then
    echo "❌ Timeout après ${MAX_WAIT}s — GitLab ne répond pas."
    echo "   Vérifier les logs : docker compose logs gitlab --tail=50"
    exit 1
  fi
  echo "   ... $(date +%H:%M:%S) — pas encore prêt (${elapsed}s écoulées)"
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
done

echo ""
echo "✅ GitLab CE est opérationnel !"
echo "   Accès : $GITLAB_URL"
echo "   Login : root / (mot de passe dans docker exec gitlab cat /etc/gitlab/initial_root_password)"
