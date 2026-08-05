"""Stage 3: transcript → clip candidates.

This is the product. Everything else is plumbing that moves bytes around; this
module decides which 40 seconds of a two-hour podcast is worth posting.

Two things do the work here:

1. The prompt, which encodes what a short-form hook actually is.
2. :func:`snap_to_speech`, which forces whatever the model proposes onto real
   sentence boundaries. The model is good at spotting a moment and sloppy about
   its exact edges, so we never trust its raw numbers.

Per CLAUDE.md, no other module is allowed to decide what makes a clip good.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from config import get_settings
from schemas import ClipCandidate, Transcript, Word

from ._fixtures import MOCK_CLIP_META
from .text import is_clause_end, is_sentence_end, sentence_end_indices

log = logging.getLogger("clipviral.select")

ProgressFn = Callable[[float], None]

# Transcripts longer than this get split; a three-hour stream in one request
# both blows the budget and makes the model lose the thread in the middle.
WINDOW_SEC = 2400.0
WINDOW_OVERLAP_SEC = 180.0

# Two candidates covering mostly the same moment are the same clip.
DUPLICATE_OVERLAP = 0.5

# How far from the model's proposed edge we will move to reach a clean boundary.
START_SNAP_TOLERANCE = 3.0
END_SNAP_TOLERANCE = 4.0

# Breathing room so a clip does not start on a clipped consonant.
LEAD_IN = 0.15
TAIL = 0.35


SYSTEM_PROMPT = """\
You find the moments in a long video that work as standalone short-form clips \
for TikTok, Reels and Shorts.

You are not summarising and you are not finding "important" moments. You are \
finding moments that hold a stranger who is scrolling fast and has no context.

A clip earns its place only if all four are true:

1. HOOK. The first three seconds create tension, curiosity or disagreement. A \
   claim that contradicts what the viewer believes, a question they now need \
   answered, a story that has already started, or a number that sounds wrong. \
   Setup, throat-clearing and "so as I was saying" are not hooks.
2. SELF-CONTAINED. It makes sense to someone who did not watch the previous \
   hour. No unexplained "he", "that thing we discussed", or callbacks.
3. COMPLETE THOUGHT. It starts at the beginning of a sentence and ends at the \
   end of one. The idea is finished when the clip is.
4. PAYOFF. The tension the hook created gets resolved inside the clip. A clip \
   that only asks is a clip nobody finishes.

Reject, always: intros and outros, sponsor reads, greetings and pleasantries, \
housekeeping, guest introductions, laughter with no content, and any moment \
whose meaning depends on something said earlier.

hook_score rubric, applied honestly:
  9-10  Stops a scroll cold. Strong contradiction, confession, or a story that \
        opens mid-action. You would send this to a friend.
  7-8   Clear hook, clean payoff, tight. Good post, not a viral one.
  5-6   Genuinely interesting but slow to start, or needs a beat of context.
  3-4   Decent content, no hook. This is a podcast excerpt, not a clip.
  1-2   Should not be posted.

Do not inflate scores. A transcript with four good moments should get four \
high scores and the rest low, not ten sevens. The scores are used to decide \
what gets rendered, so flattering everything makes the tool useless.

Titles: write what would make someone tap, in the speaker's own framing. No \
clickbait the clip does not deliver, no "You won't believe", no emoji, no \
title case. Under 60 characters.

