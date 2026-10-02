"""Database-backed registry (PostgreSQL in production), shared by every backend replica."""

from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asr import RegisteredWorker
from app.services.registry import RegisteredInstance, RegistryStore
from app.services.state import utcnow

SessionFactory = Callable[[], AsyncSession]


class SqlRegistryStore(RegistryStore):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def upsert(self, instance: RegisteredInstance) -> None:
        async with self._session_factory() as session:
            row = await session.get(RegisteredWorker, instance.id)
            if row is None:
                session.add(RegisteredWorker(**asdict(instance)))
            else:
                row.kind = instance.kind
                row.url = instance.url
                row.max_streams = instance.max_streams
                row.priority = instance.priority
                row.last_seen = instance.last_seen
            await session.commit()

    async def remove(self, instance_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(RegisteredWorker).where(RegisteredWorker.id == instance_id)
            )
            await session.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def list_alive(
        self, ttl_s: float, kinds: Sequence[str] | None = None
    ) -> list[RegisteredInstance]:
        query = (
            select(RegisteredWorker)
            .where(RegisteredWorker.last_seen >= utcnow() - timedelta(seconds=ttl_s))
            .order_by(RegisteredWorker.priority, RegisteredWorker.id)
        )
        if kinds is not None:
            query = query.where(RegisteredWorker.kind.in_(list(kinds)))
        async with self._session_factory() as session:
            rows = (await session.scalars(query)).all()
        return [
            RegisteredInstance(
                id=r.id,
                kind=r.kind,
                url=r.url,
                max_streams=r.max_streams,
                priority=r.priority,
                registered_at=r.registered_at,
                last_seen=r.last_seen,
            )
            for r in rows
        ]

    async def prune(self, ttl_s: float) -> int:
        limit = utcnow() - timedelta(seconds=ttl_s)
        async with self._session_factory() as session:
            result = await session.execute(
                delete(RegisteredWorker).where(RegisteredWorker.last_seen < limit)
            )
            await session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]
