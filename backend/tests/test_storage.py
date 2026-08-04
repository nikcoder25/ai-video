from __future__ import annotations

import pytest

from storage import LocalStorage, R2Storage, get_storage


class TestLocalStorage:
    def test_put_returns_a_servable_url(self, tmp_root):
        root = tmp_root / "store-a"
        src = tmp_root / "clip.mp4"
        src.write_bytes(b"\x00" * 32)

        url = LocalStorage(root).put(src, "job123/clip-01.mp4")

        assert url == "/files/job123/clip-01.mp4"
        assert (root / "job123" / "clip-01.mp4").read_bytes() == b"\x00" * 32

    def test_local_path_round_trips(self, tmp_root):
        root = tmp_root / "store-b"
        storage = LocalStorage(root)
        src = tmp_root / "clip2.mp4"
        src.write_bytes(b"data")
        storage.put(src, "job/clip.mp4")

        assert storage.local_path("job/clip.mp4") is not None

    def test_missing_file_is_none(self, tmp_root):
        assert LocalStorage(tmp_root / "store-c").local_path("nope/none.mp4") is None

    def test_traversal_key_is_refused(self, tmp_root):
        root = tmp_root / "store-d"
        storage = LocalStorage(root)
        (tmp_root / "secret.txt").write_text("private")

        # Even though the target exists, it is outside the storage root.
        assert storage.local_path("../secret.txt") is None

    def test_creates_its_root(self, tmp_root):
        root = tmp_root / "store-e" / "nested"
        LocalStorage(root)
        assert root.is_dir()


class TestR2Storage:
    def test_missing_credentials_names_them(self, monkeypatch):
        import config

        monkeypatch.setenv("STORAGE_BACKEND", "r2")
        monkeypatch.setenv("R2_ACCOUNT_ID", "")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "")
        config.get_settings.cache_clear()

        with pytest.raises(RuntimeError) as exc:
            R2Storage()

        message = str(exc.value)
        assert "R2_ACCOUNT_ID" in message
        assert "R2_ACCESS_KEY_ID" in message

        config.get_settings.cache_clear()


class TestBackendSelection:
    def test_defaults_to_local(self):
        assert isinstance(get_storage(), LocalStorage)
