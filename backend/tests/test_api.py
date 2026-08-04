"""API surface tests.

The pipeline itself is exercised by ``cli.py`` runs, not here -- these cover
request validation, error shapes and the job lifecycle around it.
"""

from __future__ import annotations

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
        job_id = client.post("/jobs", json={"youtube_url": "https://x.com/v"}).json()["id"]

        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        assert response.json()["id"] == job_id

    def test_new_job_has_no_clips(self, client):
        job_id = client.post("/jobs", json={"youtube_url": "https://x.com/v"}).json()["id"]
        assert client.get(f"/jobs/{job_id}/clips").json() == []

    def test_listing_is_newest_first(self, client):
        first = client.post("/jobs", json={"youtube_url": "https://x.com/1"}).json()["id"]
        second = client.post("/jobs", json={"youtube_url": "https://x.com/2"}).json()["id"]

        ids = [j["id"] for j in client.get("/jobs?limit=50").json()]
        assert ids.index(second) < ids.index(first)


class TestFiles:
    def test_path_traversal_is_rejected(self, client):
        assert client.get("/files/..%2f..%2fetc/passwd").status_code in (400, 404)

    def test_unknown_file_is_404(self, client):
        assert client.get("/files/abc123/clip-01.mp4").status_code == 404


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
