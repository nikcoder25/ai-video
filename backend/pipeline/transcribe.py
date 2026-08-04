"""Stage 2: audio → word-level transcript via Deepgram nova-2.

Returns word timings, which everything downstream depends on: selection reads
them to find sentence boundaries, captions read them for per-word sync.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import httpx

from config import get_settings
from schemas import Transcript, Word

from ._fixtures import MOCK_SPEECH

log = logging.getLogger("clipviral.transcribe")

ProgressFn = Callable[[float], None]

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

# punctuate=true is load-bearing: captions.py breaks lines on punctuation and
# select.py uses sentence endings to avoid cutting mid-thought.
DEEPGRAM_PARAMS = {
    "model": "nova-2",
    "punctuate": "true",
    "smart_format": "true",
    "diarize": "true",
    "filler_words": "false",
}


def transcribe(
    audio_path: str | Path,
    *,
    on_progress: ProgressFn | None = None,
) -> Transcript:
    settings = get_settings()

    if settings.mock:
        log.warning("MOCK=1: returning a fixture transcript")
        return mock_transcript()

    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"no audio at {path}")

    api_key = settings.require_deepgram()
    size_mb = path.stat().st_size / 1_048_576
    log.info("uploading %.1f MB to Deepgram nova-2", size_mb)

    if on_progress:
        on_progress(0.05)

    # Streamed from disk rather than read into memory -- an hour of 16kHz mono
    # wav is ~115 MB and this may be one of several concurrent jobs.
    with path.open("rb") as fh:
        try:
            response = httpx.post(
                DEEPGRAM_URL,
                params=DEEPGRAM_PARAMS,
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": "audio/wav",
                },
                content=fh,
                timeout=httpx.Timeout(30.0, read=900.0, write=900.0),
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Deepgram request failed: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"Deepgram returned {response.status_code}: {response.text[:400]}"
        )

    if on_progress:
        on_progress(0.9)

    transcript = parse_deepgram(response.json())
    log.info("transcribed %d words over %.1fs", len(transcript.words), transcript.duration)

    if on_progress:
        on_progress(1.0)
    return transcript


def parse_deepgram(payload: dict) -> Transcript:
    """Pull word timings out of a Deepgram response.

    Split out from the request so it can be tested against a captured payload
    without touching the network.
    """
    results = payload.get("results") or {}
    channels = results.get("channels") or []
    if not channels:
        raise ValueError("Deepgram response contained no channels")

    alternatives = channels[0].get("alternatives") or []
    if not alternatives:
        raise ValueError("Deepgram response contained no alternatives")

    raw_words = alternatives[0].get("words") or []
    words: list[Word] = []
    for w in raw_words:
        # punctuated_word carries the trailing "." / "?" that line-breaking needs.
        text = w.get("punctuated_word") or w.get("word") or ""
        if not text:
            continue
        speaker = w.get("speaker")
        words.append(
            Word(
                word=text,
                start=float(w.get("start", 0.0)),
                end=float(w.get("end", 0.0)),
                speaker=int(speaker) if speaker is not None else None,
            )
        )

    duration = float(payload.get("metadata", {}).get("duration") or 0.0)
    if not duration and words:
        duration = words[-1].end

    return Transcript(words=words, duration=duration)


def mock_transcript(words_per_second: float = 2.8) -> Transcript:
    """Evenly-timed words from the fixture script.

    Timing is uniform, which real speech never is -- fine for wiring checks,
    useless for judging whether selection picks good moments.
    """
    tokens = MOCK_SPEECH.split()
    step = 1.0 / words_per_second
    words = [
        Word(word=tok, start=round(i * step, 3), end=round((i + 1) * step - 0.02, 3), speaker=0)
        for i, tok in enumerate(tokens)
    ]
    duration = words[-1].end if words else 0.0
    return Transcript(words=words, duration=duration)
