"""Wires the stages together and owns progress reporting.

The only module that knows the pipeline order. Individual stages stay unaware
of each other and of how far along the job is.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from config import get_settings
from schemas import ClipCandidate, RenderedClip, SourceMedia, Stage, Transcript

from . import download as download_stage
from . import render as render_stage
from . import select as select_stage
from . import transcribe as transcribe_stage

log = logging.getLogger("clipviral.run")

# Global progress band per stage. The frontend renders a step list straight
# from this, so the bands must stay ordered and contiguous.
STAGE_PROGRESS: dict[Stage, tuple[float, float]] = {
    Stage.QUEUED: (0.0, 0.0),
    Stage.DOWNLOADING: (0.0, 0.25),
    Stage.TRANSCRIBING: (0.25, 0.45),
    Stage.SELECTING: (0.45, 0.55),
    Stage.RENDERING: (0.55, 0.92),
    Stage.UPLOADING: (0.92, 1.0),
    Stage.DONE: (1.0, 1.0),
}

# stage, fraction-within-stage, overall progress
UpdateFn = Callable[[Stage, float], None]
# Returns the URL the clip is reachable at.
UploadFn = Callable[[RenderedClip], str]


@dataclass
class JobResult:
    source: SourceMedia
    transcript: Transcript
    candidates: list[ClipCandidate]
    clips: list[RenderedClip] = field(default_factory=list)
    urls: dict[int, str] = field(default_factory=dict)
    work_dir: Path = Path(".")

    @property
    def candidates_path(self) -> Path:
        return self.work_dir / "candidates.json"


def overall_progress(stage: Stage, fraction: float) -> float:
    lo, hi = STAGE_PROGRESS.get(stage, (0.0, 1.0))
    return round(lo + (hi - lo) * max(0.0, min(1.0, fraction)), 4)


# Small text artifacts worth keeping for debugging and re-selection; everything
# else in a work dir is regenerable and heavy.
KEEP_FILES = {"candidates.json", "transcript.json"}


def cleanup_work(work_dir: str | Path, *, remove_clips: bool) -> int:
    """Delete a finished job's heavy intermediates, returning bytes freed.

    An hour of 1080p source is ~2 GB and the wav another ~0.5 GB, per job,
    forever -- a small VPS fills in days. ``remove_clips`` should be True only
    when the clips were uploaded to storage and the copies here are redundant.
    """
    work = Path(work_dir)
    if not work.is_dir():
        return 0

    freed = 0
    for entry in work.iterdir():
        if entry.name in KEEP_FILES:
            continue
        if entry.name == "clips" and not remove_clips:
            continue
        try:
            if entry.is_dir():
                freed += sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                shutil.rmtree(entry, ignore_errors=True)
            else:
                freed += entry.stat().st_size
                entry.unlink()
        except OSError:
            log.warning("could not remove %s during cleanup", entry, exc_info=True)

    log.info("cleaned %s, freed %.1f MB", work, freed / 1_048_576)
    return freed


def run_job(
    *,
    work_dir: str | Path,
    url: str | None = None,
    upload_path: str | Path | None = None,
    title: str | None = None,
    render: bool = True,
    uploader: UploadFn | None = None,
    on_update: UpdateFn | None = None,
) -> JobResult:
    """Run the pipeline end to end.

    Exactly one of ``url`` or ``upload_path`` must be given.
    """
    if bool(url) == bool(upload_path):
        raise ValueError("pass exactly one of url or upload_path")

    settings = get_settings()
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    clips_dir = work / "clips"

    def report(stage: Stage, fraction: float = 0.0) -> None:
        if on_update:
            on_update(stage, fraction)

    # --- download ---------------------------------------------------------
    report(Stage.DOWNLOADING, 0.0)
    if url:
        source = download_stage.download(
            url, work, on_progress=lambda f: report(Stage.DOWNLOADING, f)
        )
    else:
        source = download_stage.ingest_upload(upload_path, work, title=title)  # type: ignore[arg-type]
    report(Stage.DOWNLOADING, 1.0)
    log.info(
        "source ready: %r, %.1fs, %dx%d",
        source.title,
        source.duration,
        source.width,
        source.height,
    )

    # --- transcribe -------------------------------------------------------
    report(Stage.TRANSCRIBING, 0.0)
    transcript = transcribe_stage.transcribe(
        source.audio_path, on_progress=lambda f: report(Stage.TRANSCRIBING, f)
    )
    (work / "transcript.json").write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    report(Stage.TRANSCRIBING, 1.0)

    # --- select -----------------------------------------------------------
    report(Stage.SELECTING, 0.0)
    candidates = select_stage.select(
        transcript, on_progress=lambda f: report(Stage.SELECTING, f)
    )
    result = JobResult(
        source=source, transcript=transcript, candidates=candidates, work_dir=work
    )
    result.candidates_path.write_text(
        json.dumps([c.model_dump() for c in candidates], indent=2), encoding="utf-8"
    )
    report(Stage.SELECTING, 1.0)
    log.info("selected %d candidates → %s", len(candidates), result.candidates_path)

    if not render:
        return result

    # --- render -----------------------------------------------------------
    keepers = [c for c in candidates if c.hook_score >= settings.min_hook_score]
    dropped = len(candidates) - len(keepers)
    if dropped:
        log.info("skipping %d candidates below hook score %d", dropped, settings.min_hook_score)
    if not keepers:
        log.warning("no candidate cleared the minimum hook score; nothing to render")

    report(Stage.RENDERING, 0.0)
    result.clips = render_stage.render_clips(
        source,
        keepers,
        transcript,
        out_dir=clips_dir,
        work_dir=work / "tmp",
        on_progress=lambda f: report(Stage.RENDERING, f),
    )
    report(Stage.RENDERING, 1.0)

    # render_clips swallows per-clip failures so one bad cut cannot lose the
    # others. Losing *all* of them is a different thing and must not be
    # reported as a finished job with nothing in it -- that is indistinguishable
    # from "no moment cleared the bar", which is a legitimate result.
    if keepers and not result.clips:
        raise RuntimeError(
            f"all {len(keepers)} clips failed to render; see the ffmpeg errors above"
        )

    # --- upload -----------------------------------------------------------
    if uploader and result.clips:
        report(Stage.UPLOADING, 0.0)
        failed_uploads = 0
        for i, clip in enumerate(result.clips, start=1):
            # A transient storage error on clip 7 must not throw away clips 1-6,
            # which are already uploaded and are the expensive part of the job.
            try:
                result.urls[clip.index] = uploader(clip)
            except Exception:  # noqa: BLE001 - backend-specific, all recoverable
                failed_uploads += 1
                log.exception("uploading clip %d failed, continuing", clip.index)
            report(Stage.UPLOADING, i / len(result.clips))

        if failed_uploads == len(result.clips):
            raise RuntimeError(f"none of the {failed_uploads} clips could be uploaded")
        if failed_uploads:
            log.warning("%d of %d clips failed to upload", failed_uploads, len(result.clips))
            result.clips = [c for c in result.clips if c.index in result.urls]
    report(Stage.UPLOADING, 1.0)

    # Server jobs clean up after themselves; CLI runs (no uploader) keep
    # everything because they are the tuning loop and the source is expensive
    # to re-fetch. Clip copies here are redundant once every clip uploaded.
    if uploader and not settings.keep_work:
        all_uploaded = len(result.urls) == len(result.clips)
        cleanup_work(work, remove_clips=all_uploaded)

    return result
