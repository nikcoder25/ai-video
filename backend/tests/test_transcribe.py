"""Deepgram response parsing.

The HTTP call itself cannot be tested without a key, so these exercise
``parse_deepgram`` against the payload shape nova-2 actually returns for
``punctuate=true&diarize=true&smart_format=true``, plus the degenerate shapes
a real API will occasionally hand back.
"""

from __future__ import annotations

import pytest

from pipeline.transcribe import mock_transcript, parse_deepgram


def payload(words: list[dict], *, duration: float = 12.5) -> dict:
    return {
        "metadata": {"request_id": "abc", "duration": duration, "channels": 1},
        "results": {
            "channels": [
                {"alternatives": [{"transcript": "...", "confidence": 0.99, "words": words}]}
            ]
        },
    }


WORD = {
    "word": "everyone",
    "start": 0.08,
    "end": 0.39,
    "confidence": 0.99,
    "speaker": 0,
    "speaker_confidence": 0.87,
    "punctuated_word": "Everyone",
}


class TestParseDeepgram:
    def test_reads_word_timings_and_speaker(self):
        t = parse_deepgram(payload([WORD]))

        assert len(t.words) == 1
        w = t.words[0]
        assert (w.start, w.end, w.speaker) == (0.08, 0.39, 0)
        assert t.duration == 12.5

    def test_prefers_the_punctuated_form(self):
        # Line breaking and clip-boundary detection both depend on punctuation,
        # so the punctuated variant must win over the bare token.
        t = parse_deepgram(payload([{**WORD, "word": "sleep", "punctuated_word": "sleep."}]))
        assert t.words[0].word == "sleep."

    def test_falls_back_when_punctuation_is_absent(self):
        raw = {k: v for k, v in WORD.items() if k != "punctuated_word"}
        assert parse_deepgram(payload([raw])).words[0].word == "everyone"

    def test_missing_speaker_is_none_not_zero(self):
        # Without diarize the key is absent; defaulting to 0 would invent a
        # speaker that never existed.
        raw = {k: v for k, v in WORD.items() if k != "speaker"}
        assert parse_deepgram(payload([raw])).words[0].speaker is None

    def test_skips_empty_tokens(self):
        t = parse_deepgram(payload([WORD, {**WORD, "word": "", "punctuated_word": ""}]))
        assert len(t.words) == 1

    def test_derives_duration_when_metadata_omits_it(self):
        body = payload([WORD])
        body["metadata"].pop("duration")
        assert parse_deepgram(body).duration == pytest.approx(0.39)

    def test_empty_word_list_is_an_empty_transcript(self):
        t = parse_deepgram(payload([]))
        assert t.words == []
        assert t.duration == 12.5

    def test_only_the_first_channel_is_read(self):
        body = payload([WORD])
        body["results"]["channels"].append(
            {"alternatives": [{"words": [{**WORD, "word": "other"}]}]}
        )
        assert [w.word for w in parse_deepgram(body).words] == ["Everyone"]

    def test_missing_channels_raises_clearly(self):
        with pytest.raises(ValueError, match="channels"):
            parse_deepgram({"results": {"channels": []}})

    def test_missing_alternatives_raises_clearly(self):
        with pytest.raises(ValueError, match="alternatives"):
            parse_deepgram({"results": {"channels": [{"alternatives": []}]}})

    def test_garbage_payload_raises_rather_than_returning_empty(self):
        # Silently returning nothing would look like "no speech found".
        with pytest.raises(ValueError):
            parse_deepgram({})


class TestMockTranscript:
    def test_is_ordered_and_non_overlapping(self):
        words = mock_transcript().words

        assert len(words) > 50
        for a, b in zip(words, words[1:], strict=False):
            assert a.end <= b.start
            assert a.start < a.end

    def test_carries_sentence_punctuation(self):
        # Selection and captioning both key off terminal punctuation, so the
        # fixture is useless without it.
        assert any(w.word.endswith(".") for w in mock_transcript().words)
