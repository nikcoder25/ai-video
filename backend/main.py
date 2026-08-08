"""ClipViral HTTP API.

Jobs run on a dedicated single-thread pool -- the Phase 1 shortcut, and the
seam where Celery goes later. Rendering is CPU-bound, so one worker keeps a
single job encoding at a time instead of letting four concurrent uploads fight
over the same cores.

Deliberately *not* FastAPI ``BackgroundTasks``: those execute on the same
anyio thread pool that serves every sync route, and a job holds its thread for
the entire render. Forty submitted jobs would consume the default 40 tokens and
freeze every endpoint including ``/health``, which then fails the container
healthcheck. Keeping jobs on their own pool means a full job queue slows down
nothing but the queue.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
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
# every concurrent job slower rather than any of them finish sooner -- the
# single worker *is* the serialisation, so no separate lock is needed.
_pool_lock = threading.Lock()
_job_pool: ThreadPoolExecutor | None = None


def job_pool() -> ThreadPoolExecutor:
    """The worker, created on demand.

    Built lazily rather than at import so that shutting the app down and
    starting it again in the same process -- which every API test does -- gets
    a live pool instead of one that refuses work forever.
    """
    global _job_pool
    with _pool_lock:
        if _job_pool is None:
            _job_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipviral-job")
        return _job_pool


def shutdown_job_pool() -> None:
    global _job_pool
    with _pool_lock:
        pool, _job_pool = _job_pool, None
    if pool is not None:
        # Don't wait: the container gets ~10s before SIGKILL and a render takes
        # minutes. _fail_orphaned_jobs picks the interrupted job up next boot.
        pool.shutdown(wait=False, cancel_futures=True)


# The pool's own queue is unbounded, so without this a client can enqueue work
# faster than it drains and build a backlog measured in days while every
# submission still returns 201.
_queue_lock = threading.Lock()
_queued = 0


def _reserve_queue_slot() -> bool:
    global _queued
    with _queue_lock:
        if _queued >= settings.max_queued_jobs:
            return False
        _queued += 1
        return True


def _release_queue_slot() -> None:
    global _queued
    with _queue_lock:
        _queued = max(0, _queued - 1)


# No `.` on its own: the class already contains it, so a bare `..` matched and
# the only thing stopping traversal was the containment check below it.
SAFE_NAME = re.compile(r"^(?!\.+$)[A-Za-z0-9._-]+$")
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}

# The JSON body carries one URL. Uploads are the multipart branch, and they
# stream to disk; this side is parsed in memory, so it needs its own ceiling --
# without one, a single large POST becomes the process's resident set.
MAX_JSON_BODY = 64 * 1024


async def _read_capped(request: Request, limit: int) -> bytes:
    """Read a request body, refusing it once it exceeds ``limit``.

    Reads the stream rather than trusting Content-Length, which is absent under
    chunked transfer encoding and is attacker-supplied in any case.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"Request body exceeds {limit // 1024} KB")
        chunks.append(chunk)
    return b"".join(chunks)


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
    shutdown_job_pool()


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
        known = {job_id for (job_id,) in session.query(Job.id).all()}

    _sweep_orphaned_work_dirs(known, settings.work_dir)


def _sweep_orphaned_work_dirs(known_job_ids: set[str], root: Path) -> None:
    """Reclaim the heavy files in work directories with no job behind them.

    Cleanup normally happens in-process when a job finishes, so anything that
    kills the process mid-job -- a deploy, an OOM, a crash -- strands the source
    video and its wav, which for a long podcast is several gigabytes each time.
    Nothing else ever revisits them, so boot is the only chance to notice.

    Deliberately ``cleanup_work`` rather than ``rmtree``: ``cli.py`` writes into
    this same root and never creates a database row, so every CLI run looks
    orphaned from here. Those runs are the prompt-tuning loop, and their
    candidates.json is the whole point of them -- so this takes the regenerable
    gigabytes and leaves the artifacts alone.
    """
    if not root.is_dir():
        return

    freed = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name in known_job_ids:
            continue
        freed += cleanup_work(entry, remove_clips=False)
    if freed:
        log.warning("swept %.1f MB from orphaned work directories", freed / 1_048_576)


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


def _run_queued_job(job_id: str) -> None:
    """Pool entry point. Releases the queue slot however the job ends.

    Separate from :func:`_process_job` so the slot is returned even when the
    job body is swapped out, which is what the API tests do.
    """
    try:
        _process_job(job_id)
    finally:
        _release_queue_slot()


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

    # The result write is in the same try-scope as the render. If it were
    # outside, a failure there (disk full, database locked) would leave the
    # job stuck in `running` forever: the poller never stops and DELETE
    # returns 409 until someone restarts the process.
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
async def create_job(request: Request) -> JobOut:
    """Accepts either ``{"youtube_url": ...}`` JSON or a multipart upload."""
    content_type = request.headers.get("content-type", "")
    job_id = new_id()

    # Claimed before the upload is read, so a full queue is rejected without
    # first spending bandwidth and disk on a file that would only sit there.
    if not _reserve_queue_slot():
        raise HTTPException(
            503, "Too many jobs are already queued. Try again in a few minutes."
        )
    submitted = False
    try:
        source_url: str | None = None
        upload_path: str | None = None
        title: str | None = None

        if content_type.startswith("application/json"):
            try:
                payload = json.loads(await _read_capped(request, MAX_JSON_BODY))
            except HTTPException:
                raise
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

        job_pool().submit(_run_queued_job, job_id)
        submitted = True
        log.info("queued job %s (%s)", job_id, source_url or upload_path)
        return out
    finally:
        # Any path that does not reach the pool has to give the slot back,
        # and take its half-written upload with it. Without this a rejected
        # or abandoned upload leaks a queue slot permanently, and leaves a
        # file on disk with no database row -- which means neither DELETE
        # nor cleanup_work can ever find it again.
        if not submitted:
            _release_queue_slot()
            shutil.rmtree(settings.work_dir / job_id, ignore_errors=True)


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
