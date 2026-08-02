"""Low-rate MOG2 motion detector used while the edge stream is idle."""

from __future__ import annotations

import time
from collections import deque


class MotionDetector:
    def __init__(
        self,
        device: int | str,
        *,
        width: int = 320,
        height: int = 240,
        fps: float = 5.0,
        area_threshold: float = 0.02,
        window_size: int = 5,
        trigger_frames: int = 3,
        warmup_seconds: float = 2.0,
    ) -> None:
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.area_threshold = area_threshold
        self.window_size = window_size
        self.trigger_frames = trigger_frames
        self.warmup_seconds = warmup_seconds
        self._camera = None

    def wait_for_motion(self, stop_event) -> bool:
        import cv2

        camera = cv2.VideoCapture(self.device)
        if not camera.isOpened():
            camera.release()
            raise RuntimeError(f"Could not open motion camera: {self.device}")
        self._camera = camera
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        subtractor = cv2.createBackgroundSubtractorMOG2(detectShadows=True)
        history: deque[bool] = deque(maxlen=self.window_size)
        warmed_at = time.monotonic() + self.warmup_seconds
        period = 1.0 / self.fps
        try:
            while not stop_event.is_set():
                started = time.monotonic()
                success, frame = camera.read()
                if not success:
                    raise RuntimeError("Motion camera frame read failed.")
                mask = subtractor.apply(frame)
                _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, None)
                changed = cv2.countNonZero(mask) / float(mask.size) >= self.area_threshold
                if started >= warmed_at:
                    history.append(changed)
                    if sum(history) >= self.trigger_frames:
                        return True
                stop_event.wait(max(0.0, period - (time.monotonic() - started)))
            return False
        finally:
            self.close()

    def close(self) -> None:
        if self._camera is not None:
            self._camera.release()
            self._camera = None