Reasons: name the specific mechanism -- what the hook is and where the payoff \
lands. "Interesting discussion about sleep" is not a reason.\
"""

CLIP_TOOL = {
    "name": "propose_clips",
    "description": "Return the clip candidates found in the transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {
                            "type": "number",
                            "description": "Start in seconds, copied from a line timestamp.",
                        },
                        "end": {
                            "type": "number",
                            "description": "End in seconds, copied from a line's end timestamp.",
                        },
                        "hook_score": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                        },
                        "title": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["start", "end", "hook_score", "title", "reason"],
                },
            }
        },
        "required": ["clips"],
    },
}


# --- transcript formatting --------------------------------------------------


def format_transcript_for_model(words: Sequence[Word]) -> str:
    """One line per sentence, tagged with its exact start and end.

    Sentences rather than fixed time chunks: the model picks clip edges by
    copying a line's timestamps, so making sentences the unit means the numbers
    it returns already fall on complete thoughts before snapping runs.
    """
    if not words:
        return ""

    lines: list[str] = []
    buf: list[Word] = []
    for word in words:
        buf.append(word)
        # Long run-on speech still needs to break somewhere or one "sentence"
        # swallows a minute of audio and stops being a usable boundary.
        too_long = (buf[-1].end - buf[0].start) > 20.0
        if is_sentence_end(word) or (too_long and is_clause_end(word)):
            lines.append(_line(buf))
            buf = []
    if buf:
        lines.append(_line(buf))
    return "\n".join(lines)


def _line(buf: list[Word]) -> str:
    text = " ".join(w.word for w in buf)
    speakers = {w.speaker for w in buf if w.speaker is not None}
    tag = f" S{sorted(speakers)[0]}" if len(speakers) == 1 else ""
    return f"[{buf[0].start:.1f}-{buf[-1].end:.1f}{tag}] {text}"


def build_user_prompt(
    words: Sequence[Word],
    *,
    target_count: int,
    min_sec: float,
    max_sec: float,
    window_start: float,
    window_end: float,
) -> str:
    return f"""\
Transcript of a video, one sentence per line. Each line is tagged with its \
start and end time in seconds: [start-end]. `S0`/`S1` marks the speaker where \
diarisation identified one.

This section covers {window_start:.0f}s to {window_end:.0f}s of the source.

Find the {target_count} best clip candidates in it.

Hard constraints:
- Every clip must be between {min_sec:.0f} and {max_sec:.0f} seconds long.
- `start` must be the start timestamp of some line. `end` must be the end \
timestamp of some line. Copy those numbers exactly; do not invent times or \
round them.
- Clips must not overlap each other.
- Times are seconds as decimals, always within {window_start:.0f}-{window_end:.0f}.

If there are fewer than {target_count} moments that genuinely clear the bar, \
return fewer. Returning weak clips to hit a count is worse than returning three \
strong ones.

