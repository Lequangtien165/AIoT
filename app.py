"""Display an RTSP stream with green bounding boxes around detected faces."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from stream_settings import RTSP_URL


MODEL_PATH = Path(__file__).parent / "models" / "blaze_face_short_range.tflite"
WINDOW_TITLE = "MediaPipe Face Detection"
DEFAULT_SOURCE = RTSP_URL


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


def display_source(source: str) -> str:
    """Return a source URL safe to include in logs."""
    try:
        parsed = urlsplit(source)
        if not parsed.hostname:
            return "RTSP source"
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        if parsed.username is not None:
            host = f"{parsed.username}:***@{host}"
        return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))
    except ValueError:
        return "RTSP source"


def should_exit(wait_seconds: float) -> bool:
    """Keep the window responsive while waiting to reconnect."""
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        key = cv2.waitKey(100) & 0xFF
        if key in (27, ord("q")):
            return True
    return False


def open_capture(source: str):
    # MediaMTX is configured for TCP-only RTSP to keep the local pipeline simple.
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;5000000"
    return cv2.VideoCapture(source, cv2.CAP_FFMPEG)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect faces from an RTSP stream with MediaPipe."
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"RTSP URL to read (default: {DEFAULT_SOURCE}).",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.5,
        help="Minimum detection confidence from 0 to 1 (default: 0.5).",
    )
    parser.add_argument(
        "--reconnect-delay",
        type=float,
        default=2,
        help="Seconds to wait before retrying a disconnected stream (default: 2).",
    )
    args = parser.parse_args()

    if not 0 <= args.confidence <= 1:
        parser.error("--confidence must be between 0 and 1.")
    if args.reconnect_delay <= 0:
        parser.error("--reconnect-delay must be positive.")

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

    base_options = python.BaseOptions(model_asset_path=str(MODEL_PATH))
    options = vision.FaceDetectorOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        min_detection_confidence=args.confidence,
    )

    camera = None
    reconnecting = False
    try:
        with vision.FaceDetector.create_from_options(options) as detector:
            while True:
                if camera is None:
                    camera = open_capture(args.source)
                    if not camera.isOpened():
                        camera.release()
                        camera = None
                        if not reconnecting:
                            print(
                                f"Could not open RTSP stream: {display_source(args.source)}. "
                                f"Retrying every {args.reconnect_delay:g} seconds.",
                                file=sys.stderr,
                            )
                        reconnecting = True
                        if should_exit(args.reconnect_delay):
                            break
                        continue
                    if reconnecting:
                        print(f"Reconnected to RTSP stream: {display_source(args.source)}")
                    reconnecting = False

                success, frame = camera.read()
                if not success:
                    camera.release()
                    camera = None
                    if not reconnecting:
                        print(
                            f"Lost RTSP stream: {display_source(args.source)}. "
                            f"Retrying every {args.reconnect_delay:g} seconds.",
                            file=sys.stderr,
                        )
                    reconnecting = True
                    if should_exit(args.reconnect_delay):
                        break
                    continue

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
    except KeyboardInterrupt:
        return 0
    finally:
        if camera is not None:
            camera.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
