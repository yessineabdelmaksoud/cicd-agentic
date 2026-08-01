# Step 3: Agent IA LangGraph + OpenRouter (Jour 3)

Ce document résume l'implémentation et la validation du Jour 3 : construction du pipeline agent IA complet à 9 nœuds avec LangGraph et OpenRouter.

## Objectif accompli

Le pipeline LangGraph `agent/` est opérationnel avec les 9 nœuds et les 3 agents LLM via OpenRouter.

---

## Architecture du pipeline

```
webhook → Redis queue → Worker RQ
                            ↓
    ┌────────────────────────────────────────────┐
    │              LangGraph StateGraph           │
    │                                             │
    │  1. fetch_logs   → MinIO download           │
    │  2. parse_error  → Regex build_type         │
    │  3. diagnose     → qwen/qwen3-coder:free    │
    │  4. gen_patch    → deepseek-v3              │
    │  5. review_patch → claude-sonnet-4-5        │
    │         ↓ conf<0.75                         │
    │  9b. post_comment (low confidence)          │
    │         ↓ conf≥0.75                         │
    │  6. apply_patch  → GitLab Files API         │
    │  7. trigger_rebuild → GitLab Pipeline       │
    │  8. evaluate_result → polling               │
    │       ↓ pass         ↓ fail                 │
    │  9a. open_mr    9b. post_comment            │
    └────────────────────────────────────────────┘
```

## Fichiers créés

### Application (agent/)
| Fichier | Rôle |
|---------|------|
| `main.py` | FastAPI app avec lifespan, CORS, Prometheus mount |
| `worker.py` | RQ Redis queue consumer |
| `requirements.txt` | Dépendances Python (langgraph==0.2.38) |
| `Dockerfile` | Image Python 3.11-slim |

### API (agent/api/)
| Fichier | Rôle |
|---------|------|
| `schemas.py` | Pydantic: WebhookPayload, CallbackPayload, HealthResponse |
| `routes.py` | POST /webhook (202 + attempt cap), GET /health, POST /callback |

### Core (agent/core/)
| Fichier | Rôle |
|---------|------|
| `state.py` | AgentState TypedDict (19 champs) |
| `graph.py` | LangGraph StateGraph + routing conditionnel |

### Nœuds (agent/core/nodes/)
| Nœud | Rôle |
|------|------|
| `fetch_logs.py` | Télécharge le log depuis MinIO |
| `parse_error.py` | Regex par build_type (yocto/zephyr/qnx/aosp) |
| `diagnose.py` | qwen3-coder → {root_cause, fix_type, confidence} |
| `generate_patch.py` | deepseek-v3 → {files_to_modify, confidence, explanation} |
| `review_patch.py` | claude-sonnet → {approved, confidence, concerns} |
| `apply_patch.py` | Crée branche `ai-fix/<id>` + GitLab Files API |
| `trigger_rebuild.py` | Lance pipeline GitLab sur la branche sandbox |
| `evaluate_result.py` | Polling pipeline GitLab (timeout 10min) |
| `open_mr.py` | MR Draft (0.75-0.90) ou Normal (>0.90) |
| `post_comment.py` | Commentaire sur commit avec diagnostic complet |

### Services (agent/services/)
| Fichier | Rôle |
|---------|------|
| `openrouter_client.py` | Client unifié avec retry, JSON fence strip |
| `minio_client.py` | Download logs, upload résultats |
| `gitlab_client.py` | REST API v4 : branches, fichiers, pipelines, MRs |
| `metrics.py` | Prometheus : LLM latency, node duration, fix outcomes |

---

## Seuils de confiance (implémentés)

| Confidence | Action |
|------------|--------|
| `< 0.75` | `post_comment` — pas de sandbox |
| `0.75 – 0.90` | Sandbox build → **Draft MR** si pass |
| `> 0.90` | Sandbox build → **Normal MR** si pass |

---

## Tests

### Résultats unit tests
```
14 passed in 0.05s ✅
```

- `TestYoctoParser` : 5 tests (fetch, compile, SRC_URI, task, context window)
- `TestZephyrParser` : 3 tests (ninja, undefined ref, cmake)
- `TestQNXParser` : 2 tests (compile, make)
- `TestEdgeCases` : 4 tests (no error, empty log, unknown type, line numbers)

---

## Commandes de validation

```bash
# Lancer l'agent en local (nécessite Redis + MinIO up)
make run-agent-local

# Ou via Docker Compose
make deploy-agent

# Vérifier les critères J3
make verify-day3

# Tests unitaires
make test-unit

# Voir les logs
make agent-logs
```

---

## Notes d'implémentation

1. **Version LangGraph** : `0.2.38` + `langchain-core==0.3.15` (v0.1.x incompatible avec pydantic v2)
2. **Attempt cap** : Redis key `remediation:<sha>` avec TTL 24h, rejeté à MAX_ATTEMPTS (défaut=3) avec HTTP 429
3. **JSON fence stripping** : L'OpenRouter client nettoie les balises ` ```json ` que certains modèles ajoutent malgré le mode `json_object`
4. **Retry** : `tenacity` avec backoff exponentiel sur les appels HTTP OpenRouter et GitLab
5. **Polling timeout** : `evaluate_result` poll toutes les 15s, timeout à 600s (10min)
