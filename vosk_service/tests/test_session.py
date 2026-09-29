"""RealtimeSession tests (protocol logic, independent of FastAPI)."""

import pytest

from app.metrics import Metrics
from app.session import COMPLETED, DELTA, InvalidRequestError, RealtimeSession
from tests.conftest import END, FakeEngine

CHUNK = b"\x01\x00" * 160


def make(*, endpointing: bool = False, limit: float = 3600) -> tuple[RealtimeSession, FakeEngine]:
    engine = FakeEngine()
    return RealtimeSession(engine, Metrics(4), endpointing=endpointing, max_seconds=limit), engine


def types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def test_created_describes_the_model() -> None:
    session, _ = make()
    created = session.created()
    assert created["type"] == "session.created"
    assert created["session"] == {
        "sample_rate": 16000,
        "model": "vosk-model-small-fr-0.22",
        "language": "fr",
    }
    assert created["event_id"].startswith("event_")


def test_event_ids_are_unique() -> None:
    session, _ = make()
    ids = {session.created()["event_id"] for _ in range(5)}
    assert len(ids) == 5


def test_deltas_carry_only_the_new_text() -> None:
    session, _ = make()
    first = session.feed(CHUNK)
    second = session.feed(CHUNK)
    assert [(e["type"], e["delta"]) for e in first + second] == [
        (DELTA, "bonjour"),
        (DELTA, " tout"),
    ]


def test_audio_processed_grows_with_the_audio() -> None:
    session, _ = make()
    [first] = session.feed(CHUNK)
    [second] = session.feed(CHUNK)
    assert first["audio_processed"] == pytest.approx(0.01)
    assert second["audio_processed"] == pytest.approx(0.02)


def test_unchanged_text_gives_no_event_and_empty_chunk_is_ignored() -> None:
    session, engine = make()
    assert session.feed(b"") == []
    session.feed(CHUNK)
    recognizer = engine.created[0]
    recognizer.partial_result = lambda: {"partial": "bonjour"}  # type: ignore[method-assign]
    assert session.feed(CHUNK) == []


def test_revised_partial_is_sent_in_full() -> None:
    session, engine = make()
    session.feed(CHUNK)
    recognizer = engine.created[0]
    recognizer.partial_result = lambda: {"partial": "bonsoir tout le monde"}  # type: ignore[method-assign]
    [event] = session.feed(CHUNK)
    assert event["delta"] == "bonsoir tout le monde"


def test_vanished_partial_gives_no_event() -> None:
    session, engine = make()
    session.feed(CHUNK)
    engine.created[0].partial_result = lambda: {"partial": ""}  # type: ignore[method-assign]
    assert session.feed(CHUNK) == []


def test_commit_completes_and_starts_over() -> None:
    session, engine = make()
    session.feed(CHUNK)
    session.feed(CHUNK)
    events = session.commit()
    assert types(events) == [COMPLETED, "input_audio_buffer.committed"]
    assert events[0]["transcript"] == "bonjour tout"
    assert "words" not in events[0]
    session.feed(CHUNK)
    assert len(engine.created) == 2  # a fresh recognizer after the commit


def test_commit_without_audio_only_commits() -> None:
    session, _ = make()
    assert types(session.commit()) == ["input_audio_buffer.committed"]


def test_commit_of_silence_has_no_completed_event() -> None:
    session, engine = make()
    session.feed(END)  # the fake returns an empty result
    assert types(session.commit()) == ["input_audio_buffer.committed"]
    assert len(engine.created) == 1


def test_clear_drops_the_audio() -> None:
    session, engine = make()
    session.feed(CHUNK)
    assert types(session.clear()) == ["input_audio_buffer.cleared"]
    assert types(session.commit()) == ["input_audio_buffer.committed"]
    session.feed(CHUNK)
    assert len(engine.created) == 2


