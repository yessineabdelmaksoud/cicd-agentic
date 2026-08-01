Voici une liste complète des commandes de **setup** (mise en route) et de **validation / test** pour vérifier que toute la plateforme fonctionne correctement, du démarrage jusqu'à l'injection d'erreur.

Toutes ces commandes doivent être lancées depuis la racine de votre projet `ai-cicd-embedded`.

### 🚀 1. Commandes de Setup (Démarrage)

**1. Démarrer l'infrastructure K3s (GitLab, MinIO, Redis, Agent, etc.)**
```bash
make k3s-up
```

**2. Construire les images Docker de compilation embarquée (Yocto, Zephyr, QNX)**
*(Cette commande est indispensable pour que le Runner GitLab sache comment compiler les projets).*
```bash
make build-images
```

**3. Démarrer l'Agent IA (FastAPI + Worker Redis)**
*(Ces conteneurs traiteront les webhooks de GitLab).*
```bash
make deploy-agent
```

---

### 🔍 2. Commandes de Validation (Vérification de l'état)

**1. Vérifier que tous les services d'infrastructure sont opérationnels (Script Jour 1)**
```bash
make verify-day1
```

**2. Voir le statut de tous les pods K3s**
```bash
kubectl get pods
```
*(Vous devriez voir `gitlab`, `gitlab-runner`, `minio`, `redis`, `agent`, `worker` en statut `Running`).*

**3. Suivre les logs de l'Agent IA en temps réel**
*(Très utile pour voir le webhook arriver et l'agent générer son patch).*
```bash
kubectl logs -f deployment/agent
```

---

### 🛠️ 3. Commandes de Test E2E (Déclenchement CI/CD & Agent)

**1. Déclencher un build qui passe (sans erreur)**
Vous pouvez déclencher manuellement via l'interface web GitLab ou via l'API. Par exemple, pour déclencher le pipeline du projet `zephyr-demo` (ID 5) :
```bash
source .env && curl -X POST -s --header "PRIVATE-TOKEN: $GITLAB_PROJECT_TOKEN" "http://localhost/api/v4/projects/5/pipeline?ref=main"
```

**2. Injecter une erreur pour tester la réparation IA (Workflow principal)**
C'est la commande la plus importante pour tester la plateforme : elle pousse un commit cassé, fait échouer le build, et déclenche le webhook vers l'Agent IA.

Pour `qnx-demo` (erreur de compilation C) :
```bash
./scripts/inject-error.sh qnx-demo compile
```

Pour `yocto-demo` (erreur de recette / SRC_URI) :
```bash
./scripts/inject-error.sh yocto-demo src_uri
```

**3. Vérifier le statut des pipelines d'un projet**
Pour voir si l'erreur a bien fait échouer le pipeline (remplacez `6` par l'ID du projet, ex: 6 pour qnx-demo, 5 pour zephyr-demo) :
```bash
source .env && curl -s --header "PRIVATE-TOKEN: $GITLAB_PROJECT_TOKEN" "http://localhost/api/v4/projects/6/pipelines" | grep -E '"id"|"status"|"ref"' | head -n 15
```

---

### 🧹 4. Commandes d'Arrêt et de Nettoyage (K3s et Docker)

**1. Arrêter et supprimer l'infrastructure K3s**
```bash
make k3s-down
```

*(Commandes Docker Compose (Legacy) : `make stop`, `make down`)*

**3. Réinitialiser complètement (⚠️ Supprime les conteneurs ET TOUTES les données/volumes)**
```bash
make clean
```

*(Si vous voulez juste redémarrer un service spécifique sans perdre de données, utilisez par exemple : `make restart s=agent`).*