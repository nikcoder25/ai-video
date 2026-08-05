"""Stage 1: get a local video file plus a 16kHz mono wav.

Two entry points -- :func:`download` for a URL, :func:`ingest_upload` for a file
the user posted. Both return the same :class:`SourceMedia`, so nothing
downstream needs to know which one ran.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from config import get_settings
from schemas import SourceMedia

from . import ffmpeg

log = logging.getLogger("clipviral.download")

ProgressFn = Callable[[float], None]

# Cap at 1080p: the output is 1080x1920, so a 4K source costs download time and
# decode time for detail that gets thrown away by the crop.
YTDLP_FORMAT = (
    "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]"
    "/bestvideo[height<=1080]+bestaudio"
    "/best[height<=1080]"
    "/best"
)


def _reject_unfetchable(info: dict | None, settings) -> None:
    """Refuse sources that would run forever or cost more than they are worth.

    Checked against the metadata probe rather than mid-download, because both
    of these failure modes are unbounded: a live stream never ends, and a
    twelve-hour upload holds the single render slot for most of a day.
    """
    if not info:
        raise ValueError("could not read any information about that URL")

    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
        raise ValueError("that is a live stream -- wait until it has finished and post the VOD")

    duration = info.get("duration")
    if duration and duration > settings.max_source_sec:
        hours = settings.max_source_sec / 3600
        raise ValueError(
            f"that video is {duration / 3600:.1f} hours long; the limit is {hours:.1f} hours"
        )


def _pick_downloaded(work: Path) -> Path | None:
    """The finished video among yt-dlp's leftovers.

    A merged download leaves format-specific files (``source.f137.mp4``) and
    partials (``source.mp4.part``) beside the real output, and they sort
    *before* it -- taking the first match reliably picks the wrong file.
    """
    merged = [
        p
        for p in work.glob("source.*")
        if p.suffix not in {".wav", ".part", ".ytdl"} and ".f" not in p.name[len("source") :]
    ]
    if merged:
        return max(merged, key=lambda p: p.stat().st_size)
    return None


def _finalise(video_path: Path, title: str, source_url: str | None) -> SourceMedia:
    info = ffmpeg.probe(video_path)
    if not info.has_video:
        raise ValueError(f"{video_path.name} has no video stream")
    if not info.has_audio:
        raise ValueError(
            f"{video_path.name} has no audio stream -- there is nothing to transcribe"
        )

    # The URL path checks this against yt-dlp's metadata before spending the
    # download; uploads have no metadata to check, so this is where they hit it.
    limit = get_settings().max_source_sec
    if info.duration > limit:
        raise ValueError(
            f"that video is {info.duration / 3600:.1f} hours long; "
            f"the limit is {limit / 3600:.1f} hours"
        )

    audio_path = video_path.with_name("audio.wav")
    ffmpeg.extract_audio(video_path, audio_path)

    return SourceMedia(
        video_path=str(video_path),
        audio_path=str(audio_path),
        title=title,
        duration=info.duration,
        width=info.width,
        height=info.height,
        fps=info.fps,
        source_url=source_url,
    )


def download(
    url: str,
    work_dir: str | Path,
    *,
    on_progress: ProgressFn | None = None,
) -> SourceMedia:
    """Fetch ``url`` with yt-dlp into ``work_dir``."""
    settings = get_settings()
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    if settings.mock:
        return _mock_source(work, source_url=url)

    import yt_dlp  # imported lazily so MOCK runs need no yt-dlp install

    def hook(d: dict) -> None:
        if not on_progress or d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        got = d.get("downloaded_bytes")
        if total and got:
            on_progress(min(0.99, got / total))

    out_tmpl = str(work / "source.%(ext)s")
    opts = {
        "format": YTDLP_FORMAT,
        "outtmpl": out_tmpl,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "retries": 3,
        "fragment_retries": 3,
        # Without this a server that dribbles one byte every 19 seconds never
        # trips a timeout, and the job holds the render slot indefinitely.
        "socket_timeout": 30,
        "max_filesize": settings.max_source_bytes,
    }

    log.info("yt-dlp fetching %s", url)
    with yt_dlp.YoutubeDL(opts) as ydl:
        probed = ydl.extract_info(url, download=False)
        _reject_unfetchable(probed, settings)
        info = ydl.extract_info(url, download=True)

    title = (info or {}).get("title") or "Untitled"
    video_path = _pick_downloaded(work)
    if video_path is None:
        raise FileNotFoundError(f"yt-dlp reported success but wrote nothing to {work}")

    if on_progress:
        on_progress(1.0)
    return _finalise(video_path, title, url)


def ingest_upload(
    uploaded_path: str | Path,
    work_dir: str | Path,
    *,
    title: str | None = None,
) -> SourceMedia:
    """Adopt an already-uploaded file as the pipeline source."""
    src = Path(uploaded_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    dest = work / f"source{src.suffix or '.mp4'}"
    if src.resolve() != dest.resolve():
        shutil.move(str(src), dest)

    return _finalise(dest, title or src.stem, None)


def _mock_source(work: Path, *, source_url: str | None) -> SourceMedia:
    """Synthesise a source video so MOCK runs exercise the real ffmpeg paths.

    Deliberately generated rather than checked in: a 2-minute 720p fixture would
    be a multi-megabyte binary in git for something ffmpeg can make in seconds.
    """
    video_path = work / "source.mp4"
    duration = 130.0

    if not video_path.exists():
        ffmpeg.run(
            [
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size=1280x720:rate=30:duration={duration}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=220:duration={duration}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(video_path),
            ],
            desc="MOCK: synthesise source video",
            timeout=300,
        )

    log.warning("MOCK=1: using a synthetic source video, not %s", source_url)
    return _finalise(video_path, "MOCK source video", source_url)
