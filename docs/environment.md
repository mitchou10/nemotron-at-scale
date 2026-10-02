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
| `ASR_API_KEY` | vide | Clé envoyée aux instances ASR, si elles en exigent une. **Secret.** |
| `ASR_STATE_STORE` | `database` | `database` : l'état des instances et des flux est dans PostgreSQL (nécessaire avec plusieurs réplicas du backend). `memory` : en mémoire du processus. |
| `ASR_PROBE_INTERVAL_S` | `5` | Secondes entre deux mesures de latence et de charge. |
| `ASR_MAX_LATENCY_MS` | `0` | Ignore les instances plus lentes que cette valeur, sauf si toutes les libres le sont. `0` : désactivé. |
| `ASR_BUFFER_SECONDS` | `30` | Secondes d'audio gardées par flux, rejouées sur une autre instance en cas de coupure. |
| `ASR_MAX_FAILOVERS` | `2` | Nombre de reprises autorisées par flux. `0` désactive la reprise. |
| `ASR_HISTORY_INTERVAL_S` | `30` | Une mesure par instance toutes les N secondes, pour la page de statut. `0` désactive l'historique. |
| `ASR_HISTORY_RETENTION_HOURS` | `168` | Durée de conservation des mesures (7 jours). Les plus anciennes sont supprimées. |

Il n'y a plus de liste d'URL : les instances ASR **s'enregistrent elles-mêmes** (voir ci-dessous). L'ordre de
remplissage est la `priority` qu'elles annoncent (plus petit d'abord, puis par adresse), la limite de flux est
le `max_streams` annoncé.

### Registre des workers

Les serveurs de transcription (`vosk_service`, `nemo-speech`) et de synthèse vocale (`tts_service`) appellent
`PUT /api/v1/registry/instances/<id>` quand ils sont prêts, puis toutes les 10 s (heartbeat). Une instance qui
s'arrête proprement se désenregistre aussitôt (`DELETE`) ; une instance qui meurt est retirée après `REGISTRY_TTL_S`
sans heartbeat. Le registre est dans PostgreSQL : tous les réplicas du backend voient les mêmes instances.

| Variable | Défaut | Description |
|---|---|---|
| `REGISTRY_TOKEN` | vide | Jeton exigé (`Authorization: Bearer`) pour lire ou modifier le registre. Vide : registre ouvert, à réserver à un essai local. **Secret.** |
| `REGISTRY_TTL_S` | `30` | Délai sans heartbeat après lequel une instance n'est plus utilisée. |
| `REGISTRY_STORE` | `database` | `database` : PostgreSQL (plusieurs réplicas). `memory` : en mémoire du processus. |

### Synthèse vocale (relais)

Le backend est la gateway de la synthèse vocale : `POST /api/v1/audio/speech` est envoyé à l'instance `tts_service`
(compatible OpenAI) la moins chargée parmi celles qui se sont enregistrées. Une instance injoignable est écartée
10 s, une instance pleine (`429`) ou pas prête (`503`) est sautée pour cette requête.

