"""Output format tests."""

from app.formats import MAX_CUE_WORDS, Word, make_cues, srt, vtt


def words(*items: tuple[str, float, float]) -> list[Word]:
    return [Word(w, s, e, 1.0) for w, s, e in items]


def test_word_json() -> None:
    assert Word("a", 0.5, 1.0, 0.9).to_json() == {
        "word": "a",
        "start": 0.5,
        "end": 1.0,
        "confidence": 0.9,
    }


def test_words_are_grouped_in_one_cue() -> None:
    cues = make_cues(words(("bonjour", 0.0, 0.4), ("le", 0.5, 0.6), ("monde", 0.7, 1.2)))
    assert cues == [(0.0, 1.2, "bonjour le monde")]


def test_cue_split_on_word_count() -> None:
    many = words(*[(f"w{i}", i * 0.1, i * 0.1 + 0.05) for i in range(MAX_CUE_WORDS + 1)])
    assert [c[2].count(" ") + 1 for c in make_cues(many)] == [MAX_CUE_WORDS, 1]


def test_cue_split_on_duration() -> None:
    cues = make_cues(words(("a", 0.0, 1.0), ("b", 2.0, 3.0), ("c", 4.5, 5.5), ("d", 6.0, 7.0)))
    assert [c[2] for c in cues] == ["a b", "c d"]


def test_cue_split_on_pause() -> None:
    cues = make_cues(words(("a", 0.0, 0.5), ("b", 2.0, 2.5)))
    assert [c[2] for c in cues] == ["a", "b"]


def test_no_words_no_cues() -> None:
    assert make_cues([]) == []
    assert srt([]) == ""
    assert vtt([]) == "WEBVTT\n\n"


def test_srt_layout_and_timestamps() -> None:
    text = srt(words(("bonjour", 0.0, 0.4), ("monde", 3723.5, 3724.0)))
    assert text == (
        "1\n00:00:00,000 --> 00:00:00,400\nbonjour\n\n2\n01:02:03,500 --> 01:02:04,000\nmonde\n"
    )


def test_vtt_layout() -> None:
    text = vtt(words(("bonjour", 0.0, 0.4)))
    assert text == "WEBVTT\n\n00:00:00.000 --> 00:00:00.400\nbonjour\n"
