from __future__ import annotations

from pathlib import Path

from pipeline.run import cleanup_work


def _make_work(root: Path) -> Path:
    work = root / "jobwork"
    (work / "tmp").mkdir(parents=True, exist_ok=True)
    (work / "clips").mkdir(exist_ok=True)
    (work / "source.mp4").write_bytes(b"\x00" * 4096)
    (work / "audio.wav").write_bytes(b"\x00" * 2048)
    (work / "tmp" / "clip-01.ass").write_text("styles")
    (work / "clips" / "clip-01.mp4").write_bytes(b"\x00" * 1024)
    (work / "candidates.json").write_text("[]")
    (work / "transcript.json").write_text("{}")
    return work


class TestCleanupWork:
    def test_removes_heavy_files_keeps_artifacts(self, tmp_root):
        work = _make_work(tmp_root / "a")

        freed = cleanup_work(work, remove_clips=True)

        assert not (work / "source.mp4").exists()
        assert not (work / "audio.wav").exists()
        assert not (work / "tmp").exists()
        assert not (work / "clips").exists()
        assert (work / "candidates.json").exists()
        assert (work / "transcript.json").exists()
        assert freed == 4096 + 2048 + len(b"styles") + 1024

    def test_keeps_clips_when_asked(self, tmp_root):
        work = _make_work(tmp_root / "b")

        cleanup_work(work, remove_clips=False)

        assert (work / "clips" / "clip-01.mp4").exists()
        assert not (work / "source.mp4").exists()

    def test_missing_dir_is_a_noop(self, tmp_root):
        assert cleanup_work(tmp_root / "does-not-exist", remove_clips=True) == 0


class TestOrphanSweep:
    """Work dirs stranded by a crash, reclaimed at the next boot."""

    def test_reclaims_the_heavy_files_of_an_unknown_job(self, tmp_root):
        import main

        work = tmp_root / "work"
        orphan = work / "deadbeef"
        orphan.mkdir(parents=True)
        (orphan / "source.mp4").write_bytes(b"\x00" * 4096)
        (orphan / "audio.wav").write_bytes(b"\x00" * 4096)

        main._sweep_orphaned_work_dirs(set(), work)

        assert not (orphan / "source.mp4").exists()
        assert not (orphan / "audio.wav").exists()

    def test_leaves_a_known_job_untouched(self, tmp_root):
        import main

        work = tmp_root / "work"
        live = work / "abc123"
        live.mkdir(parents=True)
        (live / "source.mp4").write_bytes(b"\x00" * 4096)

        main._sweep_orphaned_work_dirs({"abc123"}, work)

        assert (live / "source.mp4").exists()

    def test_keeps_cli_tuning_artifacts(self, tmp_root):
        # cli.py never writes a database row, so every CLI run looks orphaned
        # from here. Its candidates.json is the reason the run existed.
        import main

        work = tmp_root / "work"
        cli_run = work / "manualrun"
        cli_run.mkdir(parents=True)
        (cli_run / "source.mp4").write_bytes(b"\x00" * 4096)
        (cli_run / "candidates.json").write_text("[]", encoding="utf-8")
        (cli_run / "transcript.json").write_text("{}", encoding="utf-8")

        main._sweep_orphaned_work_dirs(set(), work)

        assert not (cli_run / "source.mp4").exists()
        assert (cli_run / "candidates.json").exists()
        assert (cli_run / "transcript.json").exists()
