"""Optional annotated video and match snapshots for stream recognition."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


def safe_name(value: str) -> str:
    name = value.encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[^a-z0-9_-]+", "-", name)
    return name.strip("-_")[:80] or "unknown-person"


class StreamOutput:
    def __init__(self, video_target: str | None, snapshot_dir: str | None) -> None:
        self.video_target = Path(video_target) if video_target else None
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else None
        self.writer: cv2.VideoWriter | None = None
        self.warning_shown = False

    def write_frame(self, frame: np.ndarray, source_fps: float) -> None:
        if self.video_target is None:
            return
        if self.writer is None:
            self.writer = self._open_writer(frame, source_fps)
        if self.writer is not None:
            self.writer.write(frame)

    def save_snapshot(self, frame: np.ndarray, track_id: int, label: str, score: float) -> Path | None:
        if self.snapshot_dir is None:
            return None
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.snapshot_dir / f"{timestamp}_track-{track_id}_{safe_name(label)}_{score:.3f}.jpg"
        if not cv2.imwrite(str(path), frame):
            print("[WARNING] Could not save snapshot.")
            return None
        return path

    def close(self) -> None:
        if self.writer is not None:
            self.writer.release()
            self.writer = None

    def _open_writer(self, frame: np.ndarray, source_fps: float) -> cv2.VideoWriter | None:
        target = self.video_target
        assert target is not None
        if target.suffix == "":
            target.mkdir(parents=True, exist_ok=True)
            target = target / f"stream_{datetime.now():%Y%m%d_%H%M%S}.mp4"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
        self.video_target = target
        fps = source_fps if 1 <= source_fps <= 120 else 20.0
        codecs = ("XVID", "MJPG") if target.suffix.lower() == ".avi" else ("mp4v", "avc1")
        height, width = frame.shape[:2]
        for codec in codecs:
            writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*codec), fps, (width, height))
            if writer.isOpened():
                return writer
            writer.release()
        if not self.warning_shown:
            print("[WARNING] Could not open VideoWriter; continuing without video recording.")
            self.warning_shown = True
        return None
