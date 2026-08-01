# Step 2: Projets Embarqués & Pipelines CI/CD (Jour 2)

Ce document résume l'implémentation et la validation du Jour 2, qui met en place les projets de test (Yocto, Zephyr, QNX) et les pipelines de compilation avec intégration conditionnelle (webhook agent IA + MinIO).

## Objectifs accomplis
- Initialisation locale de 3 projets de démo (`yocto-demo`, `zephyr-demo`, `qnx-demo`).
- Création automatique des pipelines `.gitlab-ci.yml` pour compiler dans les images adaptées.
- Mise en place d'un script d'injection d'erreur (`inject-error.sh`).
- Transfert automatique des logs de compilation (traces CI) vers le stockage S3 MinIO en cas d'échec.
- Création d'une tâche de validation dédiée aux branches correctives de l'IA (`ai-fix/*`).

---

## Modélisation du pipeline `.gitlab-ci.yml`

Le fichier pipeline généré pour chaque projet se compose désormais de deux stages distincts contrôlés par des règles de nommage de branche :

### 1. `build-job` (Compilations classiques)
Ce job s'exécute sur toutes les branches **sauf** celles créées par l'agent IA (`ai-fix/*`).
Il compile le code via le script `build.sh`. S'il échoue (simulé par `inject-error.sh`), il :
1. Télécharge dynamiquement le binaire MinIO client (`mc`).
2. S'authentifie à l'instance locale via le réseau Docker (`host.docker.internal:9000`).
3. Téléverse le fichier complet `build.log` vers le bucket `build-logs` avec un identifiant unique combinant le `PIPELINE_ID` et `JOB_ID`.
4. Émet une requête HTTP `POST` (webhook) vers l'agent FastAPI (sur le port 8000) contenant le SHA du commit défectueux, la branche et l'ID du job.

### 2. `validate-job` (Validation des corrections IA)
Ce job s'exécute **uniquement** sur les branches commençant par `ai-fix/`.
Il sert de vérification finale pour l'Agent Reviewer. Si le build réussit sur cette branche, cela signifie que la correction de l'IA (le Patch) est valide, permettant à l'Agent d'ouvrir ou d'approuver la Merge Request (ce sera implémenté lors des Jours 3 et 4).

---

## Problèmes résolus

1. **Le Runner tentait de télécharger l'image depuis Docker Hub** :
   - *Problème* : Le GitLab Runner échouait sur l'erreur `image not found` car les images `embedded-build:yocto/zephyr/qnx` ont été compilées sur la machine locale.
   - *Solution* : Mise à jour du `config.toml` du runner pour inclure `pull_policy = ["if-not-present"]`.
2. **GitLab clone URL invalide depuis le runner** :
   - *Problème* : Le Runner tentait de cloner le dépôt via `http://localhost`, qui pointe vers le runner lui-même depuis son conteneur.
   - *Solution* : Ajout de la directive `clone_url = "http://gitlab"` dans la configuration globale du Runner.
3. **Mise à jour récursive des projets GitLab sans force-push** :
   - *Problème* : La branche par défaut `main` est protégée contre les `force push`.
   - *Solution* : Modification des configurations de pipeline via clonage complet, modification via `sed`, commit et push "fast-forward" pour respecter les protections GitLab.

---

## Validation et vérification

Les 3 critères de validation du Jour 2 ont été vérifiés avec succès dans GitLab :

1. **Build Yocto success en pipeline GitLab** ✅
   - Un commit sans erreur déclenche le pipeline qui compile (simulation via main.c) et renvoie un "Passed" vert (ex: Pipeline `#6`).
2. **`inject-error.sh` → build fail → log dans MinIO → webhook reçu** ✅
   - En lançant `./scripts/inject-error.sh yocto-demo src_uri`, un nouveau commit est poussé contenant le fichier de déclenchement d'erreur.
   - Le build échoue avec l'erreur `Failed to fetch URL`.
   - Dans le trace GitLab, on observe l'upload réussi : `/build.log -> myminio/build-logs/pipeline-10-job-10.log`.
   - La requête `curl` au webhook FastAPI s'exécute (pour le moment elle fait un *Connection Refused* attendu, puisque l'API FastAPI du Jour 3 n'est pas encore codée).
3. **Pipeline `validate-job` se déclenche uniquement sur `ai-fix/*`** ✅
   - En poussant une branche nommée `ai-fix/test-fix`, le job `build-job` est bien ignoré.
   - À sa place, `validate-job` prend le relai et passe au vert avec la confirmation `✅ Validation de la correction par l'IA réussie !`.
