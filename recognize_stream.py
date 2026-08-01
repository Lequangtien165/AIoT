"""Recognize all faces from an RTSP stream on Windows."""

from __future__ import annotations

import argparse
import platform
import sys
import threading
import time
from typing import Any
from dataclasses import dataclass

import cv2
import numpy as np

from aiot.mqtt import payloads
from aiot.mqtt.client import MqttClient, MqttUnavailable
from aiot.mqtt.topics import TOPIC_ERROR_PIPELINE, TOPIC_POLICIES, TOPIC_RECOGNITION_RESULT, TOPIC_SYSTEM_STATUS
from aiot.streaming.stream_reader import display_source, open_capture
from aiot.streaming.stream_settings import RTSP_URL


WINDOW_TITLE = "Face Recognition"


@dataclass(frozen=True)
class StreamFrame:
    frame_id: int
    frame: np.ndarray
    timestamp: float
    source_fps: float


@dataclass(frozen=True)
class DisplayTrack:
    track_id: int
    bbox: tuple[int, int, int, int]
    label: str | None
    score: float | None
    status: str
    missed_frames: int


@dataclass(frozen=True)
class RecognitionResult:
    result_id: int
    frame_id: int
    timestamp: float
    latency_ms: float
    tracks: list[DisplayTrack]
    events: list[object]
    active_tracks: int
    visible_tracks: int
    stale_tracks: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recognize faces from an RTSP stream on Windows.")
    parser.add_argument("--source", default=RTSP_URL, help=f"RTSP URL (default: {RTSP_URL}).")
    parser.add_argument("--threshold", type=float, default=0.45, help="Cosine similarity threshold (default: 0.45).")
    parser.add_argument("--top-k", type=int, default=5, help="Number of FAISS vectors to retrieve (default: 5).")
    parser.add_argument("--recognition-fps", type=float, default=6.0)
    parser.add_argument("--track-iou-threshold", type=float, default=0.30)
    parser.add_argument("--track-ttl-frames", type=int, default=8)
    parser.add_argument("--min-track-age-frames", type=int, default=3)
    parser.add_argument("--min-face-size", type=int, default=80)
    parser.add_argument("--matched-recognition-interval-frames", type=int, default=30)
    parser.add_argument("--det-size", type=int, default=640, help="InsightFace detector size (default: 640).")
    parser.add_argument("--record-video", help="File or directory for annotated video output.")
    parser.add_argument("--snapshot-dir", help="Directory for snapshots on MATCH or identity change.")
    parser.add_argument("--no-mirror", action="store_true", help="Do not mirror the preview.")
    parser.add_argument("--profile", action="store_true", help="Print capture, display, and recognition profiling.")
    parser.add_argument("--require-gpu", action="store_true", help="Exit if CUDAExecutionProvider is not active.")
    parser.add_argument("--reconnect-delay", type=float, default=2.0)
    parser.add_argument("--mqtt-host", help="MQTT broker host for recognition/result events.")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-client-id", default="aiot-recognition")
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        parser.error("threshold must be between 0 and 1.")
    if args.top_k <= 0 or args.recognition_fps <= 0 or args.det_size <= 0:
        parser.error("top-k, recognition-fps, and det-size must be greater than 0.")
    if (
        args.reconnect_delay <= 0
        or args.track_ttl_frames <= 0
        or args.min_track_age_frames <= 0
        or args.matched_recognition_interval_frames <= 0
    ):
        parser.error("reconnect and track values must be greater than 0.")
    return args


def mqtt_policy(topic: str) -> tuple[int, bool]:
    policy = TOPIC_POLICIES[topic]
    return policy.qos, policy.retain


def publish_mqtt(client: MqttClient | None, topic: str, payload: dict[str, Any]) -> None:
    if client is None:
        return
    qos, retain = mqtt_policy(topic)
    client.publish(topic, payload, qos=qos, retain=retain)


