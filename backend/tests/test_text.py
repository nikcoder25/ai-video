from __future__ import annotations

from conftest import make_words

from pipeline.text import (
    format_timestamp,
    is_clause_end,
    is_sentence_end,
    sentence_end_indices,
    sentence_start_indices,
)


class TestSentenceDetection:
    def test_terminal_punctuation(self):
        assert is_sentence_end("done.")
        assert is_sentence_end("really?")
        assert is_sentence_end("stop!")

    def test_plain_word_is_not_an_ending(self):
        assert not is_sentence_end("running")

    def test_looks_past_a_closing_quote(self):
        assert is_sentence_end('"finished."')

    def test_clause_endings_are_separate(self):
        assert is_clause_end("however,")
        assert not is_clause_end("however")
        assert not is_sentence_end("however,")


class TestIndices:
    def test_end_indices(self):
        words = make_words("one two. three four. five")
        assert sentence_end_indices(words) == [1, 3]

    def test_start_indices_include_the_first_word(self):
        words = make_words("one two. three four. five")
        assert sentence_start_indices(words) == [0, 2, 4]

    def test_empty(self):
        assert sentence_end_indices([]) == []
        assert sentence_start_indices([]) == []


class TestTimestampFormatting:
    def test_under_an_hour(self):
        assert format_timestamp(0) == "0:00"
        assert format_timestamp(65) == "1:05"

    def test_over_an_hour(self):
        assert format_timestamp(3725) == "1:02:05"

    def test_negative_clamps(self):
        assert format_timestamp(-10) == "0:00"
