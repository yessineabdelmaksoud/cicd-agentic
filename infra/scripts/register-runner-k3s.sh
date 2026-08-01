#!/bin/bash
# =============================================================================
# register-runner-k3s.sh — Enregistre GitLab Runner en executor Kubernetes
# =============================================================================
set -euo pipefail

GITLAB_INTERNAL_URL="http://gitlab"
GITLAB_URL="${GITLAB_EXTERNAL_URL:-http://localhost}"

if [[ -f .env ]]; then
  source .env
fi

GITLAB_PROJECT_TOKEN="${GITLAB_PROJECT_TOKEN:-}"

if [[ -z "$GITLAB_PROJECT_TOKEN" ]]; then
  echo "❌ GITLAB_PROJECT_TOKEN non trouvé dans le fichier .env."
  exit 1
fi

echo "🔄 Création du Runner GitLab via l'API..."
API_RESPONSE=$(curl -sf --request POST "$GITLAB_URL/api/v4/user/runners" \
  --header "PRIVATE-TOKEN: $GITLAB_PROJECT_TOKEN" \
  --data "runner_type=instance_type&description=k3s-runner&tag_list=docker,embedded,yocto,zephyr,qnx&run_untagged=true" || echo "")

if [[ -z "$API_RESPONSE" ]]; then
  echo "❌ Impossible de créer le runner via l'API GitLab."
  exit 1
fi

RUNNER_AUTH_TOKEN=$(echo "$API_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")

if [[ -z "$RUNNER_AUTH_TOKEN" ]]; then
  echo "❌ Token d'authentification du runner manquant dans la réponse API."
  exit 1
fi

echo "   ✅ Token de Runner créé : $RUNNER_AUTH_TOKEN"

echo "🔄 Enregistrement du GitLab Runner dans le pod K3s..."
kubectl exec deployment/gitlab-runner -- gitlab-runner register \
  --non-interactive \
  --url "$GITLAB_INTERNAL_URL" \
  --token "$RUNNER_AUTH_TOKEN" \
  --executor "kubernetes" \
  --kubernetes-namespace "default" \
  --kubernetes-pull-policy "if-not-present" \
  --clone-url "http://gitlab" \
  --description "k3s-kubernetes-runner"

echo "✅ Runner enregistré avec succès sur K3s !"
