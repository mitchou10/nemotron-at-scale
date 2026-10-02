"""Registry routes: worker instances register, send heartbeats and unregister here."""

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from pydantic import BaseModel, Field, model_validator

from app.config import settings
from app.services.registry import KINDS, RegisteredInstance, RegistryStore

router = APIRouter(tags=["registry"])

SCHEMES = {"nemo": ("ws", "wss"), "vosk": ("ws", "wss"), "tts": ("http", "https")}


async def require_registry_token(request: Request) -> None:
    """With REGISTRY_TOKEN set, only holders of the token may read or change the registry."""
    expected = settings.REGISTRY_TOKEN
    if not expected:
        return
    header = request.headers.get("authorization", "")
    provided = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not secrets.compare_digest(expected, provided):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing registry token")


class Registration(BaseModel):
    kind: Literal["nemo", "vosk", "tts"]
    # The address the instance announces for itself: the realtime WebSocket URL of a transcription
    # server (ws://host:8080/v1/audio/transcriptions/realtime), the base URL of a TTS server.
    url: str = Field(max_length=512)
    max_streams: int = Field(ge=1, le=100_000)  # streams (STT) or concurrent requests (TTS)
    priority: int = Field(default=0, ge=0, le=1000)  # fill order: lower first

    @model_validator(mode="after")
    def _check_url(self) -> "Registration":
        parts = urlsplit(self.url)
        if parts.scheme not in SCHEMES[self.kind] or not parts.hostname:
            expected = " or ".join(f"{s}://" for s in SCHEMES[self.kind])
            raise ValueError(f"`url` of a {self.kind} instance must start with {expected}")
        return self


def get_registry(request: Request) -> RegistryStore:
    return request.app.state.registry  # type: ignore[no-any-return]


Registry = Annotated[RegistryStore, Depends(get_registry)]
InstanceId = Annotated[str, Path(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._:-]+$")]


@router.put("/registry/instances/{instance_id}", dependencies=[Depends(require_registry_token)])
async def register(
    instance_id: InstanceId, body: Registration, registry: Registry
) -> dict[str, Any]:
    """Register an instance, or refresh its heartbeat: the same call does both.

    Call it again before `ttl_s` runs out (every `ttl_s / 3` is a good rhythm). An instance that
    stops calling is removed from the routing once the TTL has passed.
    """
    await registry.upsert(RegisteredInstance(instance_id, **body.model_dump()))
    return {"id": instance_id, "ttl_s": settings.REGISTRY_TTL_S}


@router.delete(
    "/registry/instances/{instance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_registry_token)],
)
async def unregister(instance_id: InstanceId, registry: Registry) -> Response:
    """Unregister at once (clean shutdown). Unknown ids are not an error."""
    await registry.remove(instance_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/registry/instances", dependencies=[Depends(require_registry_token)])
async def list_instances(registry: Registry, kind: str | None = None) -> list[dict[str, Any]]:
    """Registered instances whose heartbeat is younger than the TTL."""
    if kind is not None and kind not in KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"kind must be one of {', '.join(KINDS)}")
    now = datetime.now(UTC)
    alive = await registry.list_alive(settings.REGISTRY_TTL_S, kinds=(kind,) if kind else None)
    return [
        {
            "id": i.id,
            "kind": i.kind,
            "url": i.url,
            "max_streams": i.max_streams,
            "priority": i.priority,
            "registered_at": i.registered_at.isoformat(),
            "last_seen": i.last_seen.isoformat(),
            "age_s": round((now - i.last_seen).total_seconds(), 1),
        }
        for i in alive
    ]
