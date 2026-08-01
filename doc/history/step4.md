# Step 4: Observabilité & Tests E2E (Jour 4)

Ce document résume l'implémentation et la validation du Jour 4 : configuration de la stack d'observabilité complète (Prometheus, Grafana, Loki, Promtail) et création des dashboards personnalisés pour le pipeline AI-CICD.

## Objectif accompli

La stack d'observabilité est intégralement déployée sur K3s. Les métriques personnalisées (latence LLM, tentatives de correction, confiance) sont remontées par l'Agent et visualisables sur des dashboards Grafana créés sur mesure. Les logs de l'Agent et des Builders sont centralisés via Loki.

---

## Architecture d'Observabilité

```
  Containers (K3s)                        Observabilité (K3s)
┌──────────────────┐
│                  │
│  AI Agent (FastAPI) ── /metrics ────→   Prometheus (9090) ───┐
│                  │                                           │
└─────────┬────────┘                                           │
          │                                                    ↓
          │ logs (stdout/stderr)                       Grafana (3000)
          ↓                                                    ↑
  Promtail (DaemonSet) ───────────────→      Loki (3100) ──────┘
```

---

## Fichiers créés et modifiés

### Agent Metrics (agent/services/metrics.py)
Instrumentation avec `prometheus_client` :
| Métrique | Type | Rôle |
|----------|------|------|
| `agent_llm_duration_seconds` | Histogram | Latence API OpenRouter (par modèle et agent) |
| `agent_node_duration_seconds` | Histogram | Temps d'exécution de chaque nœud LangGraph |
| `agent_fix_attempts_total` | Counter | Suivi des résolutions (pass, fail, manual_review...) |
| `agent_reviewer_confidence` | Histogram | Distribution du score de confiance du Reviewer |
| `agent_webhooks_total` | Counter | Compteur de triggers CI par `build_type` |

### Grafana Dashboards (observability/grafana/dashboards/)
| Fichier | Panels Inclus |
|---------|---------------|
| `build-health.json` | - Build success/failure rate<br>- Agent triggers per hour<br>- Active Jobs<br>- Build Duration Heatmap |
| `agent-metrics.json` | - LLM Latency by Agent Role (95th percentile)<br>- Reviewer Confidence Distribution<br>- Fix Outcomes / Rejection Rate<br>- Fix Success Rate (Sandbox Pass %)<br>- MR Acceptance Rate |

### Infrastructure (infra/k3s/observability/)
La structure des fichiers YAML a été refactorisée par composants pour plus de clarté :
- `prometheus-deployment.yaml` (monté sur `observability/prometheus/prometheus.yml`)
- `loki-deployment.yaml` (monté sur `observability/loki/loki-config.yaml`)
- `grafana-deployment.yaml` (auto-provisioning des datasources et dashboards)
- `promtail-deployment.yaml`

---

## Commandes de validation

```bash
# Vérifier que les pods d'observabilité sont Running
kubectl get pods -n default -l io.kompose.network/infra-cicd-net=true

# Injecter une erreur pour générer des données (métriques + logs)
make demo

# Accéder aux interfaces
# 📊 Grafana : http://localhost:3000 (admin / admin)
# ⚙️ Prometheus : http://localhost:9090
```

---

## Notes d'implémentation

1. **Auto-Provisioning Grafana** : Les dashboards JSON que nous avons créés (`build-health.json` et `agent-metrics.json`) sont chargés de façon statique au démarrage du pod Grafana grâce au fichier de provisioning `dashboard.yaml`. Pas besoin de les importer manuellement !
2. **Restructuration K3s** : Pour permettre une meilleure scalabilité et lisibilité, les 40 fichiers plats K3s ont été déplacés dans des sous-dossiers par composant (`agent/`, `gitlab/`, `storage/`, `observability/`, `core/`). Les scripts de déploiement (`k3s-deploy.sh`, `Makefile`) ont été patchés avec le flag récursif `-R`.
3. **Loki Logging** : Tous les logs de l'infrastructure sont accessibles directement dans Grafana via l'onglet "Explore" en sélectionnant la source de données **Loki** et en entrant une requête comme `{app="agent"}`.
