# syntax=docker/dockerfile:1.7

# ---- Builder stage ----
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# Dependencies first (cached layer)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY app ./app
RUN uv sync --frozen --no-dev

# ---- Runtime stage ----
FROM python:3.12-slim AS runtime

RUN groupadd -r appuser && useradd -r -m -g appuser appuser \
    && mkdir -p /voices && chown appuser:appuser /voices

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TTS_VOICE_DIR=/voices

USER appuser

EXPOSE 8080

# /ready answers 503 until the voices are loaded (first start may download them)
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready')"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", \
     "--timeout-graceful-shutdown", "30"]
