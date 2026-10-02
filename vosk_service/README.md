# vosk_service

Serveur de transcription **Vosk (Kaldi)** autonome, indépendant du backend. Il expose les mêmes
routes que `nemo-speech serve` (NeMo-Speech.cpp) : n'importe quel client ou gateway qui sait parler à
Nemo peut donc l'utiliser sans changement (`ws://asr-vosk:8080/v1/audio/transcriptions/realtime`).

- Un modèle Vosk par instance (une langue par instance : français, anglais...).
- Le modèle est téléchargé au premier démarrage dans `VOSK_MODEL_DIR` (volume Docker `/models`).
- Aucune dépendance vers le dossier `backend/`.

## Enregistrement dans le backend

Avec `VOSK_REGISTRY_URL` (et `VOSK_REGISTRY_TOKEN`), le serveur s'**enregistre** auprès du backend une fois le
modèle chargé (`PUT /api/v1/registry/instances/<id>`), envoie un heartbeat toutes les 10 s et se désenregistre à
l'arrêt ; mort, il est retiré après le TTL du backend (30 s). Il annonce `VOSK_SELF_URL` (par défaut l'IP du
conteneur), sa limite de flux et `VOSK_REGISTRY_PRIORITY`. Sans `VOSK_REGISTRY_URL`, rien n'est envoyé. Voir
[docs/environment.md](../docs/environment.md).

## Routes

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/` | page de démonstration : fichier WAV et microphone en direct |
| GET | `/docs` | documentation Swagger (la route WebSocket y est décrite, voir plus bas) |
| GET | `/health` | état compact (`503` tant que le modèle n'est pas chargé) |
| GET | `/ready` | prêt ou non, modèle, langue, flux actifs et limite |
| GET | `/ready/capacity` | comme `/ready`, mais `503` aussi quand l'instance est pleine (pour un répartiteur de charge) |
| GET | `/live` | liveness : répond même si le modèle est en cours de chargement |
| GET | `/version` | version du service |
| GET | `/v1/models` | modèle chargé (format OpenAI) |
| POST | `/v1/audio/transcriptions` | transcription d'un fichier WAV (compatible OpenAI) |
| WS | `/v1/audio/transcriptions/realtime` | transcription en direct (alias : `/v1/realtime`, `/realtime`) |
| GET | `/metrics` | métriques Prometheus |

### POST /v1/audio/transcriptions

Formulaire multipart : `file` (WAV PCM16 ou float32, 8 à 96 kHz, mono ou multicanal), `model` et
`language` (acceptés pour la compatibilité), `response_format` = `json` (défaut), `verbose_json`
(mots avec `start`, `end`, `confidence`), `text`, `srt` ou `vtt`.

```bash
curl -X POST http://localhost:8080/v1/audio/transcriptions \
  -F "file=@audio.wav" -F "response_format=verbose_json"
```

Erreurs : `{"error": {"message": "...", "type": "invalid_request_error" | "server_error"}}`.

### WebSocket temps réel

La route est décrite dans Swagger (`/docs`) sous « Live transcription (WebSocket) » : Swagger ne sait
pas afficher les WebSockets, elle y figure donc comme une opération `GET` qui répond `426 Upgrade
Required` en HTTP simple, avec le protocole complet dans sa description. Connecte-toi en `ws://`.

