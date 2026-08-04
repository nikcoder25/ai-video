"""Shared fixtures.

Environment is set before anything imports the app, because ``models`` builds
its engine at import time and would otherwise grab the real database.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="clipviral-tests-"))
os.environ["MOCK"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["STORAGE_DIR"] = str(_TMP / "clips")
os.environ["WORK_DIR"] = str(_TMP / "work")

import pytest  # noqa: E402

from schemas import Transcript, Word  # noqa: E402


def make_words(text: str, *, start: float = 0.0, per_word: float = 0.4) -> list[Word]:
    """Build evenly-spaced words from a sentence, keeping punctuation attached."""
    tokens = text.split()
    words: list[Word] = []
    t = start
    for token in tokens:
        words.append(Word(word=token, start=round(t, 3), end=round(t + per_word * 0.9, 3)))
        t += per_word
    return words


def make_transcript(text: str, *, per_word: float = 0.4) -> Transcript:
    words = make_words(text, per_word=per_word)
    return Transcript(words=words, duration=words[-1].end if words else 0.0)


@pytest.fixture
def tmp_root() -> Path:
    return _TMP


@pytest.fixture
def sample_transcript() -> Transcript:
    # 60 short sentences, ~1.6s each, so clip-length constraints are reachable.
    sentences = " ".join(
        f"This is sentence number {i} and it carries a complete thought." for i in range(60)
    )
    return make_transcript(sentences, per_word=0.35)
