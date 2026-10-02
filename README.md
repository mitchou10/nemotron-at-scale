# nemotron-at-scale

Transcription de la parole **en direct**, à grande échelle. Un client envoie de l'audio sur un
WebSocket, le backend le route vers un serveur de reconnaissance vocale (ASR) et renvoie le texte au
fil de l'eau, en tenant compte de la charge, des pannes et des limites de chaque serveur.

```
                          ┌──────────────────────── backend (FastAPI) ────────────────────────┐
  client ── WebSocket ──▶ │  /api/v1/ws/audio/{id}                                            │
  (PCM16 16 kHz mono)     │    │                                                              │
        ◀── partial/final │    ▼   gateway : remplit les instances une par une (limite par    │
                          │        instance), sondes de latence, reprise si une instance      │
                          │        tombe (tampon audio rejoué), état en base, métriques       │
                          └────┬───────────────┬───────────────────┬───────────────────────────┘
                               │               │                   │        PostgreSQL (état)
                     ┌─────────▼───┐   ┌───────▼──────┐   ┌────────▼──────┐
                     │ asr-vosk ×N │   │ asr-cpu ×N   │   │ asr-gpu ×N    │   même protocole :
                     │ vosk_service│   │ nemo-speech  │   │ nemo-speech   │   /v1/audio/transcriptions/
                     │ (Kaldi, CPU)│   │ serve (CPU)  │   │ serve (GPU)   │   realtime
                     └─────────────┘   └──────────────┘   └───────────────┘
```

Les serveurs ASR sont des services **indépendants du backend**, dans leurs propres conteneurs. Ils
parlent tous le protocole de [`nemo-speech serve`](https://github.com/NVIDIA/NeMo-Speech.cpp) : la
gateway les traite de la même façon et on peut les mélanger.

## Contenu du dépôt

| Dossier / fichier | Rôle |
|---|---|
| [backend/](backend/README.md) | API FastAPI : WebSocket audio, gateway (routage, limites, reprise sur panne), état en base, métriques Prometheus, script de test de charge |
| [vosk_service/](vosk_service/README.md) | Serveur ASR **Vosk (Kaldi)** autonome, avec les mêmes routes que `nemo-speech serve` (fichier WAV, WebSocket temps réel, page de démonstration, métriques) |
| `docker-compose.yml` | Toute la stack, pilotée par des **profils** (voir plus bas) |
| `.env.example` | Configuration (à copier en `.env`) |

## Démarrage rapide

```bash
cp .env.example .env                       # adapte les ports si 5432 / 8000 sont déjà pris

docker compose --profile vosk up --build   # base + backend + Vosk (français léger)
```

Le premier démarrage télécharge le modèle Vosk (42 Mo) dans un volume. Ensuite :

- API et documentation Swagger du backend : <http://localhost:8000/api/v1/docs>
- État des instances ASR : <http://localhost:8000/api/v1/asr/instances>
- Métriques Prometheus : <http://localhost:8000/metrics>

### Profils du compose

| Profil | Service | Ce que ça lance |
|---|---|---|
| *(aucun)* | `db`, `backend` | PostgreSQL et le backend |
| `vosk` | `asr-vosk` | serveur Vosk (Kaldi), français léger par défaut, CPU |
| `cpu` | `asr-cpu` (+ `asr-model`) | Nemotron Speech Streaming 0.6B (anglais) sur CPU, via `nemo-speech serve` ; le modèle (~700 Mo) est téléchargé une fois |
| `gpu` | `asr-gpu` | Nemotron sur GPU (NVIDIA Container Toolkit). **Image jamais construite ni testée ici** |
| `monitoring` | `prometheus` | Prometheus sur <http://localhost:9090>, qui lit `/metrics` |
| `dev` | `backend-dev` | backend avec rechargement automatique |

Les profils se combinent (`--profile cpu --profile vosk`) et chaque service ASR se multiplie avec
`--scale asr-vosk=4` : la gateway découvre toutes les instances par DNS.

```bash
docker compose --profile vosk --profile monitoring up --build
docker compose --profile vosk up --scale asr-vosk=3
```

## Utiliser l'API

Connecte-toi en WebSocket sur `/api/v1/ws/audio/{client_id}` (l'identifiant sert à savoir qui est
connecté ; deux connexions avec le même id sont refusées) et envoie :

- des trames **binaires PCM 16 bits, 16 kHz, mono** ;
- le message texte `end` pour terminer le segment en cours et obtenir le texte final.

Le serveur répond en JSON : `{"type": "partial", "text": "..."}` au fil de la parole, puis
`{"type": "final", "text": "..."}`.

```python
import asyncio, json, wave
from websockets.asyncio.client import connect


async def main() -> None:
    audio = wave.open("audio.wav").readframes(10**9)  # WAV 16 kHz mono 16 bits
    async with connect("ws://localhost:8000/api/v1/ws/audio/moi") as ws:
        for i in range(0, len(audio), 3200):  # 100 ms par trame
            await ws.send(audio[i : i + 3200])
            await asyncio.sleep(0.1)
        await ws.send("end")
        while (message := json.loads(await ws.recv()))["type"] != "final":
            print(message["text"])
        print("final :", message["text"])


asyncio.run(main())
```

Codes de fermeture : `1011` si le service ASR est indisponible, `1013` si toutes les instances sont
pleines (réessayer plus tard).

## Comment la gateway répartit la charge

- **Remplissage** : un nouveau flux va à la première instance saine qui n'a pas atteint sa limite,
  dans l'ordre de `ASR_URL` ; la suivante n'est utilisée qu'une fois la précédente pleine. La limite se
  règle par instance dans l'URL (`ws://asr-vosk:8080/...#6`) ou par défaut avec
  `ASR_MAX_STREAMS_PER_INSTANCE`.
- **Panne en cours de flux** : l'audio du segment en cours est gardé en mémoire (30 s par flux par
  défaut, `ASR_BUFFER_SECONDS`). Si l'instance tombe, la gateway rejoue ce tampon sur une autre
  instance et la transcription continue.