Le serveur envoie `session.created` à la connexion. Le client envoie ensuite (optionnel, avant l'audio)
`{"type": "session.update", "session": {"sample_rate": 16000, "word_timestamps": false,
"endpointing_ms": 0}}`, puis des trames binaires PCM16 little-endian mono (ou
`input_audio_buffer.append` avec `audio` en base64), et termine par `input_audio_buffer.commit`.
`input_audio_buffer.clear` (ou `response.cancel`) jette l'audio en cours.

Événements du serveur :

- `conversation.item.input_audio_transcription.delta` : `delta` = texte ajouté depuis le partiel
  précédent (le texte complet si le partiel a été corrigé), plus `audio_processed` en secondes ;
- `conversation.item.input_audio_transcription.completed` : `transcript` final (et `words` avec
  `word_timestamps`) ;
- `input_audio_buffer.committed`, `input_audio_buffer.cleared`, `session.updated` ;
- `error` : `{"error": {"message", "type"}}`.

Par défaut (comme nemo-speech) le texte final n'est émis qu'au `commit`. Avec `VOSK_ENDPOINTING=true`
(ou `endpointing_ms > 0` dans `session.update`), un `completed` est aussi émis à chaque fin de phrase
détectée par Vosk. Quand le serveur est plein (`VOSK_MAX_STREAMS`), la connexion reçoit une erreur
puis est fermée avec le code 1013.

## Configuration (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `VOSK_MODEL_NAME` | `vosk-model-small-fr-0.22` | modèle à charger (voir [les modèles Vosk](https://alphacephei.com/vosk/models)) |
| `VOSK_MODEL_DIR` | `/models` | dossier des modèles ; le modèle y est téléchargé s'il manque |
| `VOSK_MODEL_URL` | `https://alphacephei.com/vosk/models/{name}.zip` | source du téléchargement |
| `VOSK_MAX_STREAMS` | voir « Limites » | flux temps réel simultanés |
| `VOSK_STREAMS_PER_CPU` | `1.0` | flux par CPU quand `VOSK_MAX_STREAMS` n'est pas fixé |
| `VOSK_THREADS` | CPU du conteneur | threads de décodage |
| `VOSK_ENDPOINTING` | `false` | `completed` à chaque fin de phrase détectée |
| `VOSK_API_KEY` | aucune | exige `Authorization: Bearer <clé>` sur `/v1` (WebSocket : `?api_key=`) |
| `VOSK_CORS_ORIGIN` | aucune | origine navigateur autorisée |
| `VOSK_HOST` / `VOSK_PORT` | `0.0.0.0` / `8080` | écoute |

Modèles courants : `vosk-model-small-fr-0.22` (42 Mo, léger), `vosk-model-fr-0.22` (1,4 Go, plus
précis), `vosk-model-small-en-us-0.15`, `vosk-model-en-us-0.22`. Vosk n'a pas de modèle multilingue
unique : pour plusieurs langues, lance une instance par langue.

## Limites

Le service se borne lui-même : il lit la **limite CPU du conteneur** (cgroup, par exemple `cpus` sous
Docker) et non le nombre de cœurs de l'hôte, puis en déduit ses limites. Changer la limite CPU du
conteneur suffit donc à changer sa capacité.

| Limite | Variable | Défaut |
|---|---|---|
| flux temps réel simultanés | `VOSK_MAX_STREAMS`, sinon `VOSK_STREAMS_PER_CPU` × CPU | 1 flux par CPU |
| threads de décodage | `VOSK_THREADS` | nombre de CPU (au moins 1) |
| transcriptions de fichiers simultanées | `VOSK_MAX_REQUESTS` (au-delà : `429`) | = threads |
| taille d'un fichier | `VOSK_MAX_UPLOAD_MB` (au-delà : `413`) | 64 |
| durée d'un flux | `VOSK_MAX_STREAM_SECONDS` | 3600 |
| flux inactif (aucune donnée) | `VOSK_IDLE_TIMEOUT_S`, 0 = jamais | 120 (libère les places des clients disparus) |
| taille d'une trame WebSocket | option `--ws-max-size` d'uvicorn (Dockerfile) | 1 Mio |

Sondes : `/live` répond tant que le processus tourne, `/ready` indique que le modèle est chargé, et
`/ready/capacity` répond `503` tant que le modèle charge **ou quand l'instance est pleine** (utile pour
sortir une instance pleine d'un répartiteur de charge).

Capacité mesurée (modèle français léger, machine de 12 cœurs, flux de parole en temps réel,
avec `backend/scripts/bench_asr.py`) :

| limite CPU du conteneur | flux max tenables (mesure sans marge) | avec `VOSK_STREAMS_PER_CPU=3` | retard du final (p95) | premier texte (p95) | mémoire |
|---|---|---|---|---|---|
| 0,5 | 2 | - | 0,3 s | 2,4 s | - |
| 1 | 4 | 3 flux | 0,22 s | 1,5 s | 0,3 Go |
| 2 | 8 | 6 flux | 0,25 s | 1,8 s | 0,5 Go |
| 4 | 13 | 12 flux | 0,34 s | 2,0 s | 0,9 Go |
| 12 (sans limite) | 32 | - | 0,6 s | 2,9 s | 2,3 Go |

Le minimum est donc **0,5 CPU pour 2 flux**, et environ **4 flux par CPU** à la limite. Prévois
`VOSK_STREAMS_PER_CPU=3` pour garder de la marge ; la mémoire vaut environ 0,15 Go + 70 Mo par flux avec
ce modèle (un modèle plus gros ajoute sa propre taille). Refais la mesure pour ton modèle et ta
machine. Avec le backend, la limite par instance se règle dans l'URL :
`VOSK_MAX_STREAMS`.

## Lancer

```bash
# Docker (depuis la racine du dépôt, voir docker-compose.yml)
docker compose --profile vosk up --build     # profil compose "vosk"

# En local
cd vosk_service
uv sync --extra dev
VOSK_MODEL_DIR=./models uv run uvicorn app.main:create_app --factory --port 8080
```

## Métriques (`/metrics`)

`vosk_active_streams`, `vosk_max_streams`, `vosk_streams_total`, `vosk_streams_rejected_total`,
`vosk_chunk_seconds` (temps de décodage de chaque chunk audio : au-delà de la durée du chunk,
les flux prennent du retard), `vosk_audio_seconds_total`,
`vosk_transcription_requests_total{status}` et les métriques du process (`process_*`).

## Capacité

Mesure la capacité de ton instance avec le script du backend, qui parle le protocole nemo :
`cd backend && uv run python scripts/bench_asr.py nemo <ip>:8080 --find-capacity`
(voir `backend/README.md` pour lire les résultats).

## Tests

```bash
cd vosk_service
uv run --extra dev pytest        # moteur simulé, sans modèle
VOSK_TEST_MODEL_DIR=./models uv run --extra dev pytest tests/test_real_model.py   # avec un vrai modèle
```
