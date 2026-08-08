"""Wanted-person list loaded from config/wanted.json.

Single source of truth for the "wanted" red-box and alarm decision used by
both the desktop recognition preview and the web dashboard.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WANTED_CONFIG = PROJECT_ROOT / "config" / "wanted.json"
SUPPORTED_SCHEMA_VERSION = 1


def _validate_config_path(path: str | Path) -> Path:
    """Validate a wanted-config path before touching the file system."""
    raw = str(path)
    if raw.lower().startswith("file:") or Path(path).suffix.lower() != ".json":
        raise ValueError("Wanted config path must be a local .json file.")
    return Path(path).resolve()


@dataclass(frozen=True)
class WantedEntry:
    match: str
    name: str | None = None
    severity: str = "high"

    @property
    def display_name(self) -> str:
        return self.name or self.match


def _validate_entry(item: Any) -> None:
    if not isinstance(item, dict):
        raise ValueError("Each wanted entry must be an object.")
    pattern = item.get("match")
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("Each wanted entry requires a non-empty 'match' regex string.")
    try:
        re.compile(pattern)
    except re.error as error:
        raise ValueError(f"Invalid 'match' regex {pattern!r}: {error}") from error
    if "name" in item and not isinstance(item["name"], str):
        raise ValueError("Wanted entry 'name' must be a string.")
    if "severity" in item and not isinstance(item["severity"], str):
        raise ValueError("Wanted entry 'severity' must be a string.")


class WantedList:
    """Thread-safe wanted-person matcher backed by a JSON config file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = _validate_config_path(path) if path is not None else DEFAULT_WANTED_CONFIG
        self._lock = threading.Lock()
        self._entries: list[WantedEntry] = []
        self.reload()

    def reload(self) -> None:
        path = _validate_config_path(self.path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("wanted.json must contain an object.")
        if raw.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported wanted.json schema_version: {raw.get('schema_version')!r}."
            )
        items = raw.get("wanted")
        if not isinstance(items, list):
            raise ValueError("wanted.json requires a 'wanted' list.")
        entries: list[WantedEntry] = []
        for item in items:
            _validate_entry(item)
            entries.append(
                WantedEntry(
                    match=item["match"],
                    name=item.get("name"),
                    severity=item.get("severity", "high"),
                )
            )
        with self._lock:
            self._entries = entries

    def entries(self) -> list[WantedEntry]:
        with self._lock:
            return list(self._entries)

    def match(self, label: str | None) -> WantedEntry | None:
        if label is None:
            return None
        with self._lock:
            for entry in self._entries:
                if re.search(entry.match, label) is not None:
                    return entry
        return None

    def is_wanted(self, label: str | None) -> bool:
        return self.match(label) is not None