def scale_bbox(bbox: tuple[int, int, int, int], scale: float) -> tuple[int, int, int, int]:
    if scale == 1.0:
        return bbox
    x1, y1, x2, y2 = bbox
    return (
        int(x1 * scale),
        int(y1 * scale),
        int(x2 * scale),
        int(y2 * scale),
    )


def resize_for_display(frame: np.ndarray, display_width: int) -> tuple[np.ndarray, float]:
    height, width = frame.shape[:2]
    if width <= display_width:
        return frame, 1.0
    scale = display_width / float(width)
    target_height = max(1, int(height * scale))
    resized = cv2.resize(frame, (display_width, target_height), interpolation=cv2.INTER_AREA)
    return resized, scale


def draw_tracks(frame: np.ndarray, tracks: list[DisplayTrack], scale: float, stale: bool) -> None:
    for track in tracks:
        x1, y1, x2, y2 = scale_bbox(track.bbox, scale)
        if stale:
            color = (150, 150, 150)
            text = f"#{track.track_id} stale"
        elif track.status == "matched":
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


def event_payload(event, snapshot_path: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": event.kind,
        "track_id": event.track_id,
        "label": getattr(event, "label", None),
        "score": getattr(event, "score", None),
        "previous_label": getattr(event, "previous_label", None),
    }
    if snapshot_path is not None:
        data["snapshot_path"] = snapshot_path
    return data


def track_payload(track: DisplayTrack) -> dict[str, Any]:
    return {
        "track_id": track.track_id,
        "bbox": list(track.bbox),
        "label": track.label,
        "score": track.score,
        "status": track.status,
        "missed_frames": track.missed_frames,
    }


def snapshot_tracks(tracks: list[object]) -> list[DisplayTrack]:
    return [
        DisplayTrack(
            track_id=track.track_id,
            bbox=track.bbox,
            label=track.label,
            score=track.score,
            status=track.status,
            missed_frames=track.missed_frames,
        )
        for track in tracks
        if track.missed_frames == 0
    ]


def track_counts(tracks: list[object], visible_tracks: list[DisplayTrack]) -> tuple[int, int, int]:
    active_tracks = sum(1 for track in tracks if track.missed_frames == 0)
    stale_tracks = sum(1 for track in tracks if track.missed_frames > 0)
    return active_tracks, len(visible_tracks), stale_tracks


class LatestFrameReader:
    def __init__(self, source: str, mirror: bool, reconnect_delay: float) -> None:
        self.source = source
        self.mirror = mirror
        self.reconnect_delay = reconnect_delay
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="LatestFrameReader", daemon=True)
        self._latest: StreamFrame | None = None
        self._frames_read = 0
        self._source_fps = 0.0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=3)

    def latest(self) -> StreamFrame | None:
        with self._lock:
            if self._latest is None:
                return None
            return StreamFrame(
                frame_id=self._latest.frame_id,
                frame=self._latest.frame.copy(),
                timestamp=self._latest.timestamp,
                source_fps=self._latest.source_fps,
            )

    def frames_read(self) -> int:
        with self._lock:
            return self._frames_read

    def _run(self) -> None:
        camera = None
        frame_id = 0
        reconnecting = False
        try:
            while not self._stop_event.is_set():
                if camera is None:
                    camera = open_capture(self.source)
                    if not camera.isOpened():
                        camera.release()
                        camera = None
                        if not reconnecting:
                            print(f"Could not open RTSP stream: {display_source(self.source)}. Retrying...", file=sys.stderr)
                        reconnecting = True
                        self._stop_event.wait(self.reconnect_delay)
                        continue
                    self._source_fps = camera.get(cv2.CAP_PROP_FPS)
                    reconnecting = False

                success, frame = camera.read()
                if not success:
                    camera.release()
                    camera = None
                    continue
                if self.mirror:
                    frame = cv2.flip(frame, 1)

                frame_id += 1
                stream_frame = StreamFrame(frame_id, frame, time.monotonic(), self._source_fps)
                with self._lock:
                    self._latest = stream_frame
                    self._frames_read += 1
        finally:
            if camera is not None:
                camera.release()


