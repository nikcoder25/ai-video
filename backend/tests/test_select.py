"""Selection is the product, and snapping is what keeps it watchable.

These tests care about one promise above all: a clip never starts or ends
mid-sentence, whatever the model proposed.
"""

from __future__ import annotations

from conftest import make_transcript

from pipeline.select import (
    LEAD_IN,
    TAIL,
    _windows,
    build_user_prompt,
    format_transcript_for_model,
    snap_to_speech,
    validate_candidates,
)
from pipeline.text import is_sentence_end


def _sentence_start_times(words) -> set[float]:
    times = {round(words[0].start, 3)}
    for i, w in enumerate(words[:-1]):
        if is_sentence_end(w):
            times.add(round(words[i + 1].start, 3))
    return times


def _sentence_end_times(words) -> set[float]:
    return {round(w.end, 3) for w in words if is_sentence_end(w)}


class TestSnapToSpeech:
    def test_lands_on_sentence_boundaries(self, sample_transcript):
        words = sample_transcript.words
        result = snap_to_speech(6.4, 31.7, words, min_sec=20, max_sec=58)

        assert result is not None
        start, end = result
        assert round(start + LEAD_IN, 3) in _sentence_start_times(words)
        assert round(end - TAIL, 3) in _sentence_end_times(words)

    def test_respects_duration_limits(self, sample_transcript):
        result = snap_to_speech(3.0, 300.0, sample_transcript.words, min_sec=20, max_sec=58)

        assert result is not None
        start, end = result
        assert 20 <= (end - start) <= 58

    def test_returns_none_when_nothing_fits(self):
        # Three seconds of speech cannot yield a twenty second clip.
        transcript = make_transcript("Short thing here. Another one.", per_word=0.3)
        assert snap_to_speech(0.0, 2.0, transcript.words, min_sec=20, max_sec=58) is None

    def test_empty_words_is_none(self):
        assert snap_to_speech(0.0, 30.0, [], min_sec=20, max_sec=58) is None

    def test_start_never_negative(self, sample_transcript):
        result = snap_to_speech(0.0, 25.0, sample_transcript.words, min_sec=20, max_sec=58)
        assert result is not None
        assert result[0] >= 0.0

    def test_falls_back_to_clauses_without_sentences(self):
        # No terminal punctuation anywhere -- snapping must still find an edge.
        text = " ".join(f"word{i}," for i in range(200))
        transcript = make_transcript(text, per_word=0.3)
        result = snap_to_speech(5.0, 30.0, transcript.words, min_sec=20, max_sec=58)

        assert result is not None
        assert 20 <= (result[1] - result[0]) <= 58


class TestValidateCandidates:
    def _raw(self, **overrides):
        base = {
            "start": 4.0,
            "end": 30.0,
            "hook_score": 8,
            "title": "A title",
            "reason": "A reason",
        }
        base.update(overrides)
        return base

    def test_keeps_a_good_candidate(self, sample_transcript):
        out = validate_candidates([self._raw()], sample_transcript, min_sec=20, max_sec=58)
        assert len(out) == 1
        assert out[0].title == "A title"
        assert 20 <= out[0].duration <= 58

    def test_drops_malformed(self, sample_transcript):
        raw = [
            {"start": "x", "end": 30, "hook_score": 8, "title": "t", "reason": "r"},
            {"end": 30, "hook_score": 8, "title": "t", "reason": "r"},
            self._raw(end=2.0),  # end before start once snapped
            self._raw(title=""),
        ]
        assert validate_candidates(raw, sample_transcript, min_sec=20, max_sec=58) == []

    def test_clamps_out_of_range_score(self, sample_transcript):
        out = validate_candidates(
            [self._raw(hook_score=47)], sample_transcript, min_sec=20, max_sec=58
        )
        assert out[0].hook_score == 10

    def test_deduplicates_overlapping_picks(self, sample_transcript):
        raw = [
            self._raw(start=4.0, end=30.0, hook_score=6, title="worse"),
            self._raw(start=5.0, end=31.0, hook_score=9, title="better"),
        ]
        out = validate_candidates(raw, sample_transcript, min_sec=20, max_sec=58)

        assert len(out) == 1
        assert out[0].title == "better"

    def test_keeps_distinct_moments(self, sample_transcript):
        raw = [
            self._raw(start=2.0, end=25.0, title="first"),
            self._raw(start=90.0, end=115.0, title="second"),
        ]
        out = validate_candidates(raw, sample_transcript, min_sec=20, max_sec=58)

        assert [c.title for c in out] == ["first", "second"]

    def test_output_is_sorted_by_start(self, sample_transcript):
        raw = [
            self._raw(start=90.0, end=115.0, title="later", hook_score=9),
            self._raw(start=2.0, end=25.0, title="earlier", hook_score=5),
        ]
        out = validate_candidates(raw, sample_transcript, min_sec=20, max_sec=58)
        assert [c.start for c in out] == sorted(c.start for c in out)

    def test_never_exceeds_transcript_duration(self, sample_transcript):
        end_over = sample_transcript.duration + 40
        raw = [self._raw(start=sample_transcript.duration - 30, end=end_over)]
        out = validate_candidates(raw, sample_transcript, min_sec=20, max_sec=58)
        for cand in out:
            assert cand.end <= sample_transcript.duration