| Variable | Défaut | Description |
|---|---|---|
| `TTS_API_KEY` | vide | Clé envoyée aux instances `tts_service`, si elle y est exigée. **Secret.** |
| `TTS_TIMEOUT_S` | `60` | Délai maximal d'une requête vers le service. |

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
| `VOSK_REGISTRY_URL` | vide | Adresse du backend (`http://backend:8000`). Vide : le serveur ne s'enregistre pas. |
| `VOSK_REGISTRY_TOKEN` | vide | Même valeur que `REGISTRY_TOKEN` du backend. **Secret.** |
| `VOSK_REGISTRY_ID` | hostname | Identifiant unique de l'instance. |
| `VOSK_REGISTRY_PRIORITY` | `0` | Ordre de remplissage annoncé (0 à 1000, plus petit d'abord). |
| `VOSK_REGISTRY_INTERVAL_S` | `10` | Secondes entre deux heartbeats (inférieur au TTL du backend). |
| `VOSK_SELF_URL` | IP du conteneur | Adresse annoncée au backend (`http://asr-vosk:8080`). Par défaut `http://<IP du conteneur>:<port>`. |

Une variable vide est ignorée (`VOSK_MAX_STREAMS=` revient au calcul automatique).

## Service TTS (Piper)

Préfixe `TTS_`, lu par `tts_service` ([tts_service/README.md](../tts_service/README.md)). `TTS_API_KEY` doit être la
même des deux côtés (backend et service) ; `TTS_REGISTRY_TOKEN` doit valoir `REGISTRY_TOKEN` du backend.

| Variable | Défaut | Description |
|---|---|---|
| `TTS_HOST` / `TTS_PORT` | `0.0.0.0` / `8080` | Adresse d'écoute. |
| `TTS_VOICES` | `fr_FR-siwis-medium` | Voix Piper, séparées par des virgules (la première est la voix par défaut). L'image embarque `fr_FR-siwis-medium` (argument de build `TTS_VOICES`) ; les autres sont téléchargées au premier démarrage si `/voices` est inscriptible. |
| `TTS_VOICE_DIR` | `/voices` | Dossier des voix (celles de l'image y sont déjà). |
| `TTS_VOICE_URL` | `https://huggingface.co/rhasspy/piper-voices/resolve/main` | Origine des voix, au build comme au démarrage (miroir interne possible). |
| `TTS_MAX_REQUESTS` | CPU | Synthèses simultanées ; `429` au-delà. |
| `TTS_MAX_INPUT_CHARS` | `4096` | Taille maximale du texte (limite d'OpenAI). |
| `TTS_MP3_BITRATE` | `128` | Débit du MP3, en kbit/s. |
| `TTS_API_KEY` | vide | Clé exigée des clients. **Secret.** |
| `TTS_CORS_ORIGIN` | vide | Origine CORS autorisée. |
| `TTS_LOG_LEVEL` | `info` | Niveau de log. |
| `TTS_REGISTRY_URL` | vide | Adresse du backend (`http://backend:8000`). Vide : le serveur ne s'enregistre pas. |
| `TTS_REGISTRY_TOKEN` | vide | Même valeur que `REGISTRY_TOKEN` du backend. **Secret.** |
| `TTS_REGISTRY_ID` | hostname | Identifiant unique de l'instance. |
| `TTS_REGISTRY_PRIORITY` | `0` | Départage à charge égale (plus petit d'abord). |
| `TTS_REGISTRY_INTERVAL_S` | `10` | Secondes entre deux heartbeats (inférieur au TTL du backend). |
| `TTS_SELF_URL` | IP du conteneur | Adresse annoncée au backend (`http://tts:8080`). Par défaut `http://<IP du conteneur>:<port>`. |

## Docker Compose uniquement

Ces variables ne sont lues que par [docker-compose.yml](../docker-compose.yml).

| Variable | Défaut | Description |
|---|---|---|
| `DB_PORT` | `5432` | Port PostgreSQL publié sur l'hôte. |
| `BACKEND_PORT` | `8000` | Port du backend publié sur l'hôte. |
| `FRONTEND_PORT` | `3000` | Port de la page de statut publié sur l'hôte. |
| `PROMETHEUS_PORT` | `9090` | Port de Prometheus (profil `monitoring`). |
| `REGISTRY_TOKEN` | `change-me` | Jeton d'enregistrement, lu par le backend et passé aux workers et aux registrars Nemo. |
| `TTS_PORT` | `8081` | Port du service TTS publié sur l'hôte (profil `tts`). |
| `ASR_MODEL_FILE` | `nemotron-speech-streaming-en-0.6b.q8_0.gguf` | Fichier du modèle NeMo. |
| `ASR_MODEL_URL` | Hugging Face (révision figée) | D'où `asr-model` télécharge le modèle NeMo. |
| `ASR_HTTP_THREADS` | `32` | Threads HTTP des instances `nemo-speech` : plafond dur de flux par instance. |
| `NEMO_SPEECH_REF` | `main` | Branche ou tag de NeMo-Speech.cpp à construire. |
| `VOSK_CPUS` | `4` | Limite CPU du conteneur Vosk (dont dépend la limite de flux). |
| `VOSK_MEMORY` | `2g` | Limite mémoire du conteneur Vosk. |

## Frontend (nginx)

| Variable | Défaut | Description |
|---|---|---|
| `BACKEND_URL` | `http://backend:8000` | Adresse du backend vers laquelle nginx proxifie `/api/`. Résolue à chaque requête : le frontend démarre même si le backend n'est pas encore là. |

## Helm

Le chart ([helm/values.yaml](../helm/values.yaml)) fournit les variables ainsi :

| Section | Contenu |
|---|---|
| `backend.envCm` | Configuration non secrète du backend (`APP_*`, `ASR_*`). |
| `backend.env.REGISTRY_TOKEN` | Lu dans le secret `nemotron-registry` (clé `token`, facultatif). Le même secret donne `VOSK_REGISTRY_TOKEN` et `TTS_REGISTRY_TOKEN`. |
| `backend.env.DATABASE_URL` | Lue depuis le secret Kubernetes `nemotron-database`, clé `url`, **à créer avant l'installation**. |
| `vosk.envCm` | Configuration de Vosk (`VOSK_*`), dont `VOSK_REGISTRY_URL` (calculé vers le Service backend du release). |
| `tts.envCm` | `TTS_VOICES` et `TTS_REGISTRY_URL` (calculé vers le Service backend du release). |
| `frontend.envCm` | `BACKEND_URL`, calculé vers le Service backend du release. |
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
| `APP_CLIENT_ID`, `APP_PRIVATE_KEY` | secrets | GitHub | GitHub App facultative : la pull request de release déclenche alors la CI, et `bump-chart` peut pousser sur une branche protégée. |
| `CATALOG_PATH` | variable | GitLab | Projet du catalogue de templates CI (Vault, Kaniko, Helm). |
| `REGISTRY_HOST`, `PROJECT_PATH` | variables | GitLab | Registre et chemin des images : `REGISTRY_URL` = `REGISTRY_HOST/PROJECT_PATH`. |
| `IMAGE_REPOSITORY` | variable | GitLab | Dépôt OCI où le chart est poussé. |
| `DOCKER_AUTH` | variable masquée | GitLab | Contenu de `config.json` Docker pour pousser les images et le chart. |
| `DOCKERHUB_MIRROR_URL` | variable | GitLab | Miroir Docker Hub, passé en `--build-arg` à Kaniko. |
