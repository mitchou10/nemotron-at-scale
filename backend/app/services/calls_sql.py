"""Database-backed log of the text-to-speech requests."""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asr import TtsCall
from app.services.calls import TtsCallRecord, TtsCallStore

SessionFactory = Callable[[], AsyncSession]

COLUMNS = (
    "status_code",
    "instance",
    "voice",
    "response_format",
    "characters",
    "audio_bytes",
    "duration_ms",
    "first_byte_ms",
    "at",
)


class SqlTtsCallStore(TtsCallStore):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, call: TtsCallRecord) -> None:
        async with self._session_factory() as session:
            session.add(TtsCall(**{name: getattr(call, name) for name in COLUMNS}))
            await session.commit()

    async def list_since(
        self, since: datetime, *, limit: int | None = None, status_class: str | None = None
    ) -> list[TtsCallRecord]:
        query = (
            select(TtsCall)
            .where(TtsCall.at >= since)
            .order_by(TtsCall.at.desc(), TtsCall.id.desc())
        )
        if status_class == "ok":
            query = query.where(TtsCall.status_code < 400)
        elif status_class == "client_error":
            query = query.where(TtsCall.status_code >= 400, TtsCall.status_code < 500)
        elif status_class == "error":
            query = query.where(TtsCall.status_code >= 500)
        if limit:
            query = query.limit(limit)
        async with self._session_factory() as session:
            rows = (await session.scalars(query)).all()
        return [
            TtsCallRecord(**{name: getattr(r, name) for name in COLUMNS}, id=r.id) for r in rows
        ]

    async def prune(self, before: datetime) -> int:
        async with self._session_factory() as session:
            result = await session.execute(delete(TtsCall).where(TtsCall.at < before))
            await session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]
