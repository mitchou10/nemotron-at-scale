"""FastAPI application: an OpenAI-compatible text-to-speech API, backed by Piper."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import Settings, get_settings
from app.engine import Engine
from app.errors import ApiError, error_body
from app.routes import service, speech
from app.state import ServerState

logger = logging.getLogger(__name__)


def _load_engine(settings: Settings) -> Engine:
    from app.piper_engine import PiperEngine

    return PiperEngine.load(settings)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    *,
    load_model: bool = True,
) -> FastAPI:
    """Build the app. `engine` is injected in tests; otherwise Piper loads in the background."""
    settings = settings or get_settings()
    state = ServerState(settings)
    state.engine = engine

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=settings.log_level.upper())
        loader: asyncio.Task[None] | None = None
        if state.engine is None and load_model:

            async def load() -> None:
                try:
                    state.engine = await asyncio.to_thread(_load_engine, settings)
                    logger.info("voices loaded: %s", [v.id for v in state.engine.voices])
                except Exception as exc:  # the server stays up and reports it on /ready
                    state.load_error = str(exc)
                    logger.exception("could not load the voices")

            loader = asyncio.create_task(load())
        yield
        if loader:
            loader.cancel()
        state.executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="tts-service", version=__version__, lifespan=lifespan)
    app.state.server = state

    if settings.cors_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.cors_origin],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.message, exc.error_type), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return JSONResponse(error_body(problems), status_code=400)

    app.include_router(service.router)
    app.include_router(speech.router)
    return app
