"""Where rendered clips end up: local disk in development, R2 in production.

Both backends expose the same ``put`` returning a URL the frontend can use, so
nothing upstream branches on which one is configured.
"""

from __future__ import annotations

import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from config import get_settings

log = logging.getLogger("clipviral.storage")

PRESIGN_EXPIRY_SEC = 7 * 24 * 3600


class Storage(ABC):
    @abstractmethod
    def put(self, local_path: str | Path, key: str) -> str:
        """Store the file under ``key`` and return a URL for it."""

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """Remove everything stored under ``prefix/``, returning files removed."""

    def local_path(self, key: str) -> Path | None:
        """On-disk location, when the backend has one."""
        return None


class LocalStorage(Storage):
    """Copies clips under ``STORAGE_DIR``; the API serves them from /files."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, local_path: str | Path, key: str) -> str:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = Path(local_path)
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        log.info("stored %s locally (%.1f MB)", key, dest.stat().st_size / 1_048_576)
        return f"/files/{key}"

    def local_path(self, key: str) -> Path | None:
        candidate = (self.root / key).resolve()
        # Guard against a crafted key climbing out of the storage root.
        if not candidate.is_relative_to(self.root.resolve()):
            return None
        return candidate if candidate.is_file() else None

    def delete_prefix(self, prefix: str) -> int:
        target = (self.root / prefix).resolve()
        if not target.is_relative_to(self.root.resolve()) or not target.is_dir():
            return 0
        count = sum(1 for f in target.rglob("*") if f.is_file())
        shutil.rmtree(target, ignore_errors=True)
        log.info("deleted %d file(s) under %s", count, prefix)
        return count


class R2Storage(Storage):
    """Cloudflare R2 over the S3 API."""

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        settings = get_settings()
        missing = [
            name
            for name, value in (
                ("R2_ACCOUNT_ID", settings.r2_account_id),
                ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
                ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"STORAGE_BACKEND=r2 but {', '.join(missing)} not set"
            )

        self.bucket = settings.r2_bucket
        self.public_base = settings.r2_public_base_url
        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            region_name="auto",
        )

    def put(self, local_path: str | Path, key: str) -> str:
        self.client.upload_file(
            str(local_path),
            self.bucket,
            key,
            ExtraArgs={"ContentType": "video/mp4"},
        )
        log.info("uploaded %s to r2://%s", key, self.bucket)

        if self.public_base:
            return f"{self.public_base}/{key}"
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=PRESIGN_EXPIRY_SEC,
        )

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{prefix}/"):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if not keys:
                continue
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
            deleted += len(keys)
        log.info("deleted %d object(s) under r2://%s/%s/", deleted, self.bucket, prefix)
        return deleted


def get_storage() -> Storage:
    settings = get_settings()
    if settings.uses_r2:
        return R2Storage()
    return LocalStorage(settings.storage_dir)
