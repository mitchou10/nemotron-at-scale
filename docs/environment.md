# Variables d'environnement

Où se règle chaque variable, et ce qu'elle fait. Les valeurs par défaut viennent du code
([backend/app/config.py](../backend/app/config.py), [vosk_service/app/config.py](../vosk_service/app/config.py))
et de [docker-compose.yml](../docker-compose.yml) ; le modèle de configuration est [.env.example](../.env.example).

| Contexte | Où les définir |
|---|---|
| Docker Compose | fichier `.env` à la racine (`cp .env.example .env`) |
| Backend seul (hors Docker) | `.env` à la racine ou dans `backend/` |
| Vosk seul (hors Docker) | `.env` dans `vosk_service/` ou à la racine (préfixe `VOSK_`) |
| Kubernetes | `helm/values.yaml` : `backend.envCm` / `backend.env`, `vosk.envCm` (voir [Helm](#helm)) |

`.env` est ignoré par git. Ne mettez jamais de mot de passe dans `.env.example`.

## Backend

Les noms sont sensibles à la casse. Les valeurs entre crochets sont les défauts du code.

### Application

| Variable | Défaut | Description |
|---|---|---|
| `APP_NAME` | `nemotron-backend` | Nom de l'application (documentation OpenAPI, logs). |
| `APP_ENV` | `development` | `development`, `staging` ou `production`. L'image de production fixe `production`. |
| `APP_DEBUG` | `true` | Mode debug. À mettre à `false` en production. |
| `APP_HOST` | `0.0.0.0` | Adresse d'écoute. |
| `APP_PORT` | `8000` | Port d'écoute. |
| `APP_LOG_LEVEL` | `info` | Niveau de log. |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Origines autorisées, liste JSON. |

### Base de données

| Variable | Défaut | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://nemotron:nemotron@db:5432/nemotron` | URL SQLAlchemy asynchrone (pilote `asyncpg`). **Secret** en production. |
| `DATABASE_URL_TEST` | `postgresql+asyncpg://nemotron:nemotron@db:5432/nemotron_test` | Base utilisée par les tests. |

### Transcription en direct (ASR)

Le backend relaie l'audio vers des instances ASR (`nemo-speech serve`, `vosk_service`), mesure leur latence
et leur charge, et route chaque flux vers la meilleure.

| Variable | Défaut | Description |
|---|---|---|
| `ASR_ENABLED` | `false` (code) / `true` (compose) | Active la transcription. Le compose force `true` sauf si `.env` dit autre chose. |
| `ASR_URL` | gpu, cpu, vosk | URLs WebSocket séparées par des virgules, **dans l'ordre de remplissage** : une instance est remplie avant de passer à la suivante. `#N` en fin d'URL fixe sa limite de flux (`ws://asr-vosk:8080/v1/audio/transcriptions/realtime#12`). |
| `ASR_API_KEY` | vide | Clé envoyée aux instances ASR, si elles en exigent une. **Secret.** |
| `ASR_DISCOVERY` | `dns` | `dns` : chaque nom d'hôte est résolu en toutes les IP des réplicas (`--scale`). `static` : les URL sont utilisées telles quelles. |
| `ASR_STATE_STORE` | `database` | `database` : l'état des instances et des flux est dans PostgreSQL (nécessaire avec plusieurs réplicas du backend). `memory` : en mémoire du processus. |
| `ASR_MAX_STREAMS_PER_INSTANCE` | `8` | Limite de flux pour une URL sans `#N`. |
| `ASR_PROBE_INTERVAL_S` | `5` | Secondes entre deux mesures de latence et de charge. |
| `ASR_MAX_LATENCY_MS` | `0` | Ignore les instances plus lentes que cette valeur, sauf si toutes les libres le sont. `0` : désactivé. |
| `ASR_BUFFER_SECONDS` | `30` | Secondes d'audio gardées par flux, rejouées sur une autre instance en cas de coupure. |
| `ASR_MAX_FAILOVERS` | `2` | Nombre de reprises autorisées par flux. `0` désactive la reprise. |
| `ASR_HISTORY_INTERVAL_S` | `30` | Une mesure par instance toutes les N secondes, pour la page de statut. `0` désactive l'historique. |
| `ASR_HISTORY_RETENTION_HOURS` | `168` | Durée de conservation des mesures (7 jours). Les plus anciennes sont supprimées. |

Un nom d'hôte qui ne se résout pas (service non démarré, profil Compose inactif) est simplement ignoré.

## Service Vosk

Préfixe `VOSK_`. Le service dimensionne ses limites d'après les CPU **réellement disponibles** (limite du
conteneur, pas les cœurs de la machine).

| Variable | Défaut | Description |
|---|---|---|
| `VOSK_HOST` | `0.0.0.0` | Adresse d'écoute. |
| `VOSK_PORT` | `8080` | Port d'écoute. |
| `VOSK_MODEL_NAME` | `vosk-model-small-fr-0.22` | Modèle (et donc la langue). Cherché dans `VOSK_MODEL_DIR`, téléchargé s'il manque. |
| `VOSK_MODEL_DIR` | `/models` | Dossier des modèles. À monter sur un volume pour ne pas retélécharger à chaque démarrage. |
| `VOSK_MODEL_URL` | `https://alphacephei.com/vosk/models/{name}.zip` | URL de téléchargement ; `{name}` est remplacé par le nom du modèle. |
| `VOSK_MAX_STREAMS` | calculé | Flux temps réel simultanés. Vide : `VOSK_STREAMS_PER_CPU` × CPU. |
| `VOSK_STREAMS_PER_CPU` | `1.0` (code) / `3` (compose et chart) | Flux par CPU. Capacité mesurée : environ 4 par CPU avec le petit modèle français. |
| `VOSK_THREADS` | CPU | Threads de décodage. |
| `VOSK_MAX_REQUESTS` | `VOSK_THREADS` | `POST /v1/audio/transcriptions` simultanés (429 au-delà). |
| `VOSK_MAX_UPLOAD_MB` | `64` | Taille maximale d'un fichier envoyé. |
| `VOSK_MAX_STREAM_SECONDS` | `3600` | Durée maximale d'un flux. |
| `VOSK_IDLE_TIMEOUT_S` | `120` | Ferme un flux silencieux. `0` : jamais. |
| `VOSK_ENDPOINTING` | `false` | Émet un texte final à chaque fin d'énoncé détectée. Sinon, les finaux viennent de `input_audio_buffer.commit`. |
| `VOSK_API_KEY` | vide | Clé exigée des clients (le backend la fournit via `ASR_API_KEY`). **Secret.** |
| `VOSK_CORS_ORIGIN` | vide | Origine CORS autorisée. |
| `VOSK_LOG_LEVEL` | `info` | Niveau de log. |

Une variable vide est ignorée (`VOSK_MAX_STREAMS=` revient au calcul automatique).

## Docker Compose uniquement

Ces variables ne sont lues que par [docker-compose.yml](../docker-compose.yml).

| Variable | Défaut | Description |
|---|---|---|
| `DB_PORT` | `5432` | Port PostgreSQL publié sur l'hôte. |
| `BACKEND_PORT` | `8000` | Port du backend publié sur l'hôte. |
| `PROMETHEUS_PORT` | `9090` | Port de Prometheus (profil `monitoring`). |
| `ASR_MODEL_FILE` | `nemotron-speech-streaming-en-0.6b.q8_0.gguf` | Fichier du modèle NeMo. |
| `ASR_MODEL_URL` | Hugging Face (révision figée) | D'où `asr-model` télécharge le modèle NeMo. |
| `ASR_HTTP_THREADS` | `32` | Threads HTTP des instances `nemo-speech` : plafond dur de flux par instance. |
| `NEMO_SPEECH_REF` | `main` | Branche ou tag de NeMo-Speech.cpp à construire. |
| `VOSK_CPUS` | `4` | Limite CPU du conteneur Vosk (dont dépend la limite de flux). |
| `VOSK_MEMORY` | `2g` | Limite mémoire du conteneur Vosk. |

## Helm

Le chart ([helm/values.yaml](../helm/values.yaml)) fournit les variables ainsi :

| Section | Contenu |
|---|---|
| `backend.envCm` | Configuration non secrète du backend (`APP_*`, `ASR_*`). Les valeurs sont passées à `tpl` : `ASR_URL` pointe vers le service Vosk du release. |
| `backend.env.DATABASE_URL` | Lue depuis le secret Kubernetes `nemotron-database`, clé `url`, **à créer avant l'installation**. |
| `vosk.envCm` | Configuration de Vosk (`VOSK_*`). |
| `vosk.resources` | Limites CPU et mémoire ; la limite de flux en dérive. |

```bash
kubectl create secret generic nemotron-database \
  --from-literal=url='postgresql+asyncpg://user:password@host:5432/nemotron'
helm install nemotron ./helm
```

Pour ajouter une clé ASR : `ASR_API_KEY` côté backend et `VOSK_API_KEY` côté Vosk, depuis un secret
(`backend.env` avec `valueFrom.secretKeyRef`, ou `envSecret`).

## CI/CD

| Nom | Type | Où | Rôle |
|---|---|---|---|
| `ENABLE_PRERELEASE` | variable | GitHub, Settings > Actions > Variables | `true` : active la branche `dev` et les release candidates. |
| `APP_CLIENT_ID`, `APP_PRIVATE_KEY` | secrets | GitHub | GitHub App facultative : la pull request de release déclenche alors la CI, et `bump-chart` peut pousser sur une branche protégée. |
| `CATALOG_PATH` | variable | GitLab | Projet du catalogue de templates CI (Vault, Kaniko, Helm). |
| `REGISTRY_HOST`, `PROJECT_PATH` | variables | GitLab | Registre et chemin des images : `REGISTRY_URL` = `REGISTRY_HOST/PROJECT_PATH`. |
| `IMAGE_REPOSITORY` | variable | GitLab | Dépôt OCI où le chart est poussé. |
| `DOCKER_AUTH` | variable masquée | GitLab | Contenu de `config.json` Docker pour pousser les images et le chart. |
| `DOCKERHUB_MIRROR_URL` | variable | GitLab | Miroir Docker Hub, passé en `--build-arg` à Kaniko. |
