# tts_service

Serveur de **synthèse vocale** autonome (**Piper**, CPU), indépendant du backend, avec une API
**compatible OpenAI** : n'importe quel client qui sait appeler `POST /v1/audio/speech` d'OpenAI peut l'utiliser
en changeant seulement l'URL de base.

- Une ou plusieurs voix Piper par instance (`TTS_VOICES`). L'image **embarque** la voix `fr_FR-siwis-medium` :
  elle démarre sans réseau. D'autres voix peuvent être ajoutées au build ou téléchargées au démarrage (voir plus bas).
- Même esprit que `vosk_service` : routes de santé, métriques Prometheus, clé d'API facultative, aucune
  dépendance vers `backend/`.

> Piper (`piper-tts`) est sous licence **GPL-3.0**. Le service tourne dans son propre conteneur ; vérifiez que
> cette licence convient à votre diffusion de l'image.

## Routes

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/v1/audio/speech` | synthèse (compatible OpenAI) |
| GET | `/v1/models` | `tts-1` et `tts-1-hd` (même moteur) |
| GET | `/v1/audio/voices` | voix installées (extension, absente d'OpenAI) |
| GET | `/` | page de démonstration |
| GET | `/docs` | documentation Swagger |
| GET | `/health`, `/ready`, `/ready/capacity`, `/live`, `/version` | santé (`503` tant que les voix chargent) |
| GET | `/metrics` | métriques Prometheus |

### POST /v1/audio/speech

Corps JSON :

| Champ | Défaut | Description |
|---|---|---|
| `input` | requis | texte, 4096 caractères au plus (`TTS_MAX_INPUT_CHARS`) |
| `voice` | requis | nom d'une voix Piper (`fr_FR-siwis-medium`) **ou** un nom OpenAI (`alloy`, `echo`, `nova`...), réparti sur les voix installées |
| `model` | `tts-1` | accepté pour la compatibilité (`tts-1`, `tts-1-hd`) |
| `response_format` | `mp3` | `mp3`, `wav`, `flac` ou `pcm` (PCM16 mono brut). `opus` et `aac` sont refusés |
| `speed` | `1.0` | 0,25 à 4 |

Les autres champs OpenAI (`instructions`, `stream_format`...) sont ignorés. En `mp3` et `pcm`, l'audio est
envoyé **phrase par phrase pendant la synthèse** ; `wav` et `flac` sont envoyés d'un bloc (leur en-tête contient
la durée). L'en-tête de réponse `X-Voice` indique la voix réellement utilisée. Les erreurs ont la forme OpenAI
`{"error": {"message", "type"}}`.

```bash
curl http://localhost:8081/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model": "tts-1", "input": "Bonjour tout le monde.", "voice": "alloy"}' \
  --output bonjour.mp3
```

Avec le SDK OpenAI :

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8081/v1", api_key="inutile")
with client.audio.speech.with_streaming_response.create(
    model="tts-1", voice="alloy", input="Bonjour tout le monde."
) as response:
    response.stream_to_file("bonjour.mp3")
```

## Configuration

Variables `TTS_*` (voir [docs/environment.md](../docs/environment.md)) : `TTS_VOICES`, `TTS_VOICE_DIR`,
`TTS_VOICE_URL`, `TTS_MAX_REQUESTS`, `TTS_MAX_INPUT_CHARS`, `TTS_MP3_BITRATE`, `TTS_API_KEY`, `TTS_CORS_ORIGIN`,
`TTS_LOG_LEVEL`. Les voix disponibles sont listées dans la
[collection rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices).

Au-delà de `TTS_MAX_REQUESTS` synthèses simultanées (par défaut le nombre de CPU), le service répond `429`.

## Voix embarquées dans l'image

Le build télécharge les voix dans `/voices` ; l'image (environ 650 Mo) n'a alors besoin d'aucun accès réseau ni
d'aucun volume, et tourne avec un système de fichiers en lecture seule.

```bash
docker build -t tts-service tts_service                       # fr_FR-siwis-medium
docker build -t tts-service \
  --build-arg TTS_VOICES=fr_FR-siwis-medium,en_US-lessac-medium tts_service
docker build -t tts-service \
  --build-arg TTS_VOICE_URL=https://miroir.interne/piper-voices tts_service   # sans accès à huggingface.co
```

`TTS_VOICES` du runtime prend la valeur de l'argument de build. Pour ajouter une voix sans reconstruire, montez un
volume **inscriptible** sur `/voices` et fixez `TTS_VOICES` : elle est téléchargée au premier démarrage (avec
Docker, un volume nommé neuf est d'abord rempli avec les voix de l'image). Dans le chart Helm, aucun volume n'est
monté sur `/voices` par défaut, pour ne pas masquer les voix embarquées.

## Développement

```bash
uv sync --extra dev
uv run pytest                      # voix simulée, aucun téléchargement
TTS_TEST_VOICE_DIR=/chemin/voices uv run pytest tests/test_real_voice.py   # vraie voix Piper
uv run uvicorn app.main:create_app --factory --port 8081
```