class RecognitionWorker:
    def __init__(
        self,
        reader: LatestFrameReader,
        engine: object,
        recognizer: object,
        tracker: object,
        recognition_fps: float,
        top_k: int,
        threshold: float,
        on_pipeline_error=None,
    ) -> None:
        self.reader = reader
        self.engine = engine
        self.recognizer = recognizer
        self.tracker = tracker
        self.period = 1.0 / recognition_fps
        self.top_k = top_k
        self.threshold = threshold
        self.on_pipeline_error = on_pipeline_error
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="RecognitionWorker", daemon=True)
        self._latest_result: RecognitionResult | None = None
        self._processed_frames = 0
        self._latency_total_ms = 0.0
        self._last_latency_ms = 0.0
        self._active_tracks = 0
        self._visible_tracks = 0
        self._stale_tracks = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=3)

    def latest_result(self) -> RecognitionResult | None:
        with self._lock:
            return self._latest_result

    def stats(self) -> tuple[int, float, float, int, int, int]:
        with self._lock:
            average = self._latency_total_ms / self._processed_frames if self._processed_frames else 0.0
            return (
                self._processed_frames,
                self._last_latency_ms,
                average,
                self._active_tracks,
                self._visible_tracks,
                self._stale_tracks,
            )

    def _run(self) -> None:
        last_frame_id = 0
        result_id = 0
        next_run = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now < next_run:
                self._stop_event.wait(min(0.01, next_run - now))
                continue

            stream_frame = self.reader.latest()
            if stream_frame is None or stream_frame.frame_id == last_frame_id:
                self._stop_event.wait(0.005)
                continue

            last_frame_id = stream_frame.frame_id
            next_run = now + self.period
            started = time.monotonic()
            events = []
            try:
                observations = self.engine.extract_faces(stream_frame.frame)
                tracks = self.tracker.update([item.bbox for item in observations], stream_frame.frame_id)
                observation_by_track = {}
                for observation in observations:
                    matched_track = max(
                        tracks,
                        key=lambda track: (
                            1.0 if track.missed_frames == 0 and track.bbox == observation.bbox else 0.0,
                            0.0,
                        ),
                        default=None,
                    )
                    if matched_track is not None:
                        observation_by_track[matched_track.track_id] = observation

                selected = self.tracker.select_for_recognition(stream_frame.frame_id, maximum=len(observations) or 1)
                for track in selected:
                    observation = observation_by_track.get(track.track_id)
                    if observation is None:
                        event = self.tracker.apply_recognition(track.track_id, None, None, self.threshold)
                    else:
                        name, score = self.recognizer.search(observation.embedding, self.top_k)[0]
                        event = self.tracker.apply_recognition(track.track_id, name, score, self.threshold)
                    if event is not None:
                        events.append(event)
                tracks_to_display = snapshot_tracks(tracks)
                active_tracks, visible_tracks, stale_tracks = track_counts(tracks, tracks_to_display)
            except Exception as error:
                print(f"[WARNING] Could not run InsightFace on frame {stream_frame.frame_id}: {error}", file=sys.stderr)
                if self.on_pipeline_error is not None:
                    self.on_pipeline_error(stream_frame.frame_id, error)
                tracks_to_display = snapshot_tracks(list(self.tracker.tracks.values()))
                active_tracks, visible_tracks, stale_tracks = track_counts(list(self.tracker.tracks.values()), tracks_to_display)

            latency_ms = (time.monotonic() - started) * 1000.0
            result_id += 1
            result = RecognitionResult(
                result_id=result_id,
                frame_id=stream_frame.frame_id,
                timestamp=time.monotonic(),
                latency_ms=latency_ms,
                tracks=tracks_to_display,
                events=events,
                active_tracks=active_tracks,
                visible_tracks=visible_tracks,
                stale_tracks=stale_tracks,
            )
            with self._lock:
                self._latest_result = result
                self._processed_frames += 1
                self._latency_total_ms += latency_ms
                self._last_latency_ms = latency_ms
                self._active_tracks = active_tracks
                self._visible_tracks = visible_tracks
                self._stale_tracks = stale_tracks


