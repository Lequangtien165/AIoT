"""Display an RTSP stream with MediaPipe bounding boxes."""

from __future__ import annotations

import argparse
import sys
import time

import cv2

from aiot.detection.face_detector import FaceDetector
from aiot.streaming.stream_reader import display_source, open_capture
from aiot.streaming.stream_settings import RTSP_URL


WINDOW_TITLE = "MediaPipe Face Detection"


def draw_detections(frame, detections) -> None:
    """Draw a box for every detected face."""
    for detection in detections:
        x1, y1, x2, y2 = detection.bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)


def should_exit(wait_seconds: float) -> bool:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if cv2.waitKey(100) & 0xFF in (27, ord("q")):
            return True
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect faces from an RTSP stream with MediaPipe.")
    parser.add_argument("--source", default=RTSP_URL, help=f"RTSP URL to read (default: {RTSP_URL}).")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--reconnect-delay", type=float, default=2.0)
    args = parser.parse_args()
    if not 0 <= args.confidence <= 1:
        parser.error("--confidence must be between 0 and 1.")
    if args.reconnect_delay <= 0:
        parser.error("--reconnect-delay must be positive.")
    return args


def open_camera(source: str):
    camera = open_capture(source)
    if camera.isOpened():
        return camera
    camera.release()
    return None


def wait_for_reconnect(source: str, reconnecting: bool, message: str, delay: float) -> tuple[bool, bool]:
    if not reconnecting:
        print(f"{message}: {display_source(source)}. Retrying.", file=sys.stderr)
    return True, should_exit(delay)


def render_frame(frame, detector: FaceDetector) -> bool:
    frame = cv2.flip(frame, 1)
    detections = detector.detect(frame, time.monotonic_ns() // 1_000_000)
    draw_detections(frame, detections)
    cv2.imshow(WINDOW_TITLE, frame)
    return cv2.waitKey(1) & 0xFF in (27, ord("q"))


def run_preview(source: str, reconnect_delay: float, detector: FaceDetector) -> None:
    camera = None
    reconnecting = False
    try:
        while True:
            if camera is None:
                camera = open_camera(source)
                if camera is None:
                    reconnecting, should_stop = wait_for_reconnect(
                        source, reconnecting, "Could not open RTSP stream", reconnect_delay
                    )
                    if should_stop:
                        return
                    continue
                reconnecting = False

            success, frame = camera.read()
            if not success:
                camera.release()
                camera = None
                reconnecting, should_stop = wait_for_reconnect(
                    source, reconnecting, "Lost RTSP stream", reconnect_delay
                )
                if should_stop:
                    return
                continue
            if render_frame(frame, detector):
                return
    except KeyboardInterrupt:
        return
    finally:
        if camera is not None:
            camera.release()


def main() -> int:
    args = parse_args()
    try:
        with FaceDetector(args.confidence) as detector:
            run_preview(args.source, args.reconnect_delay, detector)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
