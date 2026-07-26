"""MediaPipe face detection shared by preview and recognition CLIs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


MODEL_PATH = Path(__file__).parent / "models" / "blaze_face_short_range.tflite"


@dataclass(frozen=True)
class Detection:
    bbox: tuple[int, int, int, int]
    confidence: float


class FaceDetector:
    """Phat hien tat ca khuon mat trong BGR frame bang MediaPipe."""

    def __init__(self, confidence: float = 0.5) -> None:
        if not MODEL_PATH.is_file():
            raise FileNotFoundError(
                f"Khong tim thay model MediaPipe: {MODEL_PATH}. "
                "Hay tai theo huong dan trong README.md."
            )
        if not 0 <= confidence <= 1:
            raise ValueError("Confidence phai nam trong khoang 0 den 1.")

        options = vision.FaceDetectorOptions(
            base_options=python.BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,
            min_detection_confidence=confidence,
        )
        self._detector = vision.FaceDetector.create_from_options(options)

    def detect(self, frame: np.ndarray, timestamp_ms: int) -> list[Detection]:
        height, width = frame.shape[:2]
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_frame = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        result = self._detector.detect_for_video(mp_frame, timestamp_ms)
        detections: list[Detection] = []

        for detection in result.detections:
            box = detection.bounding_box
            x1 = max(0, box.origin_x)
            y1 = max(0, box.origin_y)
            x2 = min(width - 1, box.origin_x + box.width)
            y2 = min(height - 1, box.origin_y + box.height)
            if x1 >= x2 or y1 >= y2:
                continue
            score = detection.categories[0].score if detection.categories else 0.0
            detections.append(Detection((x1, y1, x2, y2), float(score)))

        return detections

    def close(self) -> None:
        self._detector.close()

    def __enter__(self) -> "FaceDetector":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