def print_profile(
    reader: LatestFrameReader,
    worker: RecognitionWorker,
    display_frames: int,
    last_capture_frames: int,
    last_recognition_frames: int,
    last_display_frames: int,
    last_profile_time: float,
) -> tuple[int, int, int, float]:
    now = time.monotonic()
    elapsed = max(0.001, now - last_profile_time)
    capture_frames = reader.frames_read()
    (
        recognition_frames,
        last_latency_ms,
        average_latency_ms,
        active_tracks,
        visible_tracks,
        stale_tracks,
    ) = worker.stats()
    capture_fps = (capture_frames - last_capture_frames) / elapsed
    recognition_fps = (recognition_frames - last_recognition_frames) / elapsed
    display_fps = (display_frames - last_display_frames) / elapsed
    print(
        "PROFILE "
        f"capture_fps={capture_fps:.1f} "
        f"display_fps={display_fps:.1f} "
        f"recognition_fps={recognition_fps:.1f} "
        f"last_latency_ms={last_latency_ms:.1f} "
        f"avg_latency_ms={average_latency_ms:.1f} "
        f"active_tracks={active_tracks} "
        f"visible_tracks={visible_tracks} "
        f"stale_tracks={stale_tracks}",
        file=sys.stderr,
    )
    return capture_frames, recognition_frames, display_frames, now


