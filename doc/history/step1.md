# Step 1: Infrastructure Kubernetes (K3s) (Jour 1)

Ce document résume l'implémentation et la validation du Jour 1 de l'infrastructure AI-CICD pour les projets embarqués.

## Objectif
Déployer l'ensemble des services nécessaires à l'infrastructure de développement en local via un cluster K3s léger. Le serveur dispose de 24 Go de RAM, levant la contrainte mémoire précédente et permettant une isolation parfaite.

### Services déployés :
- **K3s** : Orchestrateur Kubernetes léger.
- **GitLab CE** : Dépôt de code et moteur CI/CD.
- **GitLab Runner (Kubernetes Executor)** : Lance un pod éphémère et isolé pour chaque pipeline CI.
- **MinIO** : Stockage objet S3 compatible (logs, artefacts de build).
- **Redis** : File d'attente pour l'agent IA.
- **Observabilité** : Prometheus, Promtail, Loki, et Grafana.

---

## Problèmes rencontrés et correctifs apportés

Durant la mise en place de la stack, plusieurs défis techniques ont été résolus pour assurer la stabilité du système :

1. **Crash de Loki (Permissions et Compactor)** :
   - *Problème* : L'image Loki utilise l'utilisateur non-root (UID `10001`), causant des erreurs de permission sur le volume monté. De plus, la version 3.x exige le paramètre `delete_request_store` si la rétention est activée.
   - *Solution* : Le montage a été changé de `/loki` vers `/tmp/loki` et la configuration `delete_request_store: filesystem` a été ajoutée dans `loki-config.yaml`.

2. **Échec de l'initialisation de GitLab CE** :
   - *Problème* : Le paramètre `grafana['enable'] = false` n'est plus supporté par les nouvelles versions de `gitlab/gitlab-ce:17.1.0-ce.0`, causant un crash lors du `reconfigure`.
   - *Solution* : La variable d'environnement a été retirée de `docker-compose.yml`.

3. **Fiabilité des Healthchecks GitLab** :
   - *Problème* : Les endpoints `/-/health` et `/-/readiness` nécessitaient des configurations d'IP whitelist ou renvoyaient des erreurs 404/503 imprévisibles.
   - *Solution* : Les healthchecks (Compose, scripts d'attente, script de vérification) ont été remplacés par `http://localhost/users/sign_in`, qui renvoie un code `200` de manière fiable dès que l'interface est prête.

4. **Faux négatifs dans `verify-day1.sh` (Permissions Docker)** :
   - *Problème* : La commande `make verify-day1` échouait sur Redis et le GitLab Runner (❌) car les commandes `docker exec` et `docker ps` étaient exécutées sans les permissions adéquates si l'utilisateur courant n'était pas membre du groupe docker.
   - *Solution* : Le script `verify-day1.sh` a été mis à jour pour exécuter spécifiquement les commandes Docker à l'aide de `sg docker -c "..."`. 

5. **Automatisation complète de l'enregistrement du Runner et de la configuration GitLab** :
   - *Amélioration* : Plus aucune action manuelle n'est requise. Le script génère dynamiquement un **Personal Access Token** via `gitlab-rails runner`, et l'enregistrement du runner utilise la nouvelle API (tokens `glrt-`) adaptée à GitLab 17+.

---

## Comment valider l'installation ?

Toutes les commandes sont encapsulées dans le `Makefile` à la racine du projet.

1. **Démarrer les services** :
   ```bash
   make up
   ```
   *Ceci lance Docker Compose et attend automatiquement que GitLab soit prêt.*

2. **Configurer les projets GitLab et le Runner** :
   ```bash
   # Crée les groupes, les projets de démo, configure les webhooks et sauvegarde le token
   make setup-gitlab
   
   # Enregistre automatiquement le Runner
   make register-runner
   ```

3. **Vérification finale** :
   ```bash
   make verify-day1
   ```
   **Résultat attendu :** Tous les voyants sont au vert (`9 ✅ 0 ❌`), et la consommation mémoire reste maîtrisée (généralement moins de 500 MiB pour la base sans les pipelines lourds).
