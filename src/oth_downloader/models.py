"""Data models for the Off The Hook downloader."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(slots=True)
class MonthPage:
    """A single monthly archive page (e.g. 1994/0194.html)."""

    year: int
    month: int
    label: str
    url: str


@dataclass(slots=True)
class Episode:
    """A single downloadable audio file at the highest available bitrate."""

    year: int
    month: int
    date_label: str
    basename: str  # e.g. off_the_hook__19940105 (bitrate-agnostic id)
    title: str  # e.g. "Off The Hook - January 5" or "Off The Hook Overtime - ..."
    url: str  # highest bitrate mp3 url actually used
    bitrate: str  # "128k" or "16k"
    source_page: str
    dest_path: str = ""
    size_bytes: int = 0
    downloaded_bytes: int = 0
    status: Status = Status.PENDING
    error: str = ""

    @property
    def key(self) -> str:
        return self.basename
