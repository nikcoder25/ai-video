"""Job and clip persistence.

SQLite by default. The column types stay portable so swapping DATABASE_URL to
Postgres is a config change, not a migration project.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from config import get_settings
from schemas import ClipOut, JobOut, JobStatus, Stage


def _now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED, index=True)
    stage: Mapped[str] = mapped_column(String(16), default=Stage.QUEUED)
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    source_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    upload_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    clips: Mapped[list[Clip]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="Clip.index"
    )

    def to_schema(self) -> JobOut:
        return JobOut(
            id=self.id,
            status=JobStatus(self.status),
            stage=Stage(self.stage),
            progress=self.progress,
            source_title=self.source_title,
            source_url=self.source_url,
            duration=self.duration,
            clip_count=len(self.clips),
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(String(300))
    hook_score: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    url: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    index: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    job: Mapped[Job] = relationship(back_populates="clips")

    def to_schema(self) -> ClipOut:
        return ClipOut(
            id=self.id,
            job_id=self.job_id,
            title=self.title,
            hook_score=self.hook_score,
            reason=self.reason,
            start=self.start,
            end=self.end,
            duration=round(self.end - self.start, 3),
            url=self.url,
            size_bytes=self.size_bytes,
            width=self.width,
            height=self.height,
            index=self.index,
        )


_settings = get_settings()
_url = _settings.database_url
if _url.startswith("sqlite"):
    # Resolve the sqlite file relative to the repo, and create its directory --
    # SQLite will not make a missing parent and fails with a confusing error.
    prefix, _, tail = _url.partition(":///")
    if tail and not tail.startswith("/"):
        resolved = (Path(__file__).resolve().parent.parent / tail).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        _url = f"{prefix}:///{resolved}"

engine = create_engine(
    _url,
    # BackgroundTasks run on worker threads, so the connection must be shareable.
    connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
