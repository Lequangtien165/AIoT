"""Recognize all faces from an RTSP stream on Windows."""

from __future__ import annotations

import argparse
import platform
import sys
import time

import cv2

from aiot.streaming.stream_reader import display_source, open_capture
from aiot.streaming.stream_settings import RTSP_URL


WINDOW_TITLE = "Face Recognition"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recognize faces from an RTSP stream on Windows.")
    parser.add_argument("--source", default=RTSP_URL, help=f"RTSP URL (default: {RTSP_URL}).")
    parser.add_argument("--confidence", type=float, default=0.5, help="MediaPipe confidence (default: 0.5).")
    parser.add_argument("--threshold", type=float, default=0.45, help="Cosine similarity threshold (default: 0.45).")
    parser.add_argument("--top-k", type=int, default=5, help="Number of FAISS vectors to retrieve (default: 5).")
    parser.add_argument("--recognition-interval-frames", type=int, default=15)
    parser.add_argument("--max-recognitions-per-frame", type=int, default=1)
    parser.add_argument("--track-iou-threshold", type=float, default=0.30)
    parser.add_argument("--track-ttl-frames", type=int, default=20)
    parser.add_argument("--min-track-age-frames", type=int, default=3)
    parser.add_argument("--min-face-size", type=int, default=80)
    parser.add_argument("--record-video", help="File or directory for annotated video output.")
    parser.add_argument("--snapshot-dir", help="Directory for snapshots on MATCH or identity change.")
    parser.add_argument("--no-mirror", action="store_true", help="Do not mirror the preview.")
    parser.add_argument("--reconnect-delay", type=float, default=2.0)
    args = parser.parse_args()
    if not 0 <= args.confidence <= 1 or not 0 <= args.threshold <= 1:
        parser.error("confidence and threshold must be between 0 and 1.")
    if args.top_k <= 0 or args.recognition_interval_frames <= 0 or args.max_recognitions_per_frame <= 0:
        parser.error("interval, top-k, and max recognitions must be greater than 0.")
    if args.reconnect_delay <= 0 or args.track_ttl_frames <= 0 or args.min_track_age_frames <= 0:
        parser.error("reconnect and track values must be greater than 0.")
    return args


def draw_tracks(frame, tracks) -> None:
    for track in tracks:
        x1, y1, x2, y2 = track.bbox
        if track.status == "matched":
            color = (0, 180, 0)
            text = f"#{track.track_id} {track.label} {track.score:.3f}"
        elif track.status == "unknown":
            color = (0, 165, 255)
            text = f"#{track.track_id} UNKNOWN"
        else:
            color = (255, 200, 0)
            text = f"#{track.track_id} checking..."
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, text, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)


def log_event(event, snapshot_path) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    if event.kind == "identity_confirmed":
        message = f'MATCH track={event.track_id} person="{event.label}" score={event.score:.3f}'
    elif event.kind == "identity_changed":
        message = (
            f'IDENTITY_CHANGED track={event.track_id} from="{event.previous_label}" '
            f'to="{event.label}" score={event.score:.3f}'
        )
    else:
        message = f'UNKNOWN track={event.track_id} previous="{event.previous_label}"'
    if snapshot_path is not None:
        message += f" snapshot={snapshot_path}"
    print(f"[{timestamp}] {message}")


def main() -> int:
    args = parse_args()
    if platform.system() != "Windows":
        print("InsightFace + FAISS recognition is currently supported only on Windows. Use python app.py for detection.", file=sys.stderr)
        return 1

    # Import only after the platform gate so macOS can keep a detection-only install.
    from aiot.detection.face_detector import FaceDetector
    from aiot.recognition.face_engine import FaceEngine
    from aiot.recognition.face_recognizer import FaceRecognizer
    from aiot.streaming.stream_output import StreamOutput
    from aiot.tracking.face_tracker import FaceTracker, iou

    engine = FaceEngine()
    recognizer = FaceRecognizer()
    tracker = FaceTracker(
        iou_threshold=args.track_iou_threshold,
        ttl_frames=args.track_ttl_frames,
        min_age_frames=args.min_track_age_frames,
        min_face_size=args.min_face_size,
        recognition_interval_frames=args.recognition_interval_frames,
    )
    output = StreamOutput(args.record_video, args.snapshot_dir)
    camera = None
    frame_number = 0
    reconnecting = False
    source_fps = 0.0

    try:
        with FaceDetector(args.confidence) as detector:
            while True:
                if camera is None:
                    camera = open_capture(args.source)
                    if not camera.isOpened():
                        camera.release()
                        camera = None
                        if not reconnecting:
                            print(f"Could not open RTSP stream: {display_source(args.source)}. Retrying...", file=sys.stderr)
                        reconnecting = True
                        if cv2.waitKey(int(args.reconnect_delay * 1000)) & 0xFF in (27, ord("q")):
                            break
                        continue
                    source_fps = camera.get(cv2.CAP_PROP_FPS)
                    reconnecting = False

                success, frame = camera.read()
                if not success:
                    camera.release()
                    camera = None
                    continue
                if not args.no_mirror:
                    frame = cv2.flip(frame, 1)

                frame_number += 1
                detections = detector.detect(frame, time.monotonic_ns() // 1_000_000)
                tracks = tracker.update([item.bbox for item in detections], frame_number)
                selected = tracker.select_for_recognition(frame_number, args.max_recognitions_per_frame)
                events = []
                if selected:
                    try:
                        observations = engine.extract_faces(frame)
                    except Exception as error:
                        print(f"[WARNING] Could not generate embeddings: {error}", file=sys.stderr)
                        observations = []
                    for track in selected:
                        observation = max(observations, key=lambda item: iou(track.bbox, item.bbox), default=None)
                        if observation is None or iou(track.bbox, observation.bbox) < 0.10:
                            event = tracker.apply_recognition(track.track_id, None, None, args.threshold)
                        else:
                            name, score = recognizer.search(observation.embedding, args.top_k)[0]
                            event = tracker.apply_recognition(track.track_id, name, score, args.threshold)
                        if event is not None:
                            events.append(event)

                draw_tracks(frame, tracks)
                for event in events:
                    snapshot = None
                    if event.kind in {"identity_confirmed", "identity_changed"}:
                        snapshot = output.save_snapshot(frame, event.track_id, event.label or "unknown", event.score or 0.0)
                    log_event(event, snapshot)
                output.write_frame(frame, source_fps)
                cv2.imshow(WINDOW_TITLE, frame)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break
    except KeyboardInterrupt:
        return 0
    finally:
        if camera is not None:
            camera.release()
        output.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
