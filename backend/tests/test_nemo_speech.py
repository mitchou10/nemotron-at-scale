"""Tests of the nemo-speech client against a fake server speaking its realtime protocol."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import pytest
from websockets.asyncio.server import ServerConnection, serve

from app.services.nemo_speech import DELTA, NemoSpeechTranscriber
from app.services.transcription import TranscriberUnavailableError, TranscriptEvent

Handler = Callable[[ServerConnection], Awaitable[None]]


@asynccontextmanager
async def fake_server(handler: Handler) -> AsyncIterator[str]:
    async with serve(handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


async def happy_handler(ws: ServerConnection) -> None:
    await ws.send(json.dumps({"type": "session.created"}))
    async for message in ws:
        if isinstance(message, bytes):
            await ws.send(json.dumps({"type": DELTA, "delta": "hel"}))
            await ws.send(json.dumps({"type": DELTA, "delta": "lo"}))
        elif json.loads(message)["type"] == "input_audio_buffer.commit":
            await ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.input_audio_transcription.completed",
                        "transcript": "Hello.",
                    }
                )
            )
            await ws.send(json.dumps({"type": "input_audio_buffer.committed"}))
            await ws.close()


async def test_partials_accumulate_then_final() -> None:
    async with fake_server(happy_handler) as url:
        session = await NemoSpeechTranscriber(url).open_session()
        await session.send_audio(b"\x00\x00")
        await session.end()
        events = [e async for e in session.events()]
        await session.close()
    assert events == [
        TranscriptEvent("partial", "hel"),
        TranscriptEvent("partial", "hello"),
        TranscriptEvent("final", "Hello."),
        TranscriptEvent("committed", ""),
    ]


async def test_errors_and_empty_finals_are_skipped() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.send(json.dumps({"type": "error", "error": {"message": "bad"}}))
        await ws.send(json.dumps({"type": "x.completed", "transcript": ""}))
        await ws.send(
            json.dumps(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "transcript": "",
                }
            )
        )
        await ws.close()

    async with fake_server(handler) as url:
        session = await NemoSpeechTranscriber(url).open_session()
        assert [e async for e in session.events()] == []
        await session.close()


async def test_api_key_sent_as_bearer_header() -> None:
    seen: list[str | None] = []

    async def handler(ws: ServerConnection) -> None:
        seen.append(ws.request.headers.get("Authorization") if ws.request else None)
        await ws.close()

    async with fake_server(handler) as url:
        session = await NemoSpeechTranscriber(url, api_key="secret").open_session()
        await session.close()
    assert seen == ["Bearer secret"]


async def test_unreachable_server_raises() -> None:
    with pytest.raises(TranscriberUnavailableError):
        await NemoSpeechTranscriber("ws://127.0.0.1:1").open_session()


async def test_dropped_connection_raises_on_send_and_end() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.close()

    async with fake_server(handler) as url:
        session = await NemoSpeechTranscriber(url).open_session()
        async for _ in session.events():
            pass
        with pytest.raises(TranscriberUnavailableError):
            await session.send_audio(b"\x00\x00")
        with pytest.raises(TranscriberUnavailableError):
            await session.end()


async def test_events_raise_when_connection_breaks() -> None:
    async def handler(ws: ServerConnection) -> None:
        ws.transport.abort()

    async with fake_server(handler) as url:
        session = await NemoSpeechTranscriber(url).open_session()
        with pytest.raises(TranscriberUnavailableError):
            async for _ in session.events():
                pass
