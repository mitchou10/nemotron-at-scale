# Nemotron Backend

API FastAPI asynchrone pour le projet **nemotron-at-scale**.

## Stack

- **Python 3.12** + **FastAPI** (async natif)
- **SQLAlchemy 2.0** async avec **asyncpg**
- **Alembic** pour les migrations
- **PostgreSQL 16**
- **uv** comme gestionnaire de paquets
- **Docker** / **Docker Compose**

## Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py            # Factory FastAPI + lifespan async
│   ├── config.py          # Settings (pydantic-settings)
│   ├── db.py              # Engine + session async
│   ├── models/asr.py      # Tables asr_instances, asr_streams
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── health.py  # /health, /health/ready
│   │       ├── audio.py   # WebSocket /ws/audio/{client_id}
│       ├── asr.py     # GET /asr/instances, /asr/state/* (état de la gateway)
│       └── metrics.py # GET /metrics (Prometheus)
│   └── services/
│       ├── transcription.py  # Interfaces de transcription (indépendantes du modèle)
│       ├── nemo_speech.py    # Client du serveur `nemo-speech serve`
│       ├── discovery.py      # Discovery abstraite, StaticDiscovery, DnsDiscovery
│       ├── state.py          # StateStore abstrait, en mémoire, StreamRecorder
│       ├── state_sql.py      # StateStore en base (SQLAlchemy)
│       ├── metrics.py        # Métriques Prometheus par instance
│       ├── gateway.py        # Remplissage des instances, sondes de latence, failover
│       └── resilient.py      # Tampon audio + reprise sur une autre instance
├── alembic/
│   ├── env.py             # Config async
│   ├── script.py.mako
│   └── versions/
│       └── 0001_asr_state.py
├── tests/
│   ├── conftest.py        # Fixtures async (DB, client)
│   ├── test_health.py
│   └── test_audio_ws.py
├── monitoring/prometheus.yml  # Scrape des métriques de la gateway
├── .env.example
├── .gitignore
├── alembic.ini
├── docker-compose.yml
├── Dockerfile             # Production (multi-stage)
├── Dockerfile.dev         # Dev avec reload
├── pyproject.toml
└── README.md
```

## Démarrage

### Avec Docker (recommandé)

```bash
# Copier la config
cp .env.example .env

# Mode dev (avec hot-reload)
docker compose --profile dev up --build

# Mode production
docker compose up --build
```

L'API est disponible sur http://localhost:8000

- Docs Swagger : http://localhost:8000/api/v1/docs
- ReDoc : http://localhost:8000/api/v1/redoc

### Avec uv (local)

```bash
# Installer uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync les dépendances
uv sync

# Lancer les migrations (nécessite PostgreSQL)
alembic upgrade head

# Démarrer le serveur
uv run uvicorn app.main:app --reload
```

## Tests

```bash
uv sync --extra dev
uv run pytest
```

## Migrations Alembic

```bash
# Générer une migration
alembic revision --autogenerate -m "description"

# Appliquer
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Endpoints

| Méthode | Route                    | Description          |
|---------|--------------------------|----------------------|
| GET     | `/api/v1/health`         | Liveness probe       |
| GET     | `/api/v1/health/ready`   | Readiness probe      |
| GET     | `/api/v1/asr/instances`  | État des instances ASR (gateway) |
| WS      | `/api/v1/ws/audio/{client_id}` | Flux audio PCM 16 kHz mono 16-bit, id unique par client |

### Transcription live (Nemotron 0.6B)

