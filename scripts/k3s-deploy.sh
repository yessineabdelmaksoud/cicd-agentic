#!/bin/bash
# =============================================================================
# k3s-deploy.sh — Déploie l'infrastructure sur K3s
# =============================================================================
set -euo pipefail

echo "🔄 Vérification de l'installation de K3s..."
if ! command -v k3s &> /dev/null; then
    echo "⚙️  Installation de K3s..."
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode 644" sh -
    mkdir -p ~/.kube
    sudo k3s kubectl config view --raw > ~/.kube/config
    chmod 600 ~/.kube/config
fi

# Correction des permissions du kubeconfig par défaut pour le profil utilisateur actuel
sudo chmod 644 /etc/rancher/k3s/k3s.yaml || true
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

echo "🚀 Déploiement de l'infrastructure sur K3s..."

# S'assurer que les dossiers persistent volumes existent sur l'hôte si besoin
sudo mkdir -p /var/opt/gitlab /var/log/gitlab /etc/gitlab
# Corriger dynamiquement les chemins absolus pour la machine actuelle
python3 scripts/patch_k3s_paths.py

# Créer/mettre à jour le Secret K8s à partir de .env — jamais de secrets en
# clair dans un manifeste versionné (fix.md sécurité §14)
bash infra/scripts/apply-env-secret.sh .env

# Appliquer les manifests k3s générés
kubectl apply -R -f infra/k3s/

echo "✅ Déploiement K3s lancé !"
echo "⏳ Attendez que tous les pods soient en statut 'Running' : watch kubectl get pods"
