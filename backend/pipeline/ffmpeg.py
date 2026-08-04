"""Thin subprocess wrapper around ffmpeg/ffprobe.

Every ffmpeg invocation in the codebase goes through :func:`run` so that the
exact command is logged. When a render looks wrong the first debugging step is
copying the logged command into a terminal, so the log line must be complete
and runnable -- no abbreviation, no ``...``.
"""

from __future__ import annotations

import json
import logging
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from config import get_settings

log = logging.getLogger("clipviral.ffmpeg")


class FFmpegError(RuntimeError):
    """An ffmpeg/ffprobe call exited non-zero."""

    def __init__(self, command: str, returncode: int, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        tail = "\n".join(stderr.strip().splitlines()[-15:])
        super().__init__(f"ffmpeg exited {returncode}\n  command: {command}\n{tail}")


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_video: bool
    has_audio: bool

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0


def _bin(name: str) -> str:
    settings = get_settings()
    exe = settings.ffmpeg_bin if name == "ffmpeg" else settings.ffprobe_bin
    resolved = shutil.which(exe)
    if resolved is None:
        raise FFmpegError(
            exe,
            127,
            f"{exe!r} not found on PATH. Install ffmpeg (apt install ffmpeg) or "
            f"set FFMPEG_BIN/FFPROBE_BIN to an absolute path.",
        )
    return resolved


def available() -> bool:
    """True when both ffmpeg and ffprobe can be located."""
    try:
        _bin("ffmpeg")
        _bin("ffprobe")
    except FFmpegError:
        return False
    return True


def run(
    args: Sequence[str],
    *,
    desc: str,
    timeout: float | None = None,
    binary: str = "ffmpeg",
) -> str:
    """Run ffmpeg with ``args``, returning stderr (where ffmpeg reports).

    ``args`` excludes the binary itself and the boilerplate flags below.
    """
    # -nostdin is an ffmpeg-only option; ffprobe rejects it outright.
    prefix = [_bin(binary), "-hide_banner", "-loglevel", "error"]
    if binary == "ffmpeg":
        prefix += ["-nostdin", "-y"]
    cmd = [*prefix, *[str(a) for a in args]]

    log.info("%s: %s", desc, shlex.join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(shlex.join(cmd), -1, f"timed out after {timeout}s") from exc

    if proc.returncode != 0:
        raise FFmpegError(shlex.join(cmd), proc.returncode, proc.stderr or proc.stdout)
    return proc.stderr


def probe(path: str | Path) -> MediaInfo:
    """Read stream metadata without decoding the file."""
    args = [
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    raw = subprocess.run(
        [_bin("ffprobe"), "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if raw.returncode != 0:
        raise FFmpegError(f"ffprobe {path}", raw.returncode, raw.stderr)

    data = json.loads(raw.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = 0.0
    fmt_dur = data.get("format", {}).get("duration")
    if fmt_dur:
        duration = float(fmt_dur)
    elif video and video.get("duration"):
        duration = float(video["duration"])

    width = int(video["width"]) if video and video.get("width") else 0
    height = int(video["height"]) if video and video.get("height") else 0

    fps = 0.0
    if video:
        # r_frame_rate is a rational like "30000/1001".
        rate = video.get("r_frame_rate") or video.get("avg_frame_rate") or "0/1"
        try:
            num, _, den = rate.partition("/")
            fps = float(num) / float(den) if float(den) else 0.0
        except (ValueError, ZeroDivisionError):
            fps = 0.0

    return MediaInfo(
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        has_video=video is not None,
        has_audio=audio is not None,
    )


def extract_audio(video_path: str | Path, out_path: str | Path) -> Path:
    """16kHz mono PCM wav -- what speech APIs want, and small enough to upload."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(out),
        ],
        desc="extract 16kHz mono wav",
    )
    return out


def extract_frames(
    video_path: str | Path,
    out_dir: str | Path,
    *,
    start: float,
    duration: float,
    fps: float = 2.0,
    width: int = 480,
) -> list[Path]:
    """Write downscaled sample frames to disk for face detection.

    Frames go to disk rather than memory deliberately: a 58s clip at 2fps is
    ~116 frames, and holding full-size decoded frames would blow past the
    memory budget on a small VPS.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run(
        [
            "-ss",
            f"{start:.3f}",
            "-i",
            str(video_path),
            "-t",
            f"{duration:.3f}",
            "-vf",
            f"fps={fps},scale={width}:-2",
            "-q:v",
            "4",
            str(out / "frame-%05d.jpg"),
        ],
        desc=f"sample frames at {fps}fps for face tracking",
    )
    return sorted(out.glob("frame-*.jpg"))
