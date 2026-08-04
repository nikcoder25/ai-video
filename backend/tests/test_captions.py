from __future__ import annotations

from conftest import make_words

from pipeline.captions import GOLD, _ass_time, _escape, build_ass, group_words
from schemas import Word


class TestAssTime:
    def test_zero(self):
        assert _ass_time(0.0) == "0:00:00.00"

    def test_centisecond_resolution(self):
        assert _ass_time(61.5) == "0:01:01.50"
        assert _ass_time(1.239) == "0:00:01.24"

    def test_hours(self):
        assert _ass_time(3661.0) == "1:01:01.00"

    def test_negative_clamps_to_zero(self):
        assert _ass_time(-5.0) == "0:00:00.00"


class TestGrouping:
    def test_caps_at_three_words(self):
        words = make_words("one two three four five six seven eight nine")
        for line in group_words(words):
            assert len(line) <= 3

    def test_breaks_on_sentence_end(self):
        words = make_words("Stop here. Now continue on")
        lines = group_words(words)

        assert [w.word for w in lines[0]] == ["Stop", "here."]

    def test_breaks_on_a_long_pause(self):
        words = [
            Word(word="before", start=0.0, end=0.4),
            Word(word="after", start=3.0, end=3.4),
        ]
        assert len(group_words(words)) == 2

    def test_every_word_survives_grouping(self):
        words = make_words("Alpha bravo charlie. Delta echo, foxtrot golf hotel india.")
        grouped = [w for line in group_words(words) for w in line]
        assert [w.word for w in grouped] == [w.word for w in words]

    def test_no_empty_lines(self):
        words = make_words("Alpha bravo charlie delta echo foxtrot.")
        assert all(len(line) > 0 for line in group_words(words))


class TestEscaping:
    def test_braces_cannot_inject_markup(self):
        assert _escape("{\\an8}hack") == "(/an8)hack"

    def test_plain_text_untouched(self):
        assert _escape("hello") == "hello"


class TestBuildAss:
    def test_has_a_usable_header(self):
        doc = build_ass(make_words("Hello there friend."), width=1080, height=1920)

        assert "[Script Info]" in doc
        assert "PlayResX: 1080" in doc
        assert "PlayResY: 1920" in doc
        assert "Style: Caption," in doc
        assert "[Events]" in doc

    def test_one_event_per_word(self):
        words = make_words("one two three four five six")
        doc = build_ass(words)

        assert doc.count("Dialogue:") == len(words)

    def test_active_word_is_gold(self):
        doc = build_ass(make_words("alpha bravo charlie"))
        assert GOLD in doc

    def test_times_are_relative_to_clip_start(self):
        words = make_words("late words here now", start=100.0)
        doc = build_ass(words, clip_start=100.0)

        first = next(line for line in doc.splitlines() if line.startswith("Dialogue:"))
        # Field 2 is the start time; at clip-relative zero it must not read 1:40.
        assert first.split(",")[1] == "0:00:00.00"

    def test_no_event_starts_before_zero(self):
        words = make_words("alpha bravo charlie delta", start=10.0)
        doc = build_ass(words, clip_start=10.5)

        for line in doc.splitlines():
            if line.startswith("Dialogue:"):
                assert not line.split(",")[1].startswith("-")

    def test_events_have_positive_duration(self):
        doc = build_ass(make_words("alpha bravo charlie delta echo"))

        for line in doc.splitlines():
            if not line.startswith("Dialogue:"):
                continue
            _, start, end, *_ = line.split(",")
            assert end > start

    def test_empty_words_still_valid(self):
        doc = build_ass([])
        assert "[Events]" in doc
        assert doc.count("Dialogue:") == 0
