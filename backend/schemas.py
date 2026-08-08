"""Shared data shapes.

Every timestamp in this file is seconds as a float, per CLAUDE.md. Nothing here
stores a formatted time string; formatting happens at the display edge only.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Stage(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    SELECTING = "selecting"
    RENDERING = "rendering"
    UPLOADING = "uploading"
    DONE = "done"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# --- pipeline types ---------------------------------------------------------


class Word(BaseModel):
    word: str
    start: float
    end: float
    speaker: int | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class Transcript(BaseModel):
    words: list[Word] = Field(default_factory=list)
    duration: float = 0.0

    @property
    def text(self) -> str:
        return " ".join(w.word for w in self.words)

    def words_between(self, start: float, end: float) -> list[Word]:
        """Words whose midpoint falls inside [start, end).

        Midpoint rather than full containment: a word straddling the boundary
        belongs to whichever side holds most of it, which keeps captions from
        duplicating across adjacent clips.
        """
        out: list[Word] = []
        for w in self.words:
            mid = (w.start + w.end) / 2.0
            if start <= mid < end:
                out.append(w)
        return out


class SourceMedia(BaseModel):
    """What `download` hands to the rest of the pipeline."""

    video_path: str
    audio_path: str
    title: str
    duration: float
    width: int
    height: int
    fps: float
    source_url: str | None = None


class ClipCandidate(BaseModel):
    """One selected moment. Produced only by pipeline/select.py."""

    start: float
    end: float
    hook_score: int = Field(ge=1, le=10)
    title: str
    reason: str

    @field_validator("title", "reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class RenderedClip(BaseModel):
    candidate: ClipCandidate
    path: str
    size_bytes: int
    width: int
    height: int
    index: int

    @property
    def duration(self) -> float:
        return self.candidate.duration


# --- API types --------------------------------------------------------------


class JobOut(BaseModel):
    id: str
    status: JobStatus
    stage: Stage
    progress: float
    source_title: str | None
    source_url: str | None
    duration: float | None
    clip_count: int
    error: str | None
    created_at: datetime
    updated_at: datetime


class ClipOut(BaseModel):
    id: str
    job_id: str
    title: str
    hook_score: int
    reason: str
    start: float
    end: float
    duration: float
    url: str
    size_bytes: int
    width: int
    height: int
    index: int


class CreateJobRequest(BaseModel):
    youtube_url: str | None = None
