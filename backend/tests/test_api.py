"""API surface tests.

The pipeline itself is exercised by ``cli.py`` runs, not here -- these cover
request validation, error shapes and the job lifecycle around it.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

import main
from models import Job, init_db, new_id, session_scope
from schemas import JobStatus, Stage


@pytest.fixture
def client(monkeypatch):
    # Keep POST /jobs from actually running a render during the tests.
    monkeypatch.setattr(main, "_process_job", lambda job_id: None)
    init_db()
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def blocked_queue(monkeypatch):
    """Hold every submitted job open so the queue actually fills up.

    Request this *after* ``client``: the client fixture patches ``_process_job``
    too, and whichever runs last wins.
    """
    gate = threading.Event()
    monkeypatch.setattr(main, "_process_job", lambda job_id: gate.wait(10))
    yield gate
    gate.set()
    # The counter is module state and the releases happen on the pool thread,
    # so leaving it to drain on its own would bleed into the next test.
    main.shutdown_job_pool()
    with main._queue_lock:
        main._queued = 0


class TestHealth:
    def test_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestCreateJob:
    def test_accepts_a_url(self, client):
        response = client.post("/jobs", json={"youtube_url": "https://youtube.com/watch?v=abc"})

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == JobStatus.QUEUED
        assert body["stage"] == Stage.QUEUED
        assert body["progress"] == 0.0
        assert body["clip_count"] == 0

    def test_rejects_a_missing_url(self, client):
        assert client.post("/jobs", json={}).status_code == 400

    def test_rejects_a_non_http_url(self, client):
        response = client.post("/jobs", json={"youtube_url": "file:///etc/passwd"})
        assert response.status_code == 400

    def test_rejects_an_internal_host(self, client):
        # Whatever reaches this endpoint is handed to yt-dlp, which will fetch
        # anything the container can reach. test_source_url.py covers the rule
        # itself; this checks the route is actually wired to it.
        response = client.post("/jobs", json={"youtube_url": "http://169.254.169.254/latest/"})
        assert response.status_code == 400

    def test_a_full_queue_is_refused_rather_than_promised(self, client, blocked_queue):
        # Jobs render one at a time, so an unbounded queue means accepting work
        # that will not start for days while still answering 201.
        from config import get_settings

        limit = get_settings().max_queued_jobs
        body = {"youtube_url": "https://youtube.com/watch?v=abc"}

        accepted = [client.post("/jobs", json=body).status_code for _ in range(limit)]
        assert accepted == [201] * limit

        overflow = client.post("/jobs", json=body)
        assert overflow.status_code == 503

    def test_a_rejected_submission_does_not_consume_a_slot(self, client, blocked_queue):
        # Otherwise a client sending bad requests permanently shrinks the queue.
        from config import get_settings

        for _ in range(get_settings().max_queued_jobs + 5):
            assert client.post("/jobs", json={"youtube_url": "nope"}).status_code == 400

        good = client.post("/jobs", json={"youtube_url": "https://youtube.com/watch?v=abc"})
        assert good.status_code == 201

    def test_an_oversized_json_body_is_refused_before_it_is_parsed(self, client):
        # request.json() buffers the whole body in memory, so without a cap a
        # single POST sets the process's resident set.
        payload = {"youtube_url": "https://youtube.com/watch?v=abc", "pad": "x" * 200_000}
        assert client.post("/jobs", json=payload).status_code == 413

    def test_a_normal_json_body_still_passes(self, client):
        response = client.post("/jobs", json={"youtube_url": "https://youtube.com/watch?v=abc"})
        assert response.status_code == 201

    def test_rejects_an_unknown_content_type(self, client):
        response = client.post("/jobs", content="raw", headers={"Content-Type": "text/plain"})
        assert response.status_code == 415

    def test_rejects_an_unsupported_upload(self, client):
        response = client.post("/jobs", files={"file": ("notes.txt", b"hello", "text/plain")})
        assert response.status_code == 400

    def test_rejects_an_empty_upload(self, client):
        response = client.post("/jobs", files={"file": ("clip.mp4", b"", "video/mp4")})
        assert response.status_code == 400

    def test_accepts_a_video_upload(self, client):
        response = client.post("/jobs", files={"file": ("talk.mp4", b"\x00" * 2048, "video/mp4")})

        assert response.status_code == 201
        assert response.json()["source_title"] == "talk"


class TestReadJob:
    def test_unknown_job_is_404(self, client):
        assert client.get("/jobs/does-not-exist").status_code == 404

    def test_unknown_job_clips_is_404(self, client):
        assert client.get("/jobs/does-not-exist/clips").status_code == 404

    def test_round_trips_a_created_job(self, client):
        job_id = client.post("/jobs", json={"youtube_url": "https://youtube.com/watch?v=aaa"}).json()["id"]

        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        assert response.json()["id"] == job_id

    def test_new_job_has_no_clips(self, client):
        job_id = client.post("/jobs", json={"youtube_url": "https://youtube.com/watch?v=aaa"}).json()["id"]
        assert client.get(f"/jobs/{job_id}/clips").json() == []

    def test_listing_is_newest_first(self, client):
        first = client.post("/jobs", json={"youtube_url": "https://youtube.com/watch?v=one"}).json()["id"]
        second = client.post("/jobs", json={"youtube_url": "https://youtube.com/watch?v=two"}).json()["id"]

        ids = [j["id"] for j in client.get("/jobs?limit=50").json()]
        assert ids.index(second) < ids.index(first)


class TestFiles:
    def test_path_traversal_is_rejected(self, client):
        assert client.get("/files/..%2f..%2fetc/passwd").status_code in (400, 404)

    def test_unknown_file_is_404(self, client):
        assert client.get("/files/abc123/clip-01.mp4").status_code == 404


class TestDeleteJob:
    def test_unknown_job_is_404(self, client):
        assert client.delete("/jobs/does-not-exist").status_code == 404

    def test_running_job_is_refused(self, client):
        job_id = new_id()
        with session_scope() as session:
            session.add(
                Job(id=job_id, status=JobStatus.RUNNING, stage=Stage.RENDERING, progress=0.5)
            )

        assert client.delete(f"/jobs/{job_id}").status_code == 409
        assert client.get(f"/jobs/{job_id}").status_code == 200

    def test_delete_removes_job_and_files(self, client):
        from config import get_settings
        from storage import get_storage

        job_id = client.post("/jobs", json={"youtube_url": "https://youtube.com/watch?v=aaa"}).json()["id"]

        # Simulate what a finished job leaves on disk.
        storage = get_storage()
        src = get_settings().work_dir / "seed.mp4"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"\x00" * 64)
        storage.put(src, f"{job_id}/clip-01.mp4")
        work_dir = get_settings().work_dir / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "source.mp4").write_bytes(b"\x00" * 64)

        assert client.delete(f"/jobs/{job_id}").status_code == 204

        assert client.get(f"/jobs/{job_id}").status_code == 404
        assert storage.local_path(f"{job_id}/clip-01.mp4") is None
        assert not work_dir.exists()

    def test_delete_cascades_to_clip_rows(self, client):
        from models import Clip

        job_id = client.post("/jobs", json={"youtube_url": "https://youtube.com/watch?v=aaa"}).json()["id"]
        with session_scope() as session:
            session.add(
                Clip(
                    job_id=job_id,
                    title="t",
                    hook_score=8,
                    reason="r",
                    start=0.0,
                    end=25.0,
                    url="/files/x/clip-01.mp4",
                    index=1,
                )
            )

        assert client.delete(f"/jobs/{job_id}").status_code == 204
        with session_scope() as session:
            assert session.query(Clip).filter(Clip.job_id == job_id).count() == 0


class TestOrphanRecovery:
    def test_running_jobs_are_failed_on_boot(self, client):
        job_id = new_id()
        with session_scope() as session:
            session.add(
                Job(id=job_id, status=JobStatus.RUNNING, stage=Stage.RENDERING, progress=0.6)
            )

        main._fail_orphaned_jobs()

        body = client.get(f"/jobs/{job_id}").json()
        assert body["status"] == JobStatus.FAILED
        assert "restart" in (body["error"] or "").lower()
