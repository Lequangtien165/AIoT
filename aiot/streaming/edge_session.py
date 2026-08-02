"""Pure state transitions for an edge motion-triggered RTSP session."""

from __future__ import annotations

import time
import threading
import uuid
from dataclasses import dataclass
from enum import Enum


class EdgeSessionState(str, Enum):
    MONITORING = "monitoring"
    STARTING_STREAM = "starting"
    AWAITING_FACE = "awaiting_face"
    STREAMING = "streaming"
    STOPPING_STREAM = "stopping"


@dataclass
class EdgeSessionController:
    discovery_timeout: float = 30.0
    keepalive_timeout: float = 120.0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self.state = EdgeSessionState.MONITORING
        self.stream_session_id: str | None = None
        self.deadline: float | None = None

    def begin(self) -> str:
        with self._lock:
            if self.state is not EdgeSessionState.MONITORING:
                raise RuntimeError(f"Cannot begin session while {self.state}.")
            self.stream_session_id = str(uuid.uuid4())
            self.state = EdgeSessionState.STARTING_STREAM
            return self.stream_session_id

    def publisher_ready(self, now: float | None = None) -> None:
        if self.state is not EdgeSessionState.STARTING_STREAM:
            raise RuntimeError(f"Publisher is not starting: {self.state}.")
        self.state = EdgeSessionState.AWAITING_FACE
        self.deadline = (time.monotonic() if now is None else now) + self.discovery_timeout

    def face_presence(self, session_id: str, face_count: int, now: float | None = None) -> bool:
        with self._lock:
            if (
                self.state not in {EdgeSessionState.AWAITING_FACE, EdgeSessionState.STREAMING}
                or session_id != self.stream_session_id
                or not isinstance(face_count, int)
                or isinstance(face_count, bool)
                or face_count < 1
            ):
                return False
            self.state = EdgeSessionState.STREAMING
            self.deadline = (time.monotonic() if now is None else now) + self.keepalive_timeout
            return True

    def expired(self, now: float | None = None) -> bool:
        return self.deadline is not None and (time.monotonic() if now is None else now) >= self.deadline

    def stop(self) -> None:
        if self.state is not EdgeSessionState.MONITORING:
            self.state = EdgeSessionState.STOPPING_STREAM

    def complete_stop(self) -> None:
        self.state = EdgeSessionState.MONITORING
        self.stream_session_id = None
        self.deadline = None
