#!/bin/bash
# =============================================================================
# install-docker.sh — Installe Docker Engine sur Ubuntu
# Usage: sudo bash infra/scripts/install-docker.sh
# =============================================================================
set -euo pipefail

echo "🐳 Installation de Docker Engine..."

# Supprimer les anciennes versions
apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Dépendances
apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release

# Clé GPG Docker officielle
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Repo Docker
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# Installer Docker CE + Compose plugin
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Ajouter l'utilisateur courant au groupe docker
REAL_USER="${SUDO_USER:-$USER}"
usermod -aG docker "$REAL_USER"

# Activer Docker au démarrage
systemctl enable docker
systemctl start docker

echo ""
echo "✅ Docker installé avec succès !"
echo "   Version : $(docker --version)"
echo "   Compose : $(docker compose version)"
echo ""
echo "⚠️  Déconnectez-vous et reconnectez-vous pour appliquer le groupe docker"
echo "   OU lancez : newgrp docker"