<transcript>
{format_transcript_for_model(words)}
</transcript>"""


# --- boundary snapping ------------------------------------------------------


def _boundary_indices(words: Sequence[Word], level: str) -> list[int]:
    """Indices usable as a clip edge, at decreasing strictness."""
    if level == "sentence":
        return sentence_end_indices(list(words))
    if level == "clause":
        return [i for i, w in enumerate(words) if is_sentence_end(w) or is_clause_end(w)]
    return list(range(len(words)))


def snap_to_speech(
    start: float,
    end: float,
    words: Sequence[Word],
    *,
    min_sec: float,
    max_sec: float,
) -> tuple[float, float] | None:
    """Move a proposed span onto real speech boundaries.

    Returns ``None`` when no boundary pair near the request can satisfy the
    duration limits -- the caller drops the candidate rather than emitting a
    clip that cuts someone off mid-word.
    """
    if not words:
        return None

    for level in ("sentence", "clause", "word"):
        ends = _boundary_indices(words, level)
        starts = _start_indices(words, level)
        if not ends or not starts:
            continue

        si = _nearest(
            [i for i in starts if abs(words[i].start - start) <= START_SNAP_TOLERANCE],
            key=lambda i: abs(words[i].start - start),
        )
        if si is None:
            si = _nearest(starts, key=lambda i: abs(words[i].start - start))
        if si is None:
            continue

        st = max(0.0, words[si].start - LEAD_IN)

        best: tuple[float, float, float] | None = None
        fallback: tuple[float, float, float] | None = None
        for ei in ends:
            if ei < si:
                continue
            et = words[ei].end + TAIL
            duration = et - st
            if duration > max_sec:
                break  # ends are ordered, everything after is longer too
            distance = abs(et - end)
            if duration >= min_sec:
                if best is None or distance < best[0]:
                    best = (distance, st, et)
            elif fallback is None or duration > (fallback[2] - fallback[1]):
                fallback = (distance, st, et)

        if best is not None:
            # Only accept a loose boundary if it did not drift absurdly far.
            if level == "word" and best[0] > END_SNAP_TOLERANCE * 2:
                continue
            return best[1], best[2]
        if level == "word" and fallback is not None:
            return None

    return None


def _start_indices(words: Sequence[Word], level: str) -> list[int]:
    if level == "word":
        return list(range(len(words)))
    ends = _boundary_indices(words, level)
    starts = [0]
    starts.extend(i + 1 for i in ends if i + 1 < len(words))
    return sorted(set(starts))


def _nearest(indices: Sequence[int], *, key: Callable[[int], float]) -> int | None:
    if not indices:
        return None
    return min(indices, key=key)


# --- validation -------------------------------------------------------------


def _overlap_ratio(a: ClipCandidate, b: ClipCandidate) -> float:
    overlap = min(a.end, b.end) - max(a.start, b.start)
    if overlap <= 0:
        return 0.0
    shorter = min(a.duration, b.duration)
    return overlap / shorter if shorter else 0.0


def validate_candidates(
    raw: Sequence[dict],
    transcript: Transcript,
    *,
    min_sec: float,
    max_sec: float,
) -> list[ClipCandidate]:
    """Snap, bounds-check and de-duplicate whatever the model returned."""
    cleaned: list[ClipCandidate] = []

    for item in raw:
        try:
            start = float(item["start"])
            end = float(item["end"])
            score = int(item["hook_score"])
            title = str(item["title"]).strip()
            reason = str(item.get("reason", "")).strip()
        except (KeyError, TypeError, ValueError):
            log.warning("dropping malformed candidate: %r", item)
            continue

        if end <= start or not title:
            log.warning("dropping candidate with bad span: %.1f-%.1f", start, end)
            continue

        span_words = transcript.words_between(
            max(0.0, start - END_SNAP_TOLERANCE),
            min(transcript.duration or end + END_SNAP_TOLERANCE, end + END_SNAP_TOLERANCE),
        )
        snapped = snap_to_speech(start, end, span_words, min_sec=min_sec, max_sec=max_sec)
        if snapped is None:
            log.info("dropping %.1f-%.1f (%s): no clean boundary fits", start, end, title)
            continue

        s, e = snapped
        if transcript.duration:
            e = min(e, transcript.duration)
        if e - s < min_sec:
            continue

        cleaned.append(
            ClipCandidate(
                start=round(s, 3),
                end=round(e, 3),
                hook_score=max(1, min(10, score)),
                title=title[:120],
                reason=reason[:400],
            )
        )

    # Highest score first so de-duplication keeps the better of any overlap.
    cleaned.sort(key=lambda c: (-c.hook_score, c.start))
    kept: list[ClipCandidate] = []
    for cand in cleaned:
        if any(_overlap_ratio(cand, k) > DUPLICATE_OVERLAP for k in kept):
            continue
        kept.append(cand)

    kept.sort(key=lambda c: c.start)
    return kept


# --- the model call ---------------------------------------------------------


def _windows(duration: float) -> list[tuple[float, float]]:
    if duration <= WINDOW_SEC:
        return [(0.0, duration)]
    out: list[tuple[float, float]] = []
    pos = 0.0
    while pos < duration:
        end = min(duration, pos + WINDOW_SEC)
        out.append((pos, end))
        if end >= duration:
            break
        pos = end - WINDOW_OVERLAP_SEC
    return out


# Room for the model to think before it answers. Current models reason
# adaptively unless told not to, and max_tokens caps thinking *and* the tool
# call together -- so a budget sized only for the answer lets the reasoning eat
# it and the response comes back truncated with no tool call at all. The clips
# themselves need about 1k tokens; the rest of this is headroom for thinking.
MAX_OUTPUT_TOKENS = 16000


def _call_model(prompt: str, *, model: str, api_key: str) -> list[dict]:
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[CLIP_TOOL],
        tool_choice={"type": "tool", "name": "propose_clips"},
        messages=[{"role": "user", "content": prompt}],
    )

    # A truncated response silently loses the tool call. Without this the job
    # reports success having selected nothing, which reads as "no good moments
    # in this video" -- the one failure that looks exactly like a valid result.
    if message.stop_reason == "max_tokens":
        raise RuntimeError(
            f"model response hit the {MAX_OUTPUT_TOKENS}-token limit before finishing; "
            "raise MAX_OUTPUT_TOKENS or shorten the window"
        )

    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "propose_clips":
            clips = block.input.get("clips", [])
            if isinstance(clips, list):
                return clips
    raise RuntimeError(
        f"model returned no propose_clips tool call (stop_reason={message.stop_reason})"
    )


def select(
    transcript: Transcript,
    *,
    target_count: int | None = None,
    on_progress: ProgressFn | None = None,
) -> list[ClipCandidate]:
    settings = get_settings()
    min_sec = settings.clip_min_sec
    max_sec = settings.clip_max_sec
    target = target_count or settings.target_clip_count

    if not transcript.words:
        log.warning("empty transcript, nothing to select")
        return []

    if settings.mock:
        log.warning("MOCK=1: deriving candidates from the fixture transcript")
        return _mock_candidates(transcript, min_sec=min_sec, max_sec=max_sec)

    api_key = settings.require_anthropic()
    windows = _windows(transcript.duration or transcript.words[-1].end)
    per_window = max(4, -(-target // len(windows)))  # ceil

    raw: list[dict] = []
    attempted_windows = 0
    failed_windows = 0
    for i, (w_start, w_end) in enumerate(windows):
        words = transcript.words_between(w_start, w_end)
        if len(words) < 40:
            continue
        attempted_windows += 1
        prompt = build_user_prompt(
            words,
            target_count=per_window,
            min_sec=min_sec,
            max_sec=max_sec,
            window_start=w_start,
            window_end=w_end,
        )
        log.info(
            "selecting from window %d/%d (%.0f-%.0fs, %d words)",
            i + 1,
            len(windows),
            w_start,
            w_end,
            len(words),
        )
        # One window failing must not discard the others, nor the download and
        # transcription already paid for. Nine good windows out of ten is a
        # usable result; re-running the whole job is not.
        try:
            raw.extend(_call_model(prompt, model=settings.select_model, api_key=api_key))
        except Exception:  # noqa: BLE001 - any API failure, not just SDK errors
            failed_windows += 1
            log.exception("window %d/%d failed, continuing", i + 1, len(windows))
        if on_progress:
            on_progress((i + 1) / len(windows))

    if failed_windows and failed_windows == attempted_windows:
        raise RuntimeError(
            f"every one of the {attempted_windows} selection requests failed; see the log"
        )
    if failed_windows:
        log.warning(
            "%d of %d windows failed; selecting from the rest",
            failed_windows,
            attempted_windows,
        )

    candidates = validate_candidates(raw, transcript, min_sec=min_sec, max_sec=max_sec)
    log.info("kept %d of %d proposed candidates", len(candidates), len(raw))

    # A long video is windowed and each window returns its own quota, so allow
    # more than the target before trimming. Trim by score, then restore
    # chronological order -- cutting the tail of a time-sorted list would throw
    # away the best moments simply for happening late.
    limit = max(target, 1) * 2 if len(windows) > 1 else max(target, 1)
    best = sorted(candidates, key=lambda c: -c.hook_score)[:limit]
    return sorted(best, key=lambda c: c.start)


def _mock_candidates(
    transcript: Transcript,
    *,
    min_sec: float,
    max_sec: float,
) -> list[ClipCandidate]:
    """Walk the fixture transcript, cutting at sentence ends inside the limits."""
    words = transcript.words
    ends = sentence_end_indices(words)
    if not ends:
        return []

    proposed: list[dict] = []
    cursor = 0
    for meta in MOCK_CLIP_META:
        if cursor >= len(words):
            break
        start_t = words[cursor].start
        chosen: int | None = None
        for ei in ends:
            if ei <= cursor:
                continue
            if words[ei].end - start_t >= min_sec:
                chosen = ei
                break
        if chosen is None or words[chosen].end - start_t > max_sec:
            break
        proposed.append({"start": start_t, "end": words[chosen].end, **meta})
        cursor = chosen + 1

    return validate_candidates(proposed, transcript, min_sec=min_sec, max_sec=max_sec)
