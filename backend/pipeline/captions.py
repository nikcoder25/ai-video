"""Word-synced ASS subtitles.

Style follows the existing NYT/Rohan pipeline: bold sans, thick black outline,
white words with the active word popping to gold (``&H00D7FF&``), sitting at
65% of frame height.

ASS colours are ``&HAABBGGRR`` -- byte order is reversed from hex RGB, which is
the single most common source of "why is my yellow blue" in this format.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from schemas import Word

from .text import is_clause_end, is_sentence_end

log = logging.getLogger("clipviral.captions")

WHITE = "&H00FFFFFF"
GOLD = "&H0000D7FF"
BLACK = "&H00000000"
SHADOW = "&H80000000"

# Poppins matches the existing videos; DejaVu is the fallback that is always
# present on a Debian base image so a missing font never fails a render.
FONT_STACK = ("Poppins", "Montserrat", "DejaVu Sans")

MAX_WORDS_PER_LINE = 3
# A pause longer than this ends the line even mid-sentence -- holding three
# words on screen through two seconds of silence reads as a freeze.
PAUSE_BREAK_SEC = 0.6
# Pop-in: overshoot then settle. Milliseconds, relative to the word appearing.
POP_UP_MS = 80
POP_SETTLE_MS = 200
POP_SCALE = 118


@lru_cache(maxsize=1)
def pick_font(stack: tuple[str, ...] = FONT_STACK) -> str:
    """First font in ``stack`` that fontconfig can actually resolve.

    libass silently substitutes a missing family, so an unavailable Poppins
    would render in whatever the system picks -- checking up front means the
    log shows which font the clip was really built with.
    """
    exe = shutil.which("fc-match")
    if exe is None:
        log.info("fontconfig unavailable, assuming %s", stack[-1])
        return stack[-1]

    for name in stack:
        try:
            proc = subprocess.run(
                [exe, name, "family"], capture_output=True, text=True, check=False, timeout=10
            )
        except (OSError, subprocess.TimeoutExpired):
            break
        resolved = (proc.stdout or "").strip()
        if proc.returncode == 0 and resolved.lower() == name.lower():
            return name
        log.debug("font %s unavailable (fontconfig resolved %r)", name, resolved)

    log.info("falling back to %s for captions", stack[-1])
    return stack[-1]


def _ass_time(seconds: float) -> str:
    """Seconds → ``H:MM:SS.cc``. ASS resolution is centiseconds, not seconds."""
    seconds = max(0.0, seconds)
    centis = int(round(seconds * 100))
    hours, rem = divmod(centis, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _escape(text: str) -> str:
    """Neutralise the characters ASS treats as markup."""
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").strip()


def group_words(
    words: Sequence[Word],
    *,
    max_words: int = MAX_WORDS_PER_LINE,
) -> list[list[Word]]:
    """Chunk words into caption lines.

    Breaks on: the word cap, sentence endings, and natural pauses. Clause
    endings only break a line that is already at least two words long, so we
    do not strand a single orphan word after a comma.
    """
    lines: list[list[Word]] = []
    current: list[Word] = []

    for i, word in enumerate(words):
        current.append(word)
        at_cap = len(current) >= max_words
        ends_sentence = is_sentence_end(word)
        ends_clause = is_clause_end(word) and len(current) >= 2

        gap = 0.0
        if i + 1 < len(words):
            gap = words[i + 1].start - word.end
        else:
            gap = float("inf")

        if at_cap or ends_sentence or ends_clause or gap > PAUSE_BREAK_SEC:
            lines.append(current)
            current = []

    if current:
        lines.append(current)
    return lines


def _style_block(width: int, height: int, font: str) -> str:
    # Scale type with the frame so a 720p preview render is not comically large.
    font_size = max(28, int(height * 0.045))
    outline = max(3, int(height * 0.0035))
    shadow = max(1, int(height * 0.0012))
    margin_v = int(height * 0.35)  # bottom of text at 65% height
    margin_h = int(width * 0.08)

    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{font_size},{WHITE},{GOLD},{BLACK},{SHADOW},-1,0,0,0,100,100,0.6,0,1,{outline},{shadow},2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""


def _render_line(line: Sequence[Word], active_index: int) -> str:
    """The line as ASS markup with one word highlighted and popping."""
    parts: list[str] = []
    for i, word in enumerate(line):
        text = _escape(word.word)
        if not text:
            continue
        if i == active_index:
            anim = (
                f"\\fscx100\\fscy100"
                f"\\t(0,{POP_UP_MS},\\fscx{POP_SCALE}\\fscy{POP_SCALE})"
                f"\\t({POP_UP_MS},{POP_SETTLE_MS},\\fscx100\\fscy100)"
            )
            parts.append(f"{{\\c{GOLD}{anim}}}{text}{{\\r}}")
        else:
            parts.append(f"{{\\c{WHITE}}}{text}")
    return " ".join(parts)


def build_ass(
    words: Sequence[Word],
    *,
    width: int = 1080,
    height: int = 1920,
    clip_start: float = 0.0,
    font: str = FONT_STACK[0],
    max_words: int = MAX_WORDS_PER_LINE,
) -> str:
    """Build a full ASS document for one clip.

    ``clip_start`` is subtracted from every timestamp, because the burned clip
    starts at zero while the words carry source-relative times.
    """
    header = _style_block(width, height, font)
    events: list[str] = []

    for line in group_words(words, max_words=max_words):
        for i, word in enumerate(line):
            start = word.start - clip_start
            # Hold the last word of a line until the next word starts, so the
            # line does not flicker out during the gap before the next line.
            if i + 1 < len(line):
                end = line[i + 1].start - clip_start
            else:
                end = max(word.end - clip_start, start + 0.12)

            if end <= 0:
                continue
            start = max(0.0, start)
            if end - start < 0.04:
                end = start + 0.04

            text = _render_line(line, i)
            if not text:
                continue
            events.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{text}"
            )

    log.info("built %d caption events from %d words", len(events), len(words))
    return header + "\n" + "\n".join(events) + "\n"


def write_ass(
    path: str | Path,
    words: Sequence[Word],
    **kwargs: object,
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_ass(words, **kwargs), encoding="utf-8")  # type: ignore[arg-type]
    return out
