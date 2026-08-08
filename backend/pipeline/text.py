"""Small text helpers shared by selection and captioning.

Kept out of ``select.py`` so that module stays purely about *which* moments to
pick, per the CLAUDE.md rule.
"""

from __future__ import annotations

from schemas import Word

SENTENCE_ENDINGS = (".", "!", "?", "…")
# A trailing comma or dash is a breath, not a boundary -- useful for captions,
# not strong enough to end a clip on.
CLAUSE_ENDINGS = (",", ";", ":", "—", "–")


def _tail(word: str) -> str:
    stripped = word.rstrip("\"')]}»")
    return stripped[-1:] if stripped else ""


def is_sentence_end(word: Word | str) -> bool:
    text = word if isinstance(word, str) else word.word
    return _tail(text) in SENTENCE_ENDINGS


def is_clause_end(word: Word | str) -> bool:
    text = word if isinstance(word, str) else word.word
    return _tail(text) in CLAUSE_ENDINGS


def sentence_end_indices(words: list[Word]) -> list[int]:
    """Indices of words that terminate a sentence."""
    return [i for i, w in enumerate(words) if is_sentence_end(w)]


def sentence_start_indices(words: list[Word]) -> list[int]:
    """Indices of words that begin a sentence (index 0, and after any ending)."""
    if not words:
        return []
    starts = [0]
    for i in sentence_end_indices(words):
        if i + 1 < len(words):
            starts.append(i + 1)
    return starts


def format_timestamp(seconds: float) -> str:
    """Seconds → ``m:ss`` (or ``h:mm:ss``). Display only, never stored."""
    seconds = max(0.0, seconds)
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