def main() -> int:
    args = parse_args()
    if platform.system() != "Windows":
        print("InsightFace + FAISS recognition is currently supported only on Windows. Use python app.py for detection.", file=sys.stderr)
        return 1

    from aiot.recognition.face_engine import FaceEngine
    from aiot.recognition.face_recognizer import FaceRecognizer
    from aiot.streaming.stream_output import StreamOutput
    from aiot.tracking.face_tracker import FaceTracker

    mqtt_client: MqttClient | None = None
    if args.mqtt_host:
        try:
            mqtt_client = MqttClient(
                host=args.mqtt_host,
                port=args.mqtt_port,
                client_id=args.mqtt_client_id,
            )
            mqtt_client.connect()
            publish_mqtt(
                mqtt_client,
                TOPIC_SYSTEM_STATUS,
                payloads.system_status(
                    device_id=args.mqtt_client_id,
                    component="recognition",
                    state="starting",
                    message="Recognition pipeline is starting.",
                ),
            )
        except MqttUnavailable as error:
            print(f"[MQTT] {error}", file=sys.stderr)
            return 1

    engine = FaceEngine(det_size=args.det_size)
    recognizer = FaceRecognizer()
    tracker = FaceTracker(
        iou_threshold=args.track_iou_threshold,
        ttl_frames=args.track_ttl_frames,
        min_age_frames=args.min_track_age_frames,
        min_face_size=args.min_face_size,
        recognition_interval_frames=1,
        matched_recognition_interval_frames=args.matched_recognition_interval_frames,
    )
    output = StreamOutput(args.record_video, args.snapshot_dir)
    if engine.startup_output:
        print(engine.startup_output, file=sys.stderr)
    provider_display = ", ".join(engine.providers)
    print(f"FaceEngine providers: {provider_display}", file=sys.stderr)
    if engine.provider_status.gpu_active:
        print("GPU active", file=sys.stderr)
    elif engine.provider_status.gpu_requested:
        print("GPU requested but unavailable, using CPU", file=sys.stderr)
        if engine.provider_status.warning:
            print(f"[WARNING] {engine.provider_status.warning}", file=sys.stderr)
    else:
        print("CPU only", file=sys.stderr)
    if args.require_gpu and not engine.provider_status.gpu_active:
        print("Error: --require-gpu was set but CUDAExecutionProvider is not active.", file=sys.stderr)
        return 1

    output = StreamOutput(args.record_video, args.snapshot_dir)
    reader = LatestFrameReader(args.source, mirror=not args.no_mirror, reconnect_delay=args.reconnect_delay)
    def on_pipeline_error(frame_id: int, error: Exception) -> None:
        publish_mqtt(
            mqtt_client,
            TOPIC_ERROR_PIPELINE,
            payloads.error_event(
                component="recognition",
                source=args.source,
                message=str(error),
                details={"frame_id": frame_id},
            ),
        )

    worker = RecognitionWorker(
        reader=reader,
        engine=engine,
        recognizer=recognizer,
        tracker=tracker,
        recognition_fps=args.recognition_fps,
        top_k=args.top_k,
        threshold=args.threshold,
        on_pipeline_error=on_pipeline_error,
    )

    display_frames = 0
    consumed_result_id = 0
    last_rendered_frame_id = 0
    last_rendered_result_id = 0
    last_capture_frames = 0
    last_recognition_frames = 0
    last_display_frames = 0
    last_profile_time = time.monotonic()

    reader.start()
    worker.start()
    try:
        while True:
            stream_frame = reader.latest()
            if stream_frame is None:
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break
                continue

            result = worker.latest_result()
            result_id = result.result_id if result is not None else 0
            if stream_frame.frame_id == last_rendered_frame_id and result_id == last_rendered_result_id:
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break
                continue
            last_rendered_frame_id = stream_frame.frame_id
            last_rendered_result_id = result_id

            display_frame, display_scale = resize_for_display(stream_frame.frame, 1280)
            if display_frame is stream_frame.frame:
                display_frame = display_frame.copy()

            if result is not None:
                stale = time.monotonic() - result.timestamp > max(0.5, 2.0 / args.recognition_fps)
                draw_tracks(display_frame, result.tracks, display_scale, stale)
                if result.result_id != consumed_result_id:
                    consumed_result_id = result.result_id
                    event_payloads = []
                    for event in result.events:
                        snapshot = None
                        if event.kind in {"identity_confirmed", "identity_changed"}:
                            snapshot = output.save_snapshot(stream_frame.frame, event.track_id, event.label or "unknown", event.score or 0.0)
                        log_event(event, snapshot)
                        event_payloads.append(event_payload(event, str(snapshot) if snapshot is not None else None))
                    publish_mqtt(
                        mqtt_client,
                        TOPIC_RECOGNITION_RESULT,
                        payloads.recognition_result(
                            source=args.source,
                            frame_id=result.frame_id,
                            result_id=result.result_id,
                            latency_ms=result.latency_ms,
                            tracks=[track_payload(track) for track in result.tracks],
                            events=event_payloads,
                        ),
                    )

            output.write_frame(display_frame, stream_frame.source_fps)
            cv2.imshow(WINDOW_TITLE, display_frame)
            display_frames += 1

            if args.profile and time.monotonic() - last_profile_time >= 2.0:
                (
                    last_capture_frames,
                    last_recognition_frames,
                    last_display_frames,
                    last_profile_time,
                ) = print_profile(
                    reader,
                    worker,
                    display_frames,
                    last_capture_frames,
                    last_recognition_frames,
                    last_display_frames,
                    last_profile_time,
                )
            if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                break
    except KeyboardInterrupt:
        return 0
    finally:
        publish_mqtt(
            mqtt_client,
            TOPIC_SYSTEM_STATUS,
            payloads.system_status(
                device_id=args.mqtt_client_id,
                component="recognition",
                state="stopping",
                message="Recognition pipeline is stopping.",
            ),
        )
        worker.stop()
        reader.stop()
        output.close()
        if mqtt_client is not None:
            mqtt_client.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
