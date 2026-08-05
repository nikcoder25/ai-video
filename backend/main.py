"""ClipViral HTTP API.

Jobs run in FastAPI ``BackgroundTasks`` -- the Phase 1 shortcut. Rendering is
CPU-bound, so a semaphore keeps one job encoding at a time instead of letting
four concurrent uploads fight over the same cores. When that stops being
enough, this is the seam where Celery goes.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from config import get_settings
from models import Clip, Job, init_db, new_id, session_scope
from pipeline.run import cleanup_work, overall_progress, run_job
from schemas import ClipOut, JobOut, JobStatus, RenderedClip, Stage
from source_url import InvalidSourceUrl, normalize_source_url
from storage import LocalStorage, get_storage

log = logging.getLogger("clipviral.api")

settings = get_settings()

# One render at a time. Raising this without moving to a real queue just makes
# every concurrent job slower rather than any of them finish sooner.
RENDER_SLOTS = threading.Semaphore(1)

# No `.` on its own: the class already contains it, so a bare `..` matched and
# the only thing stopping traversal was the containment check below it.
SAFE_NAME = re.compile(r"^(?!\.+$)[A-Za-z0-9._-]+$")
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )
    init_db()
    _fail_orphaned_jobs()
    log.info(
        "ClipViral API up (storage=%s, mock=%s)", settings.storage_backend, settings.mock
    )
    yield


app = FastAPI(title="ClipViral", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _fail_orphaned_jobs() -> None:
    """Jobs left ``running`` by a restart can never resume -- mark them failed.

    BackgroundTasks live in the process, so a crash loses the work entirely.
    Leaving the row as `running` would strand the frontend polling forever.
    """
    with session_scope() as session:
        stale = session.query(Job).filter(Job.status == JobStatus.RUNNING).all()
        for job in stale:
            job.status = JobStatus.FAILED
            job.stage = Stage.FAILED
            job.error = "Server restarted while this job was running. Submit it again."
        if stale:
            log.warning("failed %d job(s) orphaned by a restart", len(stale))


# --- job execution ----------------------------------------------------------


def _mark_failed(job_id: str, message: str) -> None:
    """Move a job to a terminal state. Never raises -- the caller is already
    handling one failure and a second would leave the job stuck ``running``."""
    try:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.FAILED
                job.stage = Stage.FAILED
                job.error = message[:1000]
                job.updated_at = datetime.now(UTC)
    except Exception:  # noqa: BLE001
        log.exception("could not record failure for job %s", job_id)


def _process_job(job_id: str) -> None:
    settings = get_settings()
    work_dir = settings.work_dir / job_id
    storage = get_storage()

    last_written = {"progress": -1.0, "stage": ""}

    def on_update(stage: Stage, fraction: float) -> None:
        progress = overall_progress(stage, fraction)
        # Throttle writes: progress ticks arrive far faster than any UI needs.
        if stage.value == last_written["stage"] and progress - last_written["progress"] < 0.01:
            return
        last_written["stage"] = stage.value
        last_written["progress"] = progress
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            job.stage = stage
            job.progress = progress
            job.status = JobStatus.RUNNING
            job.updated_at = datetime.now(UTC)

    def upload(clip: RenderedClip) -> str:
        return storage.put(clip.path, f"{job_id}/{Path(clip.path).name}")

    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            log.error("job %s vanished before it started", job_id)
            return
        url = job.source_url
        upload_path = job.upload_path
        title = job.source_title

    with RENDER_SLOTS:
        # The result write is inside this block too. If it were outside, a
        # failure there (disk full, database locked) would leave the job stuck
        # in `running` forever: the poller never stops and DELETE returns 409
        # until someone restarts the process.
        try:
            result = run_job(
                work_dir=work_dir,
                url=url if not upload_path else None,
                upload_path=upload_path,
                title=title,
                render=True,
                uploader=upload,
                on_update=on_update,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the client
            log.exception("job %s failed", job_id)
            _mark_failed(job_id, str(exc))
            # A failed job's partial downloads and renders are unreachable by
            # the user (clips are served from storage, not the work dir), so
            # only KEEP_WORK justifies keeping gigabytes of them.
            if not settings.keep_work:
                cleanup_work(work_dir, remove_clips=True)
            return

        try:
            with session_scope() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return
                job.source_title = result.source.title
                job.duration = result.source.duration
                for clip in result.clips:
                    session.add(
                        Clip(
                            id=new_id(),
                            job_id=job_id,
                            title=clip.candidate.title,
                            hook_score=clip.candidate.hook_score,
                            reason=clip.candidate.reason,
                            start=clip.candidate.start,
                            end=clip.candidate.end,
                            url=result.urls.get(clip.index, ""),
                            size_bytes=clip.size_bytes,
                            width=clip.width,
                            height=clip.height,
                            index=clip.index,
                        )
                    )
                job.status = JobStatus.DONE
                job.stage = Stage.DONE
                job.progress = 1.0
                job.updated_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001 - must not leave the job running
            log.exception("job %s rendered but could not be recorded", job_id)
            _mark_failed(job_id, f"clips rendered but could not be saved: {exc}")
            return

    log.info("job %s done: %d clips", job_id, len(result.clips))


# --- routes -----------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs", response_model=JobOut, status_code=201)
async def create_job(request: Request, background: BackgroundTasks) -> JobOut:
    """Accepts either ``{"youtube_url": ...}`` JSON or a multipart upload."""
    content_type = request.headers.get("content-type", "")
    job_id = new_id()
    source_url: str | None = None
    upload_path: str | None = None
    title: str | None = None

    if content_type.startswith("application/json"):
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Body was not valid JSON") from None
        raw_url = (payload or {}).get("youtube_url") or (payload or {}).get("url")
        if not raw_url or not isinstance(raw_url, str):
            raise HTTPException(400, "Provide a YouTube URL in `youtube_url`")
        try:
            source_url = normalize_source_url(raw_url)
        except InvalidSourceUrl as exc:
            raise HTTPException(400, str(exc)) from None

    elif content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "filename"):
            raise HTTPException(400, "Attach a video as the `file` field")

        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in VIDEO_SUFFIXES:
            raise HTTPException(
                400, f"Unsupported file type {suffix or '(none)'}. Use mp4, mov, mkv or webm."
            )

        dest_dir = settings.work_dir / job_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"upload{suffix}"
        limit = settings.max_upload_mb * 1_048_576
        written = 0

        # Streamed to disk in chunks -- a 2 GB upload must never be a 2 GB
        # bytes object in the worker process.
        with dest.open("wb") as fh:
            while chunk := await upload.read(1_048_576):
                written += len(chunk)
                if written > limit:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")
                fh.write(chunk)

        if written == 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "Uploaded file was empty")

        upload_path = str(dest)
        title = Path(upload.filename or "upload").stem
    else:
        raise HTTPException(
            415, "Send application/json with `youtube_url`, or multipart/form-data with `file`"
        )

    with session_scope() as session:
        job = Job(
            id=job_id,
            status=JobStatus.QUEUED,
            stage=Stage.QUEUED,
            progress=0.0,
            source_url=source_url,
            upload_path=upload_path,
            source_title=title,
        )
        session.add(job)
        session.flush()
        out = job.to_schema()

    background.add_task(_process_job, job_id)
    log.info("queued job %s (%s)", job_id, source_url or upload_path)
    return out


@app.get("/jobs", response_model=list[JobOut])
def list_jobs(limit: int = 20) -> list[JobOut]:
    limit = max(1, min(100, limit))
    with session_scope() as session:
        jobs = session.query(Job).order_by(Job.created_at.desc()).limit(limit).all()
        return [j.to_schema() for j in jobs]


@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "No such job")
        return job.to_schema()


@app.get("/jobs/{job_id}/clips", response_model=list[ClipOut])
def get_clips(job_id: str) -> list[ClipOut]:
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "No such job")
        return [c.to_schema() for c in job.clips]


@app.delete("/jobs/{job_id}", status_code=204, response_class=Response)
def delete_job(job_id: str) -> Response:
    """Remove a job, its clips, its stored files, and any work-dir leftovers."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "No such job")
        if job.status == JobStatus.RUNNING:
            # The pipeline holds open file handles into these directories; a
            # concurrent delete would fail the render in a confusing way.
            raise HTTPException(409, "Job is still running; try again when it finishes")
        session.delete(job)  # clips cascade

    if SAFE_NAME.match(job_id):
        get_storage().delete_prefix(job_id)
        work_dir = settings.work_dir / job_id
        if work_dir.is_dir():
            shutil.rmtree(work_dir, ignore_errors=True)

    log.info("deleted job %s", job_id)
    return Response(status_code=204)


@app.get("/files/{job_id}/{name}")
def get_file(job_id: str, name: str) -> FileResponse:
    if not SAFE_NAME.match(job_id) or not SAFE_NAME.match(name):
        raise HTTPException(400, "Bad path")

    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise HTTPException(404, "Files are served from object storage in this deployment")

    path = storage.local_path(f"{job_id}/{name}")
    if path is None:
        raise HTTPException(404, "No such file")
    return FileResponse(path, media_type="video/mp4", filename=name)
