#!/bin/bash
# =============================================================================
# inject-error.sh — Injecte une erreur dans un projet GitLab pour tester la CI
# Usage: ./scripts/inject-error.sh <project-name> <error-type>
# Ex: ./scripts/inject-error.sh yocto-demo src_uri
#     ./scripts/inject-error.sh zephyr-demo compile
# =============================================================================
set -euo pipefail

# Charger .env
if [[ -f .env ]]; then
  source .env
fi

GITLAB_PROJECT_TOKEN="${GITLAB_PROJECT_TOKEN:-}"
GITLAB_URL="${GITLAB_EXTERNAL_URL:-http://localhost}"

if [[ -z "$GITLAB_PROJECT_TOKEN" ]]; then
  echo "❌ GITLAB_PROJECT_TOKEN non trouvé dans .env. Lancer 'make setup-gitlab' d'abord."
  exit 1
fi

PROJECT_NAME="${1:-}"
ERROR_TYPE="${2:-}"  # "src_uri" ou "compile"

if [[ -z "$PROJECT_NAME" || -z "$ERROR_TYPE" ]]; then
  echo "❌ Usage: $0 <project-name> <error-type>"
  echo "   Projets valides : yocto-demo, zephyr-demo, qnx-demo"
  echo "   Erreurs valides : src_uri, compile"
  exit 1
fi

if [[ "$ERROR_TYPE" != "src_uri" && "$ERROR_TYPE" != "compile" ]]; then
  echo "❌ Type d'erreur inconnu : $ERROR_TYPE. Utiliser 'src_uri' ou 'compile'."
  exit 1
fi

TEMP_DIR="/tmp/inject-error-$PROJECT_NAME"
rm -rf "$TEMP_DIR"

echo "🔄 Clonage de $PROJECT_NAME..."
git clone "http://oauth2:${GITLAB_PROJECT_TOKEN}@localhost/embedded/${PROJECT_NAME}.git" "$TEMP_DIR"
cd "$TEMP_DIR"

# Configurer git local pour le commit
git config user.name "Error Injector"
git config user.email "injector@ai-cicd.local"

# Supprimer les anciens déclencheurs d'erreur
rm -f error_src_uri.txt error_compile.txt

# Créer le nouveau fichier d'erreur
if [[ "$ERROR_TYPE" == "src_uri" ]]; then
  echo "Simulated fetch error" > error_src_uri.txt
  git add error_src_uri.txt
elif [[ "$ERROR_TYPE" == "compile" ]]; then
  echo "Simulated compile error" > error_compile.txt
  git add error_compile.txt
fi

echo "📝 Commit et push de l'erreur..."
git commit --allow-empty -am "Inject $ERROR_TYPE error for AI agent validation"
git push origin main

echo ""
echo "✅ Erreur '$ERROR_TYPE' injectée avec succès dans $PROJECT_NAME !"
echo "   Vérifier le pipeline : $GITLAB_URL/embedded/$PROJECT_NAME/-/pipelines"