- **État sauvegardé** en base : chaque instance (`up`, `down`, `draining`, `gone`) et chaque flux
  (client, instance, `running`, `ended`, `failed`...).
- **Métriques par instance** : latence des sondes, flux actifs, ouvertures, reprises, mémoire des
  tampons, etc. (voir [backend/README.md](backend/README.md)).

Tout est configurable dans `.env` (`ASR_URL`, `ASR_DISCOVERY`, `ASR_STATE_STORE`, `ASR_MAX_*`...).

## Choisir un moteur ASR

| | Vosk (`vosk_service`) | Nemotron (`nemo-speech serve`) |
|---|---|---|
| Langues | une langue par instance (français par défaut, `VOSK_MODEL_NAME`) | modèle anglais intégré |
| Précision | correcte, inférieure | meilleure |
| CPU | ~4 flux par cœur (modèle léger) | ~4 flux par instance CPU |
| Mémoire | ~0,15 Go + 70 Mo par flux | ~1 Go |
| GPU | non (variante GPU d'alphacep non intégrée) | oui (image à construire) |

Capacités mesurées sur une machine de 12 cœurs : voir [vosk_service/README.md](vosk_service/README.md)
(0,5 CPU : 2 flux, 1 CPU : 4, 2 CPU : 8, 4 CPU : 13) et [backend/README.md](backend/README.md).

## Mesurer la capacité d'une instance

```bash
cd backend
uv run python scripts/bench_asr.py nemo <ip>:8080 --find-capacity --container <nom-du-conteneur>
uv run python scripts/bench_asr.py gateway localhost:8000 -n 4,16      # tout le backend
```

Le script envoie N flux simultanés en temps réel et détaille les retards (p50 à max), les chunks en
retard, le CPU et la mémoire ; chaque colonne est expliquée dans [backend/README.md](backend/README.md).

## Développement et tests

```bash
cd backend      && uv run --extra dev pytest    # 138 tests, couverture 100 %
cd vosk_service && uv run --extra dev pytest    # 126 tests (sans modèle), couverture 100 %
uv run --extra dev ruff check . && uv run --extra dev ruff format --check .
```

Les tests n'ont besoin ni de Docker, ni de Postgres, ni de modèle : les serveurs ASR sont simulés.
Un test optionnel utilise un vrai modèle Vosk (`VOSK_TEST_MODEL_DIR`, voir `vosk_service/README.md`).

Raccourcis (`make help`) : `make install-hooks` (hooks git), `make check` (tous les hooks sur tous les
fichiers), `make lint`, `make test`, `make gitleaks` (recherche de secrets dans tout l'historique).

**Page de statut** (service `frontend`, nginx) : `http://localhost:3000` affiche l'état des workers ASR (disponibilité, latence, flux en
cours) sur la dernière heure, 24 heures ou 7 jours, avec le détail par instance. Les données viennent de
`GET /api/v1/asr/instances` (temps réel) et `GET /api/v1/asr/history` (historique). Voir
[frontend/README.md](frontend/README.md).

**Synthèse vocale (TTS)** : `tts_service` (Piper, CPU) expose une API **compatible OpenAI**
`POST /v1/audio/speech` (formats `mp3`, `wav`, `flac`, `pcm`, voix OpenAI ou Piper). Avec
`docker compose --profile tts up` et `TTS_ENABLED=true`, le backend la relaie sur `/api/v1/audio/speech` : un
client OpenAI n'a qu'à pointer `base_url` vers `http://localhost:8000/api/v1` (ou `http://localhost:8081/v1` pour
le service seul). Voir [tts_service/README.md](tts_service/README.md).

Les variables d'environnement sont décrites dans [docs/environment.md](docs/environment.md).

## CI/CD et releases

Les workflows réutilisables viennent de [Mitchou10/github-workflow](https://github.com/Mitchou10/github-workflow)
(épinglés sur `@v0`) ; seuls `unit-tests.yml` et la configuration des releases sont propres à ce dépôt.
Le dépôt `github-workflow` doit être public, ou autoriser ce dépôt (Settings > Actions > General > Access).

| Workflow | Déclencheur | Rôle |
|---|---|---|
| `ci.yml` | pull request | messages de commit (Conventional Commits), ruff, tests, recherche de secrets (gitleaks), scan de configuration (Trivy), build de chaque image modifiée (sans publication) ; les jobs sont filtrés par dossier modifié ; le job **Check jobs status** regroupe tout |
| `unit-tests.yml` | appelé par `ci.yml` | pytest sur `backend/` et `vosk_service/` |
| `cd.yml` | push sur `main` | release-please, puis build et publication des images sur GHCR et scan Trivy des images publiées (rapport seul) quand une release est créée |

**Chart Helm** : `helm/` (backend, vosk, tts et frontend), généré avec
[helm-template.sh](https://github.com/this-is-tobi/tools/blob/main/shell/helm-template.sh) de this-is-tobi.
Le secret `nemotron-database` (clé `url`, URL SQLAlchemy asyncpg) est à créer avant l'installation :
`helm install nemotron ./helm`. Le README du chart se régénère avec `helm-docs -c helm`.
À chaque release, `cd.yml` met à jour `appVersion` et `version` du chart (commit direct sur la branche), puis
publie le chart en OCI sur GHCR. `ci/configs/ct.yaml` configure le lint (chart-testing + helm-docs).

**GitLab (DSO)** : `.gitlab-ci-dso.yml` construit les deux images (Kaniko) et pousse le chart sur Harbor.
Variables à définir côté GitLab : `CATALOG_PATH`, `REGISTRY_HOST`, `PROJECT_PATH`, `DOCKER_AUTH`,
`IMAGE_REPOSITORY`, `DOCKERHUB_MIRROR_URL`.

**Flux de release** (release-please) : les commits suivent les
[Conventional Commits](https://www.conventionalcommits.org) (`feat:`, `fix:`, `perf:`, `refactor:`,
`docs:`, `test:`, `build:`, `ci:`, `chore:`, `revert:` ; `!` ou `BREAKING CHANGE:` pour une rupture). À chaque
push sur `main`, release-please ouvre ou met à jour une pull request **« chore(main): release X.Y.Z »**.
La fusionner crée le tag et la release GitHub, met à jour `CHANGELOG.md` et la version des deux
`pyproject.toml`, puis publie les images :

```
ghcr.io/mitchou10/nemotron-at-scale-backend:<version>        (+ :latest)
ghcr.io/mitchou10/nemotron-at-scale-vosk-service:<version>   (+ :latest)
ghcr.io/mitchou10/nemotron-at-scale-tts-service:<version>    (+ :latest)
ghcr.io/mitchou10/nemotron-at-scale-frontend:<version>       (+ :latest)
```

Configuration : `.github/releases/` (versions de départ dans les manifestes, sections du changelog).
Contrôles locaux avant de pousser : `make install-hooks` installe ruff, gitleaks et la vérification des
commits ; `.gitleaks.toml` et `.trivyignore.yaml` portent les exceptions (avec leur raison).

**Réglages GitHub à faire une fois** (Settings) :

- *Actions > General* : cocher « Read and write permissions » et **« Allow GitHub Actions to create and
  approve pull requests »**, sinon release-please ne peut pas ouvrir sa pull request ;
- *Branches* : protéger `main` et exiger le check **Check jobs status** ;
- *Packages* : rendre les images publiques si besoin (elles naissent privées).

**Pré-releases** : la branche `dev` existe toujours et publie des release candidates (`X.Y.Z-rc.N`) ;
`main` publie les versions stables. Après chaque release, `dev` est recréée depuis `main` si elle manque,
sinon rebasée dessus (job `sync-prerelease-branch`).

Sans GitHub App, la pull request de release ne relance pas la CI sur son propre commit : ajoute les
secrets `APP_CLIENT_ID` et `APP_PRIVATE_KEY` pour que ce soit le cas.

## Limites connues

- L'image **GPU** de Nemo n'a jamais été construite ni exécutée ici (pas de GPU) ; les images CPU
  sont construites sans les patches ggml de NVIDIA, qui ne s'appliquent pas via le contexte git de Docker.
- Le modèle multilingue **Nemotron 3.5** n'est pas branché : le client ne transmet pas encore la langue.
- Avec l'endpointing activé côté serveur, les textes finals automatiques ne vident pas le tampon de
  reprise : un rejeu après panne peut dupliquer du texte déjà finalisé (désactivé par défaut).
- Le backend garde un client `vosk://` pour un `vosk-server` brut (protocole d'alphacep) : il n'est
  plus nécessaire avec `vosk_service`.
- Le nombre de flux actifs est compté par processus backend : avec plusieurs backends, chacun voit sa
  propre charge.
