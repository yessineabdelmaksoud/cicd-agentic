#!/bin/bash
# =============================================================================
# import-repos.sh — Initialise et pousse les projets de démo vers GitLab
# Usage: ./infra/scripts/import-repos.sh
# =============================================================================
set -euo pipefail

# Charger .env
if [[ -f .env ]]; then
  source .env
fi

GITLAB_PROJECT_TOKEN="${GITLAB_PROJECT_TOKEN:-}"
GITLAB_URL="${GITLAB_EXTERNAL_URL:-http://localhost}"

if [[ -z "$GITLAB_PROJECT_TOKEN" ]]; then
  echo "❌ GITLAB_PROJECT_TOKEN non trouvé dans .env. Exécuter 'make setup-gitlab' d'abord."
  exit 1
fi

echo "🚀 Initialisation et import des dépôts de démo..."
echo ""

# Configuration git globale temporaire pour éviter les erreurs d'identification
export GIT_COMMITTER_NAME="AI Agent"
export GIT_COMMITTER_EMAIL="agent@ai-cicd.local"
export GIT_AUTHOR_NAME="AI Agent"
export GIT_AUTHOR_EMAIL="agent@ai-cicd.local"

setup_project() {
  local name="$1"
  local type="$2"
  local temp_dir="/tmp/$name"

  echo "📦 Configuration de $name ($type)..."
  rm -rf "$temp_dir"
  local target_url="http://oauth2:${GITLAB_PROJECT_TOKEN}@localhost/embedded/${name}.git"
  git clone "$target_url" "$temp_dir" || true
  
  cd "$temp_dir"
  
  # Si le dépôt est vide, on crée la branche main
  git checkout main 2>/dev/null || git checkout -b main

  # Fichier README.md
  cat <<EOF > README.md
# $name — Embedded Build Simulation ($type)
Ce dépôt simule un environnement de build embarqué pour tester la plateforme AI-CICD.

## Build local
\`\`\`bash
bash build.sh
\`\`\`
EOF

  # Script de build (build.sh) avec simulation d'erreur
  cat <<EOF > build.sh
#!/bin/bash
# =============================================================================
# Build simulation script
# =============================================================================
set -eu

echo "🛠️ Début de la compilation du projet $name..."
sleep 2

# Erreur de type : fetch/src_uri (Yocto)
if [ -f error_src_uri.txt ]; then
  echo "ERROR: libfoo-1.0-r0 do_fetch: Failed to fetch URL http://invalid-url.com/libfoo-1.0.tar.gz" >&2
  exit 1
fi

# Erreur de type : compilation (Zephyr, QNX, Yocto)
if [ -f error_compile.txt ]; then
  echo "Compiling main.c..."
  echo "main.c:12:5: error: unknown type name 'invalid_type'" >&2
  echo "main.c:13:9: error: expected ';' before 'return'" >&2
  exit 1
fi

echo "✅ Compilation réussie !"
EOF
  chmod +x build.sh

  # Fichier source principal main.c (correct par défaut)
  cat <<EOF > main.c
#include <stdio.h>

int main(void) {
    printf("Hello Embedded World from $name!\n");
    return 0;
}
EOF

  # Configuration du pipeline .gitlab-ci.yml
  cat <<EOF > .gitlab-ci.yml
stages:
  - build
  - validate

build-job:
  stage: build
  image: embedded-build:$type
  tags:
    - docker
  rules:
    - if: '\$CI_COMMIT_BRANCH !~ /^ai-fix\//'  
  timeout: 10 minutes
  script:
    - bash build.sh 2>&1 | tee build.log
  after_script:
    - |
      if [ "\$CI_JOB_STATUS" = "failed" ]; then
        echo "❌ Build échoué. Upload du log vers MinIO via API S3..."
        LOG_KEY="pipeline-\${CI_PIPELINE_ID}-job-\${CI_JOB_ID}.log"
        curl -s -X PUT \\
          --user "admin:password123" \\
          --aws-sigv4 "aws:amz:us-east-1:s3" \\
          -H "Content-Type: application/octet-stream" \\
          --data-binary "@build.log" \\
          "http://minio:9000/build-logs/\${LOG_KEY}" && \\
          echo "✅ Log uploadé : \${LOG_KEY}" || echo "⚠️  Échec upload MinIO"

        echo "📡 Notification de l'agent IA..."
        curl -s -X POST "http://agent:8000/webhook" \\
          -H "Content-Type: application/json" \\
          -d "{\\"pipeline_id\\": \$CI_PIPELINE_ID, \\"project_id\\": \$CI_PROJECT_ID, \\"commit_sha\\": \\"\$CI_COMMIT_SHA\\", \\"branch\\": \\"\$CI_COMMIT_REF_NAME\\", \\"build_type\\": \\"$type\\", \\"failed_job_id\\": \$CI_JOB_ID}"
        echo "✅ Agent notifié !"
      fi
  artifacts:
    when: always
    paths:
      - build.log
    expire_in: 1 day
validate-job:
  stage: validate
  image: embedded-build:$type
  tags:
    - docker
  rules:
    - if: '\$CI_COMMIT_BRANCH =~ /^ai-fix\//'
  script:
    - bash build.sh
    - echo "✅ Validation de la correction par l'IA réussie !"
EOF

  # Commiter les changements
  git add .
  if ! git diff --cached --quiet; then
      git commit -m "Update simulation environment"
      git push -u origin main
      echo "   ✅ Projet mis à jour et poussé avec succès !"
  else
      echo "   ℹ️  Aucun changement détecté, rien à pousser."
  fi
  echo ""
}

setup_project "yocto-demo" "yocto"
setup_project "zephyr-demo" "zephyr"
setup_project "qnx-demo" "qnx"

echo "✅ Tous les projets ont été initialisés et importés dans GitLab !"