Le modèle tourne dans des instances séparées : [`nemo-speech serve`](https://github.com/NVIDIA/NeMo-Speech.cpp)
(runtime C++, GGUF quantifié Q8). Le backend embarque une **gateway** ([gateway.py](app/services/gateway.py)) :

- **Découverte** ([discovery.py](app/services/discovery.py)) : classe abstraite `Discovery` (méthode
  `discover()`). `StaticDiscovery` prend une liste d'`Endpoint(url, max_streams)` telle quelle ;
  `DnsDiscovery` (défaut, `ASR_DISCOVERY=dns`) résout chaque hostname vers toutes les IP de ses
  réplicas (`--scale`). CPU et GPU peuvent coexister.
- **Latence** : chaque instance est sondée (`GET /ready`, toutes les `ASR_PROBE_INTERVAL_S` s) ;
  la latence est lissée (moyenne exponentielle) et une instance qui ne répond pas est écartée.
- **Remplissage** : un nouveau flux va à la première instance saine qui n'a pas atteint sa limite,
  dans l'ordre de `ASR_URL`, puis par adresse pour les réplicas d'un même service ; la suivante
  n'est utilisée qu'une fois la précédente pleine, et un flux terminé libère sa place.
  Limite par instance : `ASR_MAX_STREAMS_PER_INSTANCE`, ou par URL avec `#N`
  (ex. `ws://asr-gpu:8080/v1/audio/transcriptions/realtime#16`).
- **Seuil de latence** (optionnel) : avec `ASR_MAX_LATENCY_MS`, une instance plus lente est ignorée
  tant qu'une instance rapide a de la place (sinon la plus rapide des lentes est utilisée).
- Si la connexion à une instance échoue, la suivante est essayée (failover).
- **Reprise en cours de flux** ([resilient.py](app/services/resilient.py)) : l'audio du segment en cours
  (depuis le dernier `commit` acquitté par l'instance) est gardé dans un tampon borné
  (`ASR_BUFFER_SECONDS`, 30 s). Si l'instance tombe, la gateway ouvre un flux sur une autre instance
  et rejoue le tampon ; le texte partiel du client repart simplement du début du segment.
  `ASR_MAX_FAILOVERS` limite les reprises par flux (0 = désactivé). Attention : si l'endpointing
  du serveur est activé, ses `final` automatiques ne vident pas le tampon et un rejeu peut
  dupliquer du texte déjà finalisé.
- **Erreurs** : service indisponible → fermeture 1011 ; toutes les instances pleines → 1013 (réessayer).
- **État sauvegardé** ([state.py](app/services/state.py)) : classe abstraite `StateStore`
  (`InMemoryStateStore`, ou `SqlStateStore` en base avec `ASR_STATE_STORE=database`, tables
  `asr_instances` et `asr_streams`, migration Alembic `0001`). On y trouve, pour chaque instance,
  son statut (`up`, `down`, `draining`, `gone`), sa latence et sa charge ; pour chaque flux, le client,
  l'instance, le statut (`running`, `recovering`, `ended`, `failed`, `interrupted`) et le nombre de
  reprises. Au démarrage, les flux laissés `running` par un ancien process passent en `interrupted`.
  Une base indisponible n'interrompt jamais un flux (l'erreur est seulement loguée).
- **Métriques Prometheus** ([metrics.py](app/services/metrics.py)) sur `GET /metrics`, avec le label `instance` :

  | métrique | type | sens |
  |---|---|---|
  | `asr_instance_up` | gauge | 1 si l'instance est saine |
  | `asr_instance_latency_ms` | gauge | latence `/ready` lissée |
  | `asr_instance_probe_seconds` | histogramme | latence de chaque sonde |
  | `asr_instance_probe_failures_total` | compteur | sondes en échec |
  | `asr_instance_active_streams` / `asr_instance_max_streams` | gauge | charge et limite |
  | `asr_session_open_seconds` | histogramme | temps d'ouverture d'une session WebSocket |
  | `asr_first_result_seconds` | histogramme | du premier audio envoyé au premier texte reçu |
  | `asr_streams_opened_total` | compteur | flux ouverts |
  | `asr_stream_open_failures_total` | compteur | ouvertures en échec |
  | `asr_instance_failures_total` | compteur | flux coupés par la chute de l'instance |
  | `asr_failovers_total` | compteur | flux repris sur cette instance après une panne ailleurs |
  | `asr_streams_rejected_total{reason}` | compteur | flux refusés (`busy`, `unavailable`) |

  `docker compose --profile monitoring up` lance Prometheus (http://localhost:9090), configuré dans
  [monitoring/prometheus.yml](monitoring/prometheus.yml). Exemple p95 par instance :
  `histogram_quantile(0.95, sum by (le, instance) (rate(asr_first_result_seconds_bucket[5m])))`.
- **Observabilité** : `GET /api/v1/asr/instances` (temps réel), `GET /api/v1/asr/state/instances` et
  `GET /api/v1/asr/state/streams?active=true` (état sauvegardé : qui est sur quelle instance).

Le client envoie des chunks binaires PCM16 (16 kHz, mono) ; le serveur répond en JSON
`{"type": "partial"|"final", "text": "..."}`. Le message texte `end` termine le segment courant.

```bash
docker compose --profile cpu up --build             # instance(s) CPU
docker compose --profile gpu up --build             # instance(s) GPU (NVIDIA container toolkit)
docker compose --profile cpu --profile gpu up       # les deux : la gateway choisit
docker compose --profile cpu up --scale asr-cpu=3   # plusieurs instances
```

Le GGUF (~700 Mo)
est téléchargé une fois dans le volume `asr_models` ; les images sont construites depuis le
Dockerfile officiel de NVIDIA (`NEMO_SPEECH_REF` pour épingler une version). Les instances ASR
ne sont pas publiées sur l'hôte : seul le backend y accède.
