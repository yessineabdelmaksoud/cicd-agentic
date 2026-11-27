ENV_FILE = .env

.PHONY: help up down stop status logs build-images \
        register-runner setup-gitlab apply-secret verify-day1 verify-day3 \
        build-agent run-agent-local test test-unit test-integration demo clean

# Affiche l'aide automatiquement
help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Infrastructure (Kubernetes / K3s)
# ---------------------------------------------------------------------------
start: ## ▶️  DÉMARRAGE APRÈS REDÉMARRAGE PC — lance K3s + vérifie les services
	@echo "🚀 Démarrage de K3s..."
	sudo systemctl start k3s
	@echo "🔑 Correction des permissions kubectl..."
	sudo chmod 644 /etc/rancher/k3s/k3s.yaml
	@echo "⏳ Attente que les pods soient prêts (2-4 min pour GitLab)..."
	@sleep 30
	@kubectl wait --for=condition=ready pod -l io.kompose.service=redis --timeout=120s 2>/dev/null || true
	@kubectl wait --for=condition=ready pod -l io.kompose.service=minio --timeout=120s 2>/dev/null || true
	@kubectl wait --for=condition=ready pod -l io.kompose.service=agent --timeout=120s 2>/dev/null || true
	@echo "🔄 Redémarrage de CoreDNS (un arrêt prolongé casse parfois la résolution DNS externe — vu en pratique avec les appels OpenRouter en échec après un restart)..."
	@kubectl rollout restart deployment/coredns -n kube-system 2>/dev/null || true
	@kubectl rollout status deployment/coredns -n kube-system --timeout=60s 2>/dev/null || true
	@echo "🪣 Vérification du bucket MinIO build-logs..."
	@kubectl exec deployment/minio -- mc alias set local http://localhost:9000 admin password123 2>/dev/null && \
	 kubectl exec deployment/minio -- mc mb local/build-logs --ignore-existing 2>/dev/null && \
	 kubectl exec deployment/minio -- mc anonymous set public local/build-logs 2>/dev/null && \
	 echo "   ✅ Bucket build-logs OK" || echo "   ⚠️  MinIO pas encore prêt, réessayez dans 1 min"
	@echo ""
	@echo "✅ Stack démarrée ! Vérification..."
	@bash infra/scripts/verify-day1.sh || true
	@echo ""
	@echo "🌐 GitLab:     http://localhost"
	@echo "🌐 Grafana:    http://grafana.localhost"
	@echo "🌐 Prometheus: http://prometheus.localhost"

stop: ## ⏸  Arrêt propre en fin de journée — conserve toutes les données (GitLab/MinIO/Redis/Grafana)
	@echo "⏸  Arrêt de K3s..."
	sudo systemctl stop k3s
	@echo "✅ K3s arrêté. Toutes les données sont conservées sur disque (PVC local-path)."
	@echo "   Pour relancer demain : make start"

up: check-env ## Lance toute la stack sur K3s (premier déploiement)
	@bash scripts/k3s-deploy.sh

down: ## Arrête et supprime les pods K3s (⚠️ retire aussi les manifests appliqués — pas pour un arrêt du soir, voir 'make stop')
	kubectl delete -R -f infra/k3s/

status: ## Affiche l'état de tous les pods K3s
	kubectl get pods

logs: ## Affiche les logs K3s en temps réel : make logs s=gitlab
	kubectl logs -f deployment/$(or $(s),agent)

verify-day1: ## Vérifie que tous les services Jour 1 sont opérationnels
	@bash infra/scripts/verify-day1.sh

verify-day3: ## Vérifie que l'agent Jour 3 est opérationnel
	@bash infra/scripts/verify-day3.sh

# ---------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------
register-runner: ## Enregistre le GitLab Runner K3s/Kubernetes
	@bash infra/scripts/register-runner-k3s.sh

setup-gitlab: ## Configure GitLab : projets, webhook (interactif)
	@bash infra/scripts/setup-gitlab.sh

apply-secret: ## (Re)crée le Secret K8s env-secret à partir de .env
	@bash infra/scripts/apply-env-secret.sh .env

# ---------------------------------------------------------------------------
# Agent IA
# ---------------------------------------------------------------------------
build-agent: ## Build l'image Docker de l'agent et l'importe dans K3s
	docker build -t infra-agent:latest agent/
	docker save infra-agent:latest | sudo k3s ctr images import -
	kubectl rollout restart deployment agent worker

agent-logs: ## Logs de l'agent et du worker en temps réel
	@echo "📋 Agent logs:" && kubectl logs -f deployment/agent & \
	echo "⚙️  Worker logs:" && kubectl logs -f deployment/worker

run-agent-local: ## Lance l'agent localement (sans Docker) pour dev rapide
	@cd agent && pip install -q -r requirements.txt && \
	  OPENROUTER_API_KEY=$$(grep OPENROUTER_API_KEY ../.env | cut -d= -f2) \
	  GITLAB_PROJECT_TOKEN=$$(grep GITLAB_PROJECT_TOKEN ../.env | cut -d= -f2) \
	  GITLAB_EXTERNAL_URL=http://localhost \
	  MINIO_ENDPOINT=http://localhost:9000 \
	  REDIS_URL=redis://localhost:6379/0 \
	  uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# ---------------------------------------------------------------------------
# Images Docker de build embarqué
# ---------------------------------------------------------------------------
build-images: ## Build les images Docker pour les projets embarqués ET les importe dans K3s
	docker build -t embedded-build:yocto docker/yocto/
	docker build -t embedded-build:zephyr docker/zephyr/
	docker build -t embedded-build:qnx   docker/qnx/
	@echo "✅ Images buildées : embedded-build:yocto, :zephyr, :qnx"
	@echo "📦 Import dans K3s containerd..."
	@bash infra/scripts/import-images-k3s.sh

import-images: ## Importe les images Docker locales dans K3s (à faire après chaque build-images ou redémarrage K3s)
	@bash infra/scripts/import-images-k3s.sh

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
test: ## Lance tous les tests (unit + integration)
	cd agent && python -m pytest ../tests/ -v --tb=short

test-unit: ## Tests unitaires uniquement
	cd agent && python -m pytest ../tests/unit/ -v

test-integration: ## Tests d'intégration (LLM mockés)
	cd agent && python -m pytest ../tests/integration/ -v

# ---------------------------------------------------------------------------
# Démonstration
# ---------------------------------------------------------------------------
demo: ## Démonstration complète (inject error → agent → MR ouverte)
	@bash scripts/demo.sh

inject-error: ## Injecte une erreur dans un projet démo : make inject-error p=zephyr-demo type=compile
	@bash scripts/inject-error.sh "$(or $(p),yocto-demo)" "$(or $(type),src_uri)"

# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
check-env: ## Vérifie que .env existe
	@if [ ! -f $(ENV_FILE) ]; then \
	  echo "❌ Fichier .env manquant. Copier .env.example :"; \
	  echo "   cp .env.example .env && éditez les valeurs"; \
	  exit 1; \
	fi

clean: ## Supprime TOUS les pods et volumes K3s (⚠️ perte de données GitLab)
	@echo "⚠️  Cette commande supprime TOUS les pods et volumes (données GitLab, MinIO, Redis...)"
	@read -p "Confirmer ? [y/N] " ans && [ "$$ans" = "y" ]
	kubectl delete -R -f infra/k3s/ --ignore-not-found=true
	@echo "✅ Stack K3s supprimée"
