"""Terminal entry point. Test the pipeline here before touching the API.

    python cli.py "https://youtube.com/watch?v=..."          # candidates only
    python cli.py "https://youtube.com/watch?v=..." --render # also encode mp4s
    MOCK=1 python cli.py anything                            # no API keys

The candidate listing is built for the quality gate: it prints a jump link per
pick so you can watch the actual moment rather than trusting the score.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import uuid
from pathlib import Path

from config import get_settings
from pipeline import ffmpeg
from pipeline.run import run_job
from pipeline.text import format_timestamp
from schemas import Stage

log = logging.getLogger("clipviral.cli")

YOUTUBE_ID = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/|live/))([A-Za-z0-9_-]{11})"
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )
    # yt-dlp and httpx are chatty at INFO and drown out the pipeline log.
    for noisy in ("httpx", "httpcore", "urllib3", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _jump_link(source_url: str | None, seconds: float) -> str | None:
    if not source_url:
        return None
    match = YOUTUBE_ID.search(source_url)
    if not match:
        return None
    return f"https://www.youtube.com/watch?v={match.group(1)}&t={int(seconds)}s"


def _print_candidates(result, source_url: str | None) -> None:
    if not result.candidates:
        print("\nNo candidates cleared the bar. Nothing to review.\n")
        return

    print(f"\n{len(result.candidates)} candidates  ->  {result.candidates_path}\n")
    for cand in result.candidates:
        span = f"{format_timestamp(cand.start)}-{format_timestamp(cand.end)}"
        print(f"  [{cand.hook_score:2d}/10]  {span:>15}  ({cand.duration:4.1f}s)  {cand.title}")
        print(f"           {cand.reason}")
        link = _jump_link(source_url, cand.start)
        if link:
            print(f"           watch: {link}")
        print()


def _print_clips(result) -> None:
    if not result.clips:
        return
    print(f"{len(result.clips)} clips rendered:\n")
    for clip in result.clips:
        size_mb = clip.size_bytes / 1_048_576
        print(
            f"  clip-{clip.index:02d}.mp4  {clip.duration:4.1f}s  "
            f"{size_mb:5.1f} MB  {clip.width}x{clip.height}  {clip.candidate.title}"
        )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Find and render viral clips from a long video.",
    )
    parser.add_argument("source", help="YouTube/video URL, or a local file path with --file")
    parser.add_argument("--file", action="store_true", help="treat source as a local video file")
    parser.add_argument("--render", action="store_true", help="encode mp4s, not just candidates")
    parser.add_argument("--work", default=None, help="working directory (default: WORK_DIR/<id>)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    settings = get_settings()

    if not ffmpeg.available():
        print(
            "ffmpeg/ffprobe not found on PATH. Install them (apt install ffmpeg) "
            "or set FFMPEG_BIN/FFPROBE_BIN.",
            file=sys.stderr,
        )
        return 2

    job_id = uuid.uuid4().hex[:12]
    work = Path(args.work) if args.work else settings.work_dir / job_id
    if settings.mock:
        log.warning("MOCK=1 -- synthetic video, fixture transcript, fixture candidates")

    def on_update(stage: Stage, fraction: float) -> None:
        if fraction in (0.0, 1.0):
            log.info("stage %s %s", stage.value, "start" if fraction == 0.0 else "done")

    try:
        result = run_job(
            work_dir=work,
            url=None if args.file else args.source,
            upload_path=args.source if args.file else None,
            render=args.render,
            on_update=on_update,
        )
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - the CLI is the top of the stack
        log.exception("pipeline failed")
        print(f"\nfailed: {exc}", file=sys.stderr)
        return 1

    _print_candidates(result, result.source.source_url)
    _print_clips(result)
    print(f"working directory: {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
