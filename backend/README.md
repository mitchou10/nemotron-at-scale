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
| POST    | `/api/v1/audio/speech`   | Synthèse vocale compatible OpenAI (relais vers `tts_service`, `TTS_ENABLED=true`) |
| GET     | `/api/v1/audio/voices`   | Voix installées sur le service TTS |
| GET     | `/api/v1/asr/history?hours=24&buckets=90` | Disponibilité, latence et charge de chaque instance par tranche de temps, et totaux de flux |
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
  | `asr_chunk_latency_seconds` | histogramme | Vosk : retard de la réponse à chaque chunk audio (au-delà de ~0,1 s, l'instance est en retard) |
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

**Vosk** : service séparé et indépendant du backend, dans [vosk_service/](../vosk_service/README.md).
Il expose les mêmes routes que `nemo-speech serve` (`/health`, `/ready`, `/v1/models`,
`POST /v1/audio/transcriptions`, WebSocket `/v1/audio/transcriptions/realtime`, page de démonstration
sur `/`, `/metrics`) ; la gateway l'utilise donc comme une instance Nemo, avec une simple URL
`ws://asr-vosk:8080/v1/audio/transcriptions/realtime` dans `ASR_URL`. Profil compose `vosk`,
modèle et langue choisis par `VOSK_MODEL_NAME` (français léger par défaut), plusieurs instances avec
`--scale asr-vosk=N`. Le modèle est téléchargé au premier démarrage dans le volume `vosk_models`.
Vosk n'a pas de modèle multilingue : une instance par langue. Précision inférieure à Nemotron, mais
bien moins gourmand.

Le client `vosk://` du backend ([vosk.py](app/services/vosk.py)) reste disponible pour un serveur
`vosk-server` brut (protocole natif d'alphacep) ; avec `vosk_service` il n'est plus nécessaire.

**Combien de flux par instance, et avec quel retard ?** Cela dépend de la machine : le script
[scripts/bench_asr.py](scripts/bench_asr.py) le mesure. Il envoie N flux simultanés en temps réel (un
extrait audio est fourni) et détaille, pour chaque N : le délai avant le premier texte
(`first_result`), le retard du `final` après la fin de l'audio (`final_lag`), et pour Vosk le retard de
**chaque chunk** audio (`chunk_latency`, avec la part de chunks en retard) ainsi que le pic de CPU et de
mémoire du conteneur. Les percentiles p50/p90/p95/p99/max sont donnés.

```bash
cd backend
# chercher automatiquement la capacité (double N jusqu'à l'échec, puis dichotomie)
uv run python scripts/bench_asr.py vosk 172.21.0.5:2700 --find-capacity --container nemotron-asr-vosk-2
# ou des valeurs de N choisies
uv run python scripts/bench_asr.py vosk 172.21.0.5:2700 -n 1,8,16,32 --json vosk.json
uv run python scripts/bench_asr.py nemo 172.21.0.4:8080 -n 1,4,8
uv run python scripts/bench_asr.py gateway localhost:8000 -n 4,16      # tout le backend
```

Un N est « tenable » s'il n'y a aucune erreur, si le p95 de `final_lag` reste ≤ `--max-lag` (2 s) et si
les chunks en retard restent ≤ `--max-late` (5 %). Le résultat de `--find-capacity` est la valeur à
mettre comme limite de l'instance (`#N` dans `ASR_URL`). En production, le même retard par chunk est
visible en continu dans Prometheus : `asr_chunk_latency_seconds{instance}` (Vosk).

Mesure réelle d'une instance Vosk (CPU, machine de 12 cœurs, extrait de 11 s, chunks de 100 ms) :

| flux | premier texte (p95) | retard du final (p95) | retard par chunk (p95 / p99) | chunks en retard | CPU pic |
|---|---|---|---|---|---|
| 1 | 1,15 s | 0,45 s | 37 / 42 ms | 0 % | 16 % |
| 4 | 1,17 s | 0,73 s | 48 / 83 ms | 0,9 % | 277 % |
| 8 | 1,18 s | 1,09 s | 69 / 134 ms | 2,0 % | 642 % |
| 10 | 1,18 s | 1,30 s | 96 / 202 ms | 4,7 % | 829 % |
| 11 | 1,19 s | 1,42 s | 98 / 225 ms | 5,0 % | 856 % |
| 12 | 1,20 s | 1,55 s | 121 / 243 ms | 6,7 % (trop) | 896 % |
| 16 | 1,23 s | 2,22 s | 151 / 372 ms | 11,8 % (trop) | 1028 % |

**Comment lire chaque colonne**

Le script affiche, pour chaque N, un bloc détaillé puis un tableau récapitulatif final. Chaque flux de
test envoie l'extrait audio en temps réel (un chunk de 100 ms toutes les 100 ms) ; les valeurs sont
donc mesurées sur des flux qui se comportent comme de vrais clients.

*Les percentiles.* Les valeurs sont regroupées sur tous les flux (ou tous les chunks) du test :
**p50** est la valeur médiane (la moitié est plus rapide), **p90 / p95 / p99** sont les valeurs que 90 %,
95 % et 99 % des mesures ne dépassent pas, **max** est la pire mesure. Le p95 ou le p99 comptent plus
que la moyenne : ce sont eux qui font ressentir des à-coups à l'utilisateur.

| colonne (nom dans le script) | ce que c'est | comment l'interpréter |
|---|---|---|
| `N` / « flux » | nombre de flux audio envoyés **en même temps** à l'instance. | C'est la variable testée : on l'augmente jusqu'à trouver la limite. |
| `ok` | flux terminés sans erreur (connexion coupée, timeout, rejet). | Doit valoir N. Moins que N = l'instance a rejeté ou perdu des flux (par exemple les plafonds durs de Nemo). |
| `first_p95` / « premier texte » | délai entre l'envoi du **premier** chunk audio et la réception du **premier** texte (partiel ou final), au p95. | Le temps « avant que quelque chose s'affiche ». Il inclut le temps de parole nécessaire au modèle pour reconnaître un premier mot (~1 s ici), donc il ne tombe jamais à 0. S'il grimpe avec N, l'instance est chargée dès le démarrage des flux. |
| `lag_p50` / `lag_p95` / `lag_max` / « retard du final » | délai entre la **fin de l'audio** (dernier chunk + demande de fin) et la réception du texte **final**. | Le retard de fond : tant que l'instance suit le temps réel, il reste faible (0,5 s avec 1 flux). Il augmente quand le serveur accumule du retard, car il doit rattraper l'audio en attente avant de finaliser. C'est le critère principal (`--max-lag`, 2 s par défaut). |
| `chunk_p95` / `chunk_p99` / « retard par chunk » | (Vosk) délai entre l'envoi d'**un** chunk audio et la réponse du serveur à ce chunk, mesuré pour chaque chunk de chaque flux. | Le signal de charge le plus fin : Vosk répond exactement une fois par chunk. Quand la valeur reste sous 100 ms, le serveur traite l'audio plus vite qu'il n'arrive. Quand elle dépasse 100 ms, le serveur prend du retard sur le temps réel. Le p99 montre les pires à-coups. |
| `late` / « chunks en retard » | (Vosk) part des chunks dont la réponse a mis plus longtemps que la durée d'un chunk (100 ms). | Mesure « à quelle fréquence » l'instance est en retard. 0 à 2 % = confortable ; au-delà de 5 % (`--max-late`) l'instance est jugée saturée. |
| `cpu%` / « CPU pic » | pic d'utilisation CPU du conteneur pendant le test (`docker stats`, option `--container`). 100 % = un cœur complet. | Montre la ressource qui limite : ici ~1 cœur par flux, la saturation arrive quand les 12 cœurs (1200 %) sont presque pleins et partagés avec le reste de la machine. |
| `mem` | pic de mémoire du conteneur (`--container`). | Quasi constant : le modèle est chargé une fois (~5,9 Go pour Vosk anglais) et chaque flux ajoute peu (~13 Mo). La mémoire ne limite pas le nombre de flux ; le CPU, si. |
| `wall` | durée réelle du test pour ce N. | Une valeur proche de la durée de l'audio (11 s) signifie que les flux ont tenu le rythme ; une valeur bien plus grande signale un gros retard accumulé. |
| verdict (`sustainable` / `PAST CAPACITY`) | conclusion pour ce N selon les seuils `--max-lag` et `--max-late`, avec la raison du dépassement. | `sustainable` = N flux peuvent tourner ensemble ; `PAST CAPACITY` = N est au-delà de la capacité. |

**Capacité trouvée : 11 flux** pour cette instance sur cette machine. Vosk utilise tous les cœurs
disponibles (~1 cœur par flux) : la capacité dépend donc surtout du nombre de cœurs et de ce qui tourne
d'autre. Repère pour Nemo CPU (~4 flux) :

| serveur | flux | retard du final | remarque |
|---|---|---|---|
| Nemo (CPU) | 4 | 0,5 s | ~300 % CPU, tient le temps réel |
| Nemo (CPU) | 8 | > 2 s | en retard sur le temps réel |
| Nemo (CPU) | 16 et + | - | surcharge : coupures (keepalive) |

Sur CPU, compte donc environ **4 flux par instance Nemo** et **~10 par instance Vosk**. Un GPU en
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
