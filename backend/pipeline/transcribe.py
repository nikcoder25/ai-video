"""Stage 2: audio → word-level transcript via Deepgram nova-2.

Returns word timings, which everything downstream depends on: selection reads
them to find sentence boundaries, captions read them for per-word sync.
"""

from __future__ import annotations

import logging
import time
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

# The Anthropic SDK retries on its own; httpx does not, so this side needs it
# explicitly or selection gets three attempts and transcription gets one.
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 2.0


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

    response = _post_with_retry(path, api_key=api_key)

    if on_progress:
        on_progress(0.9)

    transcript = parse_deepgram(response.json())
    log.info("transcribed %d words over %.1fs", len(transcript.words), transcript.duration)

    if on_progress:
        on_progress(1.0)
    return transcript


def _post_with_retry(path: Path, *, api_key: str) -> httpx.Response:
    """Upload the audio, retrying transient failures.

    Worth retrying because of what has already been spent by this point: the
    source video is downloaded and the wav extracted, and the failure path
    deletes both. A single 502 would otherwise cost the whole job and make the
    user re-download a two-hour podcast. Only transient classes are retried --
    a bad key or a rejected file fails immediately, since repeating it just
    delays the same answer.
    """
    last: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with path.open("rb") as fh:
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
            last = RuntimeError(f"Deepgram request failed: {exc}")
        else:
            if response.status_code == 200:
                return response
            last = RuntimeError(
                f"Deepgram returned {response.status_code}: {response.text[:400]}"
            )
            # 4xx other than rate limiting is a rejection, not a blip.
            if response.status_code < 500 and response.status_code != 429:
                raise last

        if attempt < MAX_ATTEMPTS:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            log.warning(
                "Deepgram attempt %d/%d failed (%s); retrying in %.0fs",
                attempt,
                MAX_ATTEMPTS,
                last,
                delay,
            )
            time.sleep(delay)

    raise last if last else RuntimeError("Deepgram request failed")


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
