"""Persisted download state, so re-running the app skips finished files."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

MANIFEST_NAME = ".oth-manifest.json"


class Manifest:
    """Tracks which episodes have been successfully downloaded to a dest dir."""

    def __init__(self, dest_root: Path) -> None:
        self._path = dest_root / MANIFEST_NAME
        self._lock = Lock()
        self._data: dict[str, dict] = {}
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def is_done(self, basename: str, file_path: Path) -> bool:
        record = self._data.get(basename)
        if not record:
            return False
        if record.get("status") != "done":
            return False
        return file_path.exists() and file_path.stat().st_size > 0

    def mark_done(self, basename: str, url: str, file_path: Path, size: int) -> None:
        with self._lock:
            self._data[basename] = {
                "status": "done",
                "url": url,
                "path": str(file_path),
                "size": size,
            }
            self._flush()

    def mark_failed(self, basename: str, url: str, error: str) -> None:
        with self._lock:
            self._data[basename] = {
                "status": "failed",
                "url": url,
                "error": error,
            }
            self._flush()

    def _flush(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        tmp.replace(self._path)
