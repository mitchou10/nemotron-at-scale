# syntax=docker/dockerfile:1.7

# ---- Dependencies (cached layer) ----
FROM python:3.12-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# ---- Voices: baked into the image, so it starts without network access ----
# Comma-separated Piper voices (e.g. --build-arg TTS_VOICES=fr_FR-siwis-medium,en_US-lessac-medium);
# TTS_VOICE_URL points to a mirror when huggingface.co is not reachable from the build.
FROM deps AS voices

ARG TTS_VOICES=fr_FR-siwis-medium
ARG TTS_VOICE_URL=https://huggingface.co/rhasspy/piper-voices/resolve/main

# Only the code that downloads: a change elsewhere in app/ must not download the voices again.
COPY app/__init__.py app/config.py app/voices.py ./app/
RUN TTS_VOICES="$TTS_VOICES" TTS_VOICE_URL="$TTS_VOICE_URL" TTS_VOICE_DIR=/voices \
    /app/.venv/bin/python -m app.voices

# ---- Builder stage ----
FROM deps AS builder

COPY app ./app
RUN uv sync --frozen --no-dev

# ---- Runtime stage ----
FROM python:3.12-slim AS runtime

RUN groupadd -r appuser && useradd -r -m -g appuser appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app /app
COPY --from=voices --chown=appuser:appuser /voices /voices

# The same list as the build argument: these voices are loaded at start (change both together, or
# mount a volume on /voices to download others on first start).
ARG TTS_VOICES=fr_FR-siwis-medium
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TTS_VOICE_DIR=/voices \
    TTS_VOICES=${TTS_VOICES}

USER appuser

EXPOSE 8080

# /ready answers 503 until the voices are loaded
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready')"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", \
     "--timeout-graceful-shutdown", "30"]
