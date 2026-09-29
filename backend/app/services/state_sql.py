"""Database-backed state store (PostgreSQL in production)."""

from collections.abc import Callable
from dataclasses import asdict

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asr import AsrInstance, AsrStream
from app.services.state import (
    ACTIVE_STREAM_STATUSES,
    InstanceState,
    InstanceStatus,
    StateStore,
    StreamState,
    StreamStatus,
    utcnow,
)

SessionFactory = Callable[[], AsyncSession]


class SqlStateStore(StateStore):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def save_instance(self, state: InstanceState) -> None:
        async with self._session_factory() as session:
            await session.merge(AsrInstance(**{**asdict(state), "status": str(state.status)}))
            await session.commit()

    async def save_stream(self, state: StreamState) -> None:
        async with self._session_factory() as session:
            await session.merge(AsrStream(**{**asdict(state), "status": str(state.status)}))
            await session.commit()

    async def list_instances(self) -> list[InstanceState]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(AsrInstance).order_by(AsrInstance.priority, AsrInstance.key)
                )
            ).all()
        return [
            InstanceState(
                key=r.key,
                url=r.url,
                status=InstanceStatus(r.status),
                priority=r.priority,
                max_streams=r.max_streams,
                active_streams=r.active_streams,
                latency_ms=r.latency_ms,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    async def list_streams(self, *, active_only: bool = False) -> list[StreamState]:
        query = select(AsrStream).order_by(AsrStream.started_at)
        if active_only:
            query = query.where(AsrStream.status.in_([str(s) for s in ACTIVE_STREAM_STATUSES]))
        async with self._session_factory() as session:
            rows = (await session.scalars(query)).all()
        return [
            StreamState(
                id=r.id,
                client_id=r.client_id,
                instance=r.instance,
                status=StreamStatus(r.status),
                failovers=r.failovers,
                started_at=r.started_at,
                updated_at=r.updated_at,
                ended_at=r.ended_at,
            )
            for r in rows
        ]

    async def interrupt_active_streams(self) -> int:
        now = utcnow()
        async with self._session_factory() as session:
            result = await session.execute(
                update(AsrStream)
                .where(AsrStream.status.in_([str(s) for s in ACTIVE_STREAM_STATUSES]))
                .values(status=str(StreamStatus.INTERRUPTED), ended_at=now, updated_at=now)
            )
            await session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]
