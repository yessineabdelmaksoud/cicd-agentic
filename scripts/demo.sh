#!/bin/bash
# =============================================================================
# demo.sh — Simule un cas REEL de correction par l'IA
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

PROJECT_NAME="zephyr-demo"
TEMP_DIR="/tmp/demo-real-$PROJECT_NAME"
rm -rf "$TEMP_DIR"

echo "=========================================================="
echo "🤖 DÉMONSTRATION RÉELLE : AI-CICD Agent"
echo "=========================================================="
echo ""
echo "1️⃣  Clonage du projet $PROJECT_NAME..."
git clone -q "http://oauth2:${GITLAB_PROJECT_TOKEN}@localhost/embedded/${PROJECT_NAME}.git" "$TEMP_DIR"
cd "$TEMP_DIR"

# Configurer git local pour le commit
git config user.name "Développeur Distrait"
git config user.email "dev@ai-cicd.local"

echo "2️⃣  Injection d'une VRAIE erreur de syntaxe en C..."
# S'assurer d'abord qu'on a bien printf (si prntf était déjà là)
sed -i 's/prntf/printf/g' main.c
# Remplacer printf par prntf (faute de frappe classique)
sed -i 's/printf/prntf/g' main.c
# Ajouter un commentaire unique pour forcer le commit même si le fichier était déjà prntf
echo "// Demo trigger: $(date +%s)" >> main.c

echo "--- Fichier main.c modifié ---"
cat main.c
echo "------------------------------"

echo ""
echo "3️⃣  Commit et push sur la branche principale..."
git commit -q -am "feat: add new feature (with typo)"
git push -q origin main

echo ""
echo "✅ L'erreur a été poussée avec succès !"
echo ""
echo "=========================================================="
echo "👀  QUE VA-T-IL SE PASSER MAINTENANT ? "
echo "=========================================================="
echo "1. GitLab CI va lancer la compilation (et échouer à cause de 'prntf')."
echo "2. Le webhook CI va notifier l'Agent IA (visible dans 'make agent-logs')."
echo "3. L'Agent va télécharger le log de compilation depuis MinIO."
echo "4. Le Diagnostician (Qwen) va détecter une erreur de syntaxe."
echo "5. Le Patch Generator (Deepseek) va corriger 'prntf' -> 'printf'."
echo "6. Le Reviewer (Claude) va valider le patch."
echo "7. L'Agent va créer une Merge Request avec le correctif ! 🚀"
echo "=========================================================="
echo ""
echo "🔗 Suivez le pipeline en direct ici :"
echo "   $GITLAB_URL/embedded/$PROJECT_NAME/-/pipelines"
echo ""
echo "💡 Pour voir les logs de l'Agent IA en temps réel :"
echo "   make agent-logs"
echo ""
