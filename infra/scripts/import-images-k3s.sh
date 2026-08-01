#!/bin/bash
# =============================================================================
# import-images-k3s.sh — Importe les images Docker locales dans K3s containerd
#
# Pourquoi ce script ?
# Docker et K3s utilisent deux systèmes de stockage d'images SÉPARÉS :
#   - Docker : /var/lib/docker
#   - K3s    : /var/lib/rancher/k3s/agent/containerd
#
# La policy "if-not-present" du runner cherche dans K3s, PAS dans Docker.
# Ce script fait le pont entre les deux.
#
# Usage: ./infra/scripts/import-images-k3s.sh
# Ou via Makefile: make import-images
# =============================================================================
set -euo pipefail

echo "🔄 Import des images locales Docker → K3s containerd..."
echo ""

IMAGES=(
  "embedded-build:zephyr"
  "embedded-build:yocto"
  "embedded-build:qnx"
  "registry.gitlab.com/gitlab-org/gitlab-runner/gitlab-runner-helper:x86_64-v17.1.0"
)

for IMAGE in "${IMAGES[@]}"; do
  echo "   📦 Vérification de $IMAGE dans Docker..."
  if docker image inspect "$IMAGE" > /dev/null 2>&1; then
    echo "   ✅ Image trouvée dans Docker, import vers K3s..."
    docker save "$IMAGE" | sudo k3s ctr images import -
    echo "   ✅ $IMAGE importé dans K3s !"
  else
    echo "   ⚠️  Image $IMAGE absente de Docker, skip."
    echo "      Pour la construire : make build-images"
  fi
  echo ""
done

echo "🔍 Vérification finale dans K3s :"
sudo k3s ctr images ls | grep -E "embedded-build|gitlab-runner-helper" || echo "  Aucune image trouvée."
echo ""
echo "✅ Import terminé ! Vous pouvez maintenant lancer './scripts/demo.sh'."