def test_utterance_end_without_endpointing_only_accumulates() -> None:
    session, _ = make(endpointing=False)
    session.feed(CHUNK)
    session.feed(CHUNK)
    events = session.feed(END)
    assert events == []  # the text is unchanged: both words are now finalized
    [next_delta] = session.feed(CHUNK)
    assert next_delta["delta"] == " le"  # the following utterance continues the text
    completed = session.commit()[0]
    assert completed["transcript"] == "bonjour tout le"


def test_endpointing_emits_completed_at_each_utterance_end() -> None:
    session, _ = make(endpointing=True)
    session.feed(CHUNK)
    session.feed(CHUNK)
    events = session.feed(END)
    assert types(events) == [COMPLETED]
    assert events[0]["transcript"] == "bonjour tout"
    [delta] = session.feed(CHUNK)
    assert delta["delta"] == "le"  # the text restarts after a completed utterance
    assert session.commit()[0]["transcript"] == "le"


def test_endpointing_on_silence_emits_nothing() -> None:
    session, _ = make(endpointing=True)
    assert session.feed(END) == []


def test_words_are_returned_when_requested() -> None:
    session, engine = make()
    session.update({"word_timestamps": True})
    session.feed(CHUNK)
    session.feed(CHUNK)
    completed = session.commit()[0]
    assert engine.created[0].words is True
    assert completed["words"] == [
        {"word": "bonjour", "start": 0.0, "end": 0.3, "confidence": 0.9},
        {"word": "tout", "start": 0.3, "end": 0.6, "confidence": 0.9},
    ]


def test_session_update_sets_rate_and_endpointing() -> None:
    session, engine = make()
    updated = session.update({"sample_rate": 8000, "endpointing_ms": 500, "language": "fr"})
    assert updated["type"] == "session.updated"
    assert updated["session"]["sample_rate"] == 8000
    session.feed(CHUNK)
    assert engine.created[0].rate == 8000
    session.feed(CHUNK)
    assert types(session.feed(END)) == [COMPLETED]  # endpointing_ms > 0 turned it on


def test_endpointing_ms_zero_turns_it_off() -> None:
    session, _ = make(endpointing=True)
    session.update({"endpointing_ms": 0})
    session.feed(CHUNK)
    assert session.feed(END) == []


@pytest.mark.parametrize("rate", [4000, 96001, "fast", None])
def test_session_update_rejects_bad_sample_rate(rate: object) -> None:
    session, _ = make()
    with pytest.raises(InvalidRequestError, match="sample_rate"):
        session.update({"sample_rate": rate})


def test_session_update_is_rejected_once_audio_started() -> None:
    session, _ = make()
    session.feed(CHUNK)
    with pytest.raises(InvalidRequestError, match="once audio has started"):
        session.update({"sample_rate": 8000})


def test_session_update_is_allowed_again_after_a_commit() -> None:
    session, _ = make()
    session.feed(CHUNK)
    session.commit()
    session.update({"sample_rate": 8000})


def test_stream_duration_limit() -> None:
    chunk_seconds = len(CHUNK) / (16_000 * 2)
    session, _ = make(limit=chunk_seconds * 2.5)
    session.feed(CHUNK)
    session.feed(CHUNK)
    with pytest.raises(InvalidRequestError, match="maximum duration of 0.025 seconds"):
        session.feed(CHUNK)


def test_duration_limit_follows_the_sample_rate() -> None:
    session, _ = make(limit=1.0)
    session.update({"sample_rate": 8000})
    session.feed(b"\x01\x00" * 8000)  # exactly one second at 8 kHz
    with pytest.raises(InvalidRequestError, match="maximum duration"):
        session.feed(b"\x01\x00")


def test_metrics_record_decoding() -> None:
    engine = FakeEngine()
    metrics = Metrics(4)
    session = RealtimeSession(engine, metrics, endpointing=False, max_seconds=3600)
    session.feed(CHUNK)
    session.feed(CHUNK)
    registry = metrics.registry
    assert registry.get_sample_value("vosk_chunk_seconds_count") == 2
    assert registry.get_sample_value("vosk_audio_seconds_total") == pytest.approx(0.02)
