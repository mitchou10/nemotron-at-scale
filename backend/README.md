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
│       ├── vosk.py           # Client d'un serveur Vosk (Kaldi)
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
├── .gitignore
├── alembic.ini
├── Dockerfile             # Production (multi-stage)
├── Dockerfile.dev         # Dev avec reload
├── pyproject.toml
└── README.md
```

## Démarrage

### Avec Docker (recommandé)

Le `docker-compose.yml` et le `.env.example` sont à la **racine du dépôt** ; tout se lance depuis là :

```bash
# Copier la config (variables lues par le compose et par le backend)
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

Deux types de serveurs ASR, chacun dans ses propres conteneurs (services compose séparés) :
[`nemo-speech serve`](https://github.com/NVIDIA/NeMo-Speech.cpp) (Nemotron) et
[Vosk](https://github.com/alphacep/vosk-server) (Kaldi, plus léger, CPU). La gateway les traite de la
même façon et peut les mélanger. Nemo :
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
  | `asr_buffer_bytes` | gauge | octets audio gardés en mémoire pour la reprise, par instance qui sert les flux |
  | `asr_buffer_limit_bytes` | gauge | plafond du tampon par flux (`ASR_BUFFER_SECONDS` × 32 000) |
  | `process_resident_memory_bytes` (et `process_*`) | gauge | mémoire réelle du process backend (Linux) |

  Borne haute de la mémoire du tampon : `somme des limites d'instances × asr_buffer_limit_bytes`
  (≈ 1 Mo par flux au plafond de 30 s).

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
docker compose --profile vosk up                    # instance(s) Vosk (Kaldi)
docker compose --profile cpu --profile vosk up      # mélange : la gateway remplit dans l'ordre de ASR_URL
docker compose --profile vosk up --scale asr-vosk=4 # plusieurs instances Vosk
docker compose --profile cpu up --scale asr-cpu=3   # plusieurs instances
```

Le GGUF (~700 Mo)
est téléchargé une fois dans le volume `asr_models` ; les images sont construites depuis le
Dockerfile officiel de NVIDIA (`NEMO_SPEECH_REF` pour épingler une version). Les instances ASR
ne sont pas publiées sur l'hôte : seul le backend y accède.

**Vosk** ([vosk.py](app/services/vosk.py)) : service `asr-vosk` (image `alphacep/kaldi-en`, ~6 Go, le
modèle est dedans ; `VOSK_IMAGE` choisit la langue, ex. `alphacep/kaldi-fr`). Dans `ASR_URL`, une
instance Vosk s'écrit `vosk://asr-vosk:2700` (limite par instance avec `#N`, comme pour Nemo) ; la
santé est testée par une poignée de main WebSocket (Vosk n'a pas de route `/ready`). Le message
`end` envoie `eof` : Vosk renvoie le résultat final et ferme la connexion, la gateway se reconnecte
au prochain audio. Vosk découpe les phrases lui-même : après chaque phrase finalisée, le tampon de
reprise est réduit à ~500 ms. Précision inférieure à Nemotron, mais bien moins gourmand.

**Combien de flux par instance ?** Cela dépend de la machine : mesure-le avec
[scripts/bench_asr.py](scripts/bench_asr.py), qui envoie N flux simultanés en temps réel (un extrait
audio est fourni) et donne, par N, le délai avant le premier texte et le retard du `final` après la
fin de l'audio :

```bash
cd backend
uv run python scripts/bench_asr.py vosk 172.21.0.5:2700 -n 1,8,16,32   # une instance Vosk
uv run python scripts/bench_asr.py nemo 172.21.0.4:8080 -n 1,4,8,16    # une instance Nemo
uv run python scripts/bench_asr.py gateway localhost:8000 -n 4,16      # tout le backend
```

Une instance suit le temps réel tant que `final_lag` reste autour de 1 s ; au-delà elle prend du
retard, et il faut régler `ASR_MAX_STREAMS_PER_INSTANCE` (ou le `#N` de l'URL) en dessous de ce seuil.
Mesures sur une machine 12 cœurs partagée (extrait de 11 s, 1 instance) :

| serveur | flux | premier texte | retard du final | remarque |
|---|---|---|---|---|
| Vosk (CPU) | 8 | 1,2 s | 1,1 s | ~175 % CPU |
| Vosk (CPU) | 16 | 1,2 s | 1,5–2,3 s | limite raisonnable (~370 % CPU) |
| Vosk (CPU) | 32 | 1,9 s | 5–6 s | en retard sur le temps réel |
| Nemo (CPU) | 4 | 1,0 s | 0,5 s | ~300 % CPU, tient le temps réel |
| Nemo (CPU) | 8 | 1,0 s | > 2 s | en retard sur le temps réel |
| Nemo (CPU) | 16 et + | - | - | surcharge : coupures (keepalive) |

Sur CPU, compte donc environ **4 flux par instance Nemo** et **8 à 16 par instance Vosk**. Un GPU en
tiendra beaucoup plus (non mesuré ici : refais la mesure sur ta machine).

Deux plafonds durs côté serveur Nemo, indépendants de la charge : un thread par flux (4 par défaut,
relevé à 32 par `ASR_HTTP_THREADS` dans le compose) et `asr.batching.state_arena_slots` (16 par
défaut : au-delà, les nouveaux flux sont rejetés ; réglable avec la variable d'environnement
`NEMO_SPEECH_ASR_BATCHING_STATE_ARENA_SLOTS`). Le calcul neuronal est sérialisé côté serveur, d'où
un usage CPU d'environ 3 à 4 cœurs quel que soit le nombre de flux.

**Modèles chargés par instance : un seul.** Une instance Nemo (un processus `nemo-speech serve`)
charge son modèle une fois (~1 Go de RAM au repos) et tous ses flux le partagent, avec un petit état
par flux (~5 Mo). Une instance Vosk charge un modèle (~5 Go de RAM pour l'anglais) et chaque flux ajoute
un reconnaisseur léger (~13 Mo mesurés). Pour un autre modèle ou une autre langue avec Vosk, il faut
une autre instance (`VOSK_IMAGE=alphacep/kaldi-fr`) ; le modèle multilingue de Nemo couvre plusieurs
langues dans une seule instance.

Les images Nemo sont construites avec `ENABLE_GGML_PATCHES=OFF` (ggml standard) : avec le contexte git
distant de Docker, les patches ggml de NVIDIA ne s'appliquent pas (« does NOT apply cleanly »).
Les kernels optimisés des patches ne sont donc pas utilisés (surtout sensible sur GPU).

Les ports hôte sont configurables (`DB_PORT`, `BACKEND_PORT`, `PROMETHEUS_PORT` dans `.env`) si
5432, 8000 ou 9090 sont déjà pris.
