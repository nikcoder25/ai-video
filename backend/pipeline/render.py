"""Stage 4: cut, reframe, caption and encode one vertical clip.

Deliberate choices worth not "simplifying" later:

* The cut re-encodes. Stream copy snaps the in-point to the nearest keyframe,
  which drifts the audio against the caption timings by up to a second.
* Seeking is split: a fast seek before ``-i`` to skip most of the file without
  decoding, then a short accurate seek after ``-i`` to land on the exact frame.
* Output bitrate is capped from the size budget rather than hoped for, so a
  busy 58-second clip cannot quietly blow past the limit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from config import get_settings
from schemas import ClipCandidate, RenderedClip, SourceMedia, Transcript

from . import ffmpeg
from .captions import pick_font, write_ass
from .crop import plan_crop

log = logging.getLogger("clipviral.render")

ProgressFn = Callable[[float], None]

# Decode this many seconds before the in-point to land the accurate seek.
PREROLL = 2.0
AUDIO_BITRATE_KBPS = 128
MAX_VIDEO_BITRATE_KBPS = 12_000
OUTPUT_FPS = 30


def _escape_filter_path(path: str | Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument."""
    text = str(path)
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    return text.replace("'", "\\'")


def _bitrate_cap_kbps(duration: float, max_mb: int) -> int:
    """Video bitrate that keeps the muxed file inside the size budget."""
    if duration <= 0:
        return MAX_VIDEO_BITRATE_KBPS
    total_kbits = max_mb * 8 * 1000
    # 4% headroom for container overhead, then subtract the audio track.
    budget = (total_kbits / duration) * 0.96 - AUDIO_BITRATE_KBPS
    return int(max(800, min(MAX_VIDEO_BITRATE_KBPS, budget)))


def render_clip(
    source: SourceMedia,
    candidate: ClipCandidate,
    transcript: Transcript,
    *,
    out_path: str | Path,
    index: int,
    work_dir: str | Path,
) -> RenderedClip:
    settings = get_settings()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    duration = candidate.duration
    out_w = settings.render_width
    out_h = settings.render_height

    plan = plan_crop(
        source.video_path,
        start=candidate.start,
        duration=duration,
        src_width=source.width,
        src_height=source.height,
        out_width=out_w,
        out_height=out_h,
    )

    words = transcript.words_between(candidate.start, candidate.end)
    ass_path = write_ass(
        work / f"clip-{index:02d}.ass",
        words,
        width=out_w,
        height=out_h,
        clip_start=candidate.start,
        font=pick_font(),
    )

    # --- video chain --------------------------------------------------------
    # setpts first so the clip timeline starts at 0; the sendcmd script and the
    # subtitle timings are both written relative to the clip, not the source.
    chain = ["setpts=PTS-STARTPTS"]

    if plan.is_static:
        chain.append(f"crop={plan.crop_w}:{plan.crop_h}:{plan.static_x}:{plan.y}")
    else:
        cmd_file = plan.write_sendcmd(work / f"clip-{index:02d}.cmd")
        chain.append(f"sendcmd=f={_escape_filter_path(cmd_file)}")
        chain.append(
            f"crop={plan.crop_w}:{plan.crop_h}:{plan.keyframes[0][1]}:{plan.y}"
        )

    chain.append(f"scale={out_w}:{out_h}:flags=lanczos")
    chain.append(f"fps={OUTPUT_FPS}")
    chain.append(f"ass={_escape_filter_path(ass_path)}")
    chain.append("setsar=1")

    audio_chain = "asetpts=PTS-STARTPTS,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"

    fast_seek = max(0.0, candidate.start - PREROLL)
    accurate_seek = candidate.start - fast_seek
    cap = _bitrate_cap_kbps(duration, settings.max_clip_mb)

    ffmpeg.run(
        [
            "-ss",
            f"{fast_seek:.3f}",
            "-i",
            str(source.video_path),
            "-ss",
            f"{accurate_seek:.3f}",
            "-t",
            f"{duration:.3f}",
            "-filter_complex",
            f"[0:v]{','.join(chain)}[v];[0:a]{audio_chain}[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-profile:v",
            "high",
            "-crf",
            "21",
            "-maxrate",
            f"{cap}k",
            "-bufsize",
            f"{cap * 2}k",
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(OUTPUT_FPS * 2),
            "-c:a",
            "aac",
            "-b:a",
            f"{AUDIO_BITRATE_KBPS}k",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(out),
        ],
        desc=f"render clip {index} ({candidate.start:.1f}-{candidate.end:.1f}s)",
        timeout=1800,
    )

    size = out.stat().st_size
    if size > settings.max_clip_mb * 1_048_576:
        log.warning(
            "clip %d is %.1f MB, over the %d MB budget",
            index,
            size / 1_048_576,
            settings.max_clip_mb,
        )

    log.info(
        "rendered clip %d: %.1fs, %.1f MB, crop=%s via %s",
        index,
        duration,
        size / 1_048_576,
        "static" if plan.is_static else f"{len(plan.keyframes)} keyframes",
        plan.detector,
    )

    return RenderedClip(
        candidate=candidate,
        path=str(out),
        size_bytes=size,
        width=out_w,
        height=out_h,
        index=index,
    )


def render_clips(
    source: SourceMedia,
    candidates: list[ClipCandidate],
    transcript: Transcript,
    *,
    out_dir: str | Path,
    work_dir: str | Path,
    on_progress: ProgressFn | None = None,
) -> list[RenderedClip]:
    """Render each candidate, skipping over individual failures.

    One clip failing to encode should not lose the other nine; the job reports
    what it managed to produce.
    """
    rendered: list[RenderedClip] = []
    total = len(candidates)

    for i, candidate in enumerate(candidates, start=1):
        out_path = Path(out_dir) / f"clip-{i:02d}.mp4"
        try:
            rendered.append(
                render_clip(
                    source,
                    candidate,
                    transcript,
                    out_path=out_path,
                    index=i,
                    work_dir=work_dir,
                )
            )
        except Exception:  # noqa: BLE001 - logged, then move to the next clip
            log.exception("clip %d (%s) failed to render", i, candidate.title)
        if on_progress:
            on_progress(i / total if total else 1.0)

    return rendered
