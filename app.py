"""Display webcam video with green bounding boxes around detected faces."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


MODEL_PATH = Path(__file__).parent / "models" / "blaze_face_short_range.tflite"
WINDOW_TITLE = "MediaPipe Face Detection"


def draw_detections(frame, detection_result) -> None:
    """Draw a green rectangle for each face, clamped to the camera frame."""
    height, width = frame.shape[:2]

    for detection in detection_result.detections:
        box = detection.bounding_box
        left = max(0, box.origin_x)
        top = max(0, box.origin_y)
        right = min(width - 1, box.origin_x + box.width)
        bottom = min(height - 1, box.origin_y + box.height)

        if left < right and top < bottom:
            cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect faces from a webcam with MediaPipe."
    )
    parser.add_argument(
        "--camera", type=int, default=0, help="Camera index to use (default: 0)."
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.5,
        help="Minimum detection confidence from 0 to 1 (default: 0.5).",
    )
    args = parser.parse_args()

    if not 0 <= args.confidence <= 1:
        parser.error("--confidence must be between 0 and 1.")

    return args


def main() -> int:
    args = parse_args()

    if not MODEL_PATH.is_file():
        print(
            f"Missing model file: {MODEL_PATH}\n"
            "Download it using the command in README.md.",
            file=sys.stderr,
        )
        return 1

    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        print(
            f"Could not open camera {args.camera}. "
            "Check the index, privacy permissions, and whether another app is using it.",
            file=sys.stderr,
        )
        return 1

    base_options = python.BaseOptions(model_asset_path=str(MODEL_PATH))
    options = vision.FaceDetectorOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        min_detection_confidence=args.confidence,
    )

    try:
        with vision.FaceDetector.create_from_options(options) as detector:
            while True:
                success, frame = camera.read()
                if not success:
                    print("Could not read a frame from the camera.", file=sys.stderr)
                    break

                frame = cv2.flip(frame, 1)
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_frame = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                timestamp_ms = time.monotonic_ns() // 1_000_000
                result = detector.detect_for_video(mp_frame, timestamp_ms)

                draw_detections(frame, result)
                cv2.imshow(WINDOW_TITLE, frame)

                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
    finally:
        camera.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
