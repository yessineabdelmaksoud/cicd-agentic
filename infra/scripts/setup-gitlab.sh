#!/bin/bash
# =============================================================================
# setup-gitlab.sh — Crée le projet GitLab "platform" via API REST
# Usage: ./infra/scripts/setup-gitlab.sh
# Doit être lancé APRÈS wait-gitlab.sh
# =============================================================================
set -euo pipefail

GITLAB_URL="${GITLAB_EXTERNAL_URL:-http://localhost}"
ROOT_PASSWORD="${GITLAB_ROOT_PASSWORD:-Admin1234!}"

echo "🔧 Configuration initiale de GitLab..."
echo ""

# 1️⃣  Génération automatique du token API root via Rails runner
echo "1️⃣  Génération du token API root..."
GITLAB_TOKEN=$(kubectl exec -i deployment/gitlab -- gitlab-rails runner "
  user = User.find_by_username('root')
  existing = user.personal_access_tokens.find_by(name: 'AI-CICD-Embedded Token')
  if existing
    existing.destroy!
  end
  token = user.personal_access_tokens.create!(
    scopes: ['api', 'read_repository', 'write_repository'],
    name: 'AI-CICD-Embedded Token',
    expires_at: 365.days.from_now
  )
  puts token.token
" 2>/dev/null | tr -d '\r' || echo "")

if [[ -z "$GITLAB_TOKEN" ]]; then
  echo "   ⚠️  Impossible de générer le token via kubectl exec."
  echo "   → Entrer manuellement le token créé sur $GITLAB_URL/-/profile/personal_access_tokens"
  read -p "   Token : " GITLAB_TOKEN
else
  echo "   ✅ Token API root généré avec succès !"
fi

export GITLAB_TOKEN

# Sauvegarder dans le fichier .env
if grep -q "GITLAB_PROJECT_TOKEN" .env; then
  sed -i "s|GITLAB_PROJECT_TOKEN=.*|GITLAB_PROJECT_TOKEN=$GITLAB_TOKEN|" .env
else
  echo "GITLAB_PROJECT_TOKEN=$GITLAB_TOKEN" >> .env
fi

# Créer le groupe "embedded"
echo "2️⃣  Création du groupe 'embedded'..."
curl -sf --request POST \
  "$GITLAB_URL/api/v4/groups" \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  --data "name=embedded&path=embedded&visibility=private" > /dev/null && \
  echo "   ✅ Groupe 'embedded' créé" || \
  echo "   ℹ️  Groupe 'embedded' existe déjà"

# Récupérer l'ID du groupe "embedded"
GROUP_ID=$(curl -sf \
  "$GITLAB_URL/api/v4/groups?search=embedded" \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" | \
  python3 -c "import sys,json; groups=json.load(sys.stdin); print(groups[0]['id'] if groups else '')" || echo "")

if [[ -z "$GROUP_ID" ]]; then
  echo "❌ Impossible de récupérer l'ID du groupe 'embedded'."
  exit 1
fi

# Autoriser les requêtes vers le réseau local (nécessaire pour webhook vers 'agent')
echo "   Configuration des paramètres de sécurité GitLab..."
curl -sf --request PUT \
  "$GITLAB_URL/api/v4/application/settings?allow_local_requests_from_web_hooks_and_services=true" \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" > /dev/null

# Créer les projets embarqués et configurer les webhooks
for project in "yocto-demo" "zephyr-demo" "qnx-demo"; do
  echo "3️⃣  Configuration du projet '$project'..."
  
  # Création du projet
  curl -sf --request POST \
    "$GITLAB_URL/api/v4/projects" \
    --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
    --data "name=$project&namespace_id=$GROUP_ID&initialize_with_readme=false&visibility=private" > /dev/null && \
    echo "   ✅ Projet '$project' créé dans le groupe 'embedded'" || \
    echo "   ℹ️  Projet '$project' existe déjà"

  # Récupérer l'ID du projet
  PROJECT_ID=$(curl -sf \
    "$GITLAB_URL/api/v4/projects?search=$project" \
    --header "PRIVATE-TOKEN: $GITLAB_TOKEN" | \
    python3 -c "import sys,json; projects=json.load(sys.stdin); print(projects[0]['id'] if projects else '')" || echo "")

  if [[ -n "$PROJECT_ID" ]]; then
    # Supprimer les anciens webhooks si présents pour éviter les doublons
    curl -sf --request DELETE \
      "$GITLAB_URL/api/v4/projects/$PROJECT_ID/hooks" \
      --header "PRIVATE-TOKEN: $GITLAB_TOKEN" > /dev/null || true

    # Ajouter le nouveau webhook
    curl -sf --request POST \
      "$GITLAB_URL/api/v4/projects/$PROJECT_ID/hooks" \
      --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
      --data "url=http://agent:8000/webhook&pipeline_events=true&job_events=true&push_events=false" > /dev/null
    echo "   ✅ Webhook configuré pour '$project' (ID: $PROJECT_ID)"
  else
    echo "   ❌ Impossible de trouver l'ID pour le projet '$project'"
  fi
done

echo ""
echo "✅ GitLab configuré !"
echo "   URL     : $GITLAB_URL"
echo "   Token   : $GITLAB_TOKEN (sauvegardé dans .env)"
echo ""