class TestPromptBuilding:
    def test_one_line_per_sentence_with_times(self):
        transcript = make_transcript("First thing here. Second thing here.", per_word=0.4)
        lines = format_transcript_for_model(transcript.words).splitlines()

        assert len(lines) == 2
        assert lines[0].startswith("[0.0-")
        assert lines[0].endswith("First thing here.")

    def test_empty_transcript(self):
        assert format_transcript_for_model([]) == ""

    def test_prompt_carries_the_constraints(self, sample_transcript):
        prompt = build_user_prompt(
            sample_transcript.words,
            target_count=9,
            min_sec=20,
            max_sec=58,
            window_start=0,
            window_end=100,
        )
        assert "9 best clip candidates" in prompt
        assert "between 20 and 58 seconds" in prompt
        assert "<transcript>" in prompt


class TestWindowing:
    def test_short_media_is_one_window(self):
        assert _windows(600.0) == [(0.0, 600.0)]

    def test_long_media_splits_with_overlap(self):
        windows = _windows(7200.0)

        assert len(windows) > 1
        assert windows[0][0] == 0.0
        assert windows[-1][1] == 7200.0
        # Consecutive windows must overlap so a moment on a seam is still seen whole.
        for earlier, later in zip(windows, windows[1:], strict=False):
            assert later[0] < earlier[1]


class TestWindowBounds:
    """A windowed request must only yield clips from inside that window.

    Each window sees only its slice of transcript but is told the absolute
    times. If the model answers relative to the slice, the number is still a
    valid timestamp elsewhere in the source -- it snaps cleanly and renders the
    wrong moment with no error anywhere.
    """

    def test_keeps_candidates_inside_the_window(self):
        from pipeline.select import _within_window

        clips = [{"start": 2500.0, "end": 2540.0}]
        assert _within_window(clips, 2400.0, 4800.0) == clips

    def test_drops_a_window_relative_answer(self):
        from pipeline.select import _within_window

        # "120" meaning two minutes into this section, not into the source.
        clips = [{"start": 120.0, "end": 160.0}]
        assert _within_window(clips, 2400.0, 4800.0) == []

    def test_drops_a_candidate_running_past_the_window_end(self):
        from pipeline.select import _within_window

        assert _within_window([{"start": 4700.0, "end": 5200.0}], 2400.0, 4800.0) == []

    def test_tolerates_rounding_at_the_edges(self):
        from pipeline.select import _within_window

        clips = [{"start": 2399.0, "end": 4801.0}]
        assert _within_window(clips, 2400.0, 4800.0) == clips

    def test_passes_malformed_entries_through_to_validation(self):
        # Dropping them here would lose the "dropping malformed candidate" log.
        from pipeline.select import _within_window

        clips = [{"start": "abc"}]
        assert _within_window(clips, 0.0, 100.0) == clips
