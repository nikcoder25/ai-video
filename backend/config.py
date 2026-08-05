"""Runtime configuration, read once from the environment.

Everything tunable lives here so no other module reads ``os.environ`` directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _num(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _path(name: str, default: str) -> Path:
    raw = os.getenv(name, default)
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


@dataclass(frozen=True)
class Settings:
    deepgram_api_key: str
    anthropic_api_key: str
    select_model: str

    storage_backend: str
    storage_dir: Path
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket: str
    r2_public_base_url: str

    database_url: str
    work_dir: Path
    max_upload_mb: int
    max_source_sec: float
    cors_origins: tuple[str, ...]

    mock: bool
    keep_work: bool

    clip_min_sec: float
    clip_max_sec: float
    target_clip_count: int
    min_hook_score: int
    render_width: int
    render_height: int
    max_clip_mb: int

    ffmpeg_bin: str
    ffprobe_bin: str

    @property
    def uses_r2(self) -> bool:
        return self.storage_backend.lower() == "r2"

    @property
    def max_source_bytes(self) -> int:
        return self.max_upload_mb * 1_048_576

    def require_deepgram(self) -> str:
        if not self.deepgram_api_key:
            raise RuntimeError(
                "DEEPGRAM_API_KEY is not set. Set it in .env, or run with MOCK=1 "
                "to use fixture transcripts."
            )
        return self.deepgram_api_key

    def require_anthropic(self) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Set it in .env, or run with MOCK=1 "
                "to use fixture clip candidates."
            )
        return self.anthropic_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Both spellings of loopback: a browser sent to 127.0.0.1 sends that as its
    # Origin, and allowing only "localhost" silently fails every request.
    origins = os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    return Settings(
        deepgram_api_key=os.getenv("DEEPGRAM_API_KEY", "").strip(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        select_model=os.getenv("SELECT_MODEL", "claude-sonnet-5").strip(),
        storage_backend=os.getenv("STORAGE_BACKEND", "local").strip(),
        storage_dir=_path("STORAGE_DIR", "./data/clips"),
        r2_account_id=os.getenv("R2_ACCOUNT_ID", "").strip(),
        r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        r2_bucket=os.getenv("R2_BUCKET", "clipviral").strip(),
        r2_public_base_url=os.getenv("R2_PUBLIC_BASE_URL", "").strip().rstrip("/"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/clipviral.db"),
        work_dir=_path("WORK_DIR", "./work"),
        max_upload_mb=int(_num("MAX_UPLOAD_MB", 2048)),
        # Transcription and selection are both billed per minute of source, and
        # the render slot is single-file, so an unbounded source is unbounded
        # spend and an unbounded queue. Four hours covers any real podcast.
        max_source_sec=_num("MAX_SOURCE_SEC", 4 * 3600),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        mock=_flag("MOCK"),
        keep_work=_flag("KEEP_WORK"),
        clip_min_sec=_num("CLIP_MIN_SEC", 20.0),
        clip_max_sec=_num("CLIP_MAX_SEC", 58.0),
        target_clip_count=int(_num("TARGET_CLIP_COUNT", 10)),
        min_hook_score=int(_num("MIN_HOOK_SCORE", 6)),
        render_width=int(_num("RENDER_WIDTH", 1080)),
        render_height=int(_num("RENDER_HEIGHT", 1920)),
        max_clip_mb=int(_num("MAX_CLIP_MB", 50)),
        ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
        ffprobe_bin=os.getenv("FFPROBE_BIN", "ffprobe"),
    )
