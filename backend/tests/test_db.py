"""Database session dependency tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app import db


def _patch_session(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(db, "AsyncSessionLocal", factory)
    return session


async def test_get_db_yields_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _patch_session(monkeypatch)
    gen = db.get_db()
    assert await anext(gen) is session
    with pytest.raises(StopAsyncIteration):
        await anext(gen)
    session.close.assert_awaited_once()
    session.rollback.assert_not_awaited()


async def test_get_db_rolls_back_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _patch_session(monkeypatch)
    gen = db.get_db()
    await anext(gen)
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("boom"))
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()
