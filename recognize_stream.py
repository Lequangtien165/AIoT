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
from aiot.mqtt.client import (
    MqttClient,
    MqttConnectionError,
    MqttPublishError,
    MqttSubscriptionError,
    MqttUnavailable,
    password_from_env,
)
from aiot.mqtt.topics import (
    TOPIC_RECOGNITION_RESULT,
    error_pipeline_topic,
    stream_activity_topic,
    system_status_topic,
    topic_policy,
)
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
    detected_faces: int
    embeddings_generated: int
    detection_latency_ms: float
    embedding_latency_ms: float


class CloudEdgeSession:
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self._lock = threading.Lock()
        self.session_id: str | None = None
        self.last_presence = 0.0
        self.capture_enabled = threading.Event()

    def update(self, topic: str, payload: dict, _retained: bool) -> None:
        if topic != system_status_topic(self.device_id):
            return
        if payload.get("schema_version") != payloads.SCHEMA_VERSION or payload.get("device_id") != self.device_id:
            return
        with self._lock:
            if payload.get("state") == "streaming" and isinstance(payload.get("stream_session_id"), str):
                next_session_id = payload["stream_session_id"]
                if next_session_id != self.session_id:
                    self.session_id = next_session_id
                    self.last_presence = 0.0
                self.capture_enabled.set()
                print(f"[SESSION] edge={self.device_id} state=streaming session={self.session_id}")
            elif payload.get("state") in {"monitoring", "stopping", "stopped", "error"}:
                self.session_id = None
                self.capture_enabled.clear()
                print(f"[SESSION] edge={self.device_id} state={payload.get('state')}; capture disabled")

    def presence_due(self, detected_faces: int, interval: float) -> str | None:
        if detected_faces < 1:
            return None
        with self._lock:
            now = time.monotonic()
            if self.session_id is None or now - self.last_presence < interval:
                return None
            self.last_presence = now
            return self.session_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recognize faces from an RTSP stream on Windows.")
    parser.add_argument("--source", default=RTSP_URL, help=f"RTSP URL (default: {RTSP_URL}).")
    parser.add_argument("--threshold", type=float, default=0.45, help="Cosine similarity threshold (default: 0.45).")
    parser.add_argument("--top-k", type=int, default=5, help="Number of FAISS vectors to retrieve (default: 5).")
    parser.add_argument("--recognition-fps", type=float, default=6.0, help="SCRFD detection/tracking cycles per second (default: 6.0).")
    parser.add_argument(
        "--max-embeddings-per-cycle",
        type=int,
        default=1,
        help="Maximum ArcFace embeddings per SCRFD detection cycle (default: 1).",
    )
    parser.add_argument("--track-iou-threshold", type=float, default=0.30, help="IoU threshold to associate a track with a detection (default: 0.30).")
    parser.add_argument("--track-ttl-frames", type=int, default=8, help="Missed frames before a track expires (default: 8).")
    parser.add_argument("--min-track-age-frames", type=int, default=3, help="Visible frames before a track can be recognized (default: 3).")
    parser.add_argument("--min-face-size", type=int, default=80, help="Minimum face box side in pixels for recognition (default: 80).")
    parser.add_argument("--matched-recognition-interval-frames", type=int, default=30, help="Frames between re-embeddings of a matched track (default: 30).")
    parser.add_argument(
        "--embedding-change-threshold",
        type=float,
        default=0.6,
        help="Cosine similarity below which a matched track's face is treated as changed (default: 0.6).",
    )
    parser.add_argument("--det-size", type=int, default=640, help="InsightFace detector size (default: 640).")
    parser.add_argument("--record-video", help="File or directory for annotated video output.")
    parser.add_argument("--snapshot-dir", help="Directory for snapshots on MATCH or identity change.")
    parser.add_argument("--no-mirror", action="store_true", help="Do not mirror the preview; keep published boxes in the raw video space.")
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Print capture, display, and recognition profiling. Not the camera profile flag used by stream_server.py.",
    )
    parser.add_argument("--require-gpu", action="store_true", help="Exit if CUDAExecutionProvider is not active.")
    parser.add_argument("--reconnect-delay", type=float, default=2.0, help="Seconds between RTSP reconnect attempts (default: 2.0).")
    parser.add_argument("--mqtt-host", help="MQTT broker host for recognition/result events.")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port (default: 1883).")
    parser.add_argument("--mqtt-client-id", default="aiot-recognition", help="MQTT client ID (default: aiot-recognition).")
    parser.add_argument("--mqtt-username", help="MQTT username. Password is read from --mqtt-password-env.")
    parser.add_argument("--mqtt-password-env", help="Environment variable containing the MQTT password.")
    parser.add_argument("--mqtt-ca-cert", help="CA certificate path for TLS MQTT connections.")
    parser.add_argument(
        "--source-device-id",
        help="Edge device ID for device-scoped pipeline MQTT errors; defaults to --mqtt-client-id.",
    )
    parser.add_argument(
        "--edge-triggered-session",
        action="store_true",
        help="Enable edge-triggered sessions: subscribe to the edge status and publish face presence.",
    )
    parser.add_argument("--face-presence-interval", type=float, default=15.0, help="Seconds between face-presence lease renewals (default: 15.0).")
    parser.add_argument(
        "--wanted-config",
        help="Path to the wanted-person JSON config (default: config/wanted.json).",
    )
    return parser


def parse_args() -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        parser.error("threshold must be between 0 and 1.")
    if args.top_k <= 0 or args.recognition_fps <= 0 or args.det_size <= 0 or args.max_embeddings_per_cycle <= 0:
        parser.error("top-k, recognition-fps, det-size, and max-embeddings-per-cycle must be greater than 0.")
    if not 0 <= args.embedding_change_threshold <= 1:
        parser.error("embedding-change-threshold must be between 0 and 1.")
    if (
        args.reconnect_delay <= 0
        or args.track_ttl_frames <= 0
        or args.min_track_age_frames <= 0
        or args.matched_recognition_interval_frames <= 0
    ):
        parser.error("reconnect and track values must be greater than 0.")
    if args.mqtt_username:
        try:
            password_from_env(args.mqtt_username, args.mqtt_password_env)
        except ValueError as error:
            parser.error(str(error))
    if args.edge_triggered_session and (not args.mqtt_host or not args.source_device_id):
        parser.error("--edge-triggered-session requires --mqtt-host and --source-device-id.")
    if args.face_presence_interval <= 0:
        parser.error("--face-presence-interval must be positive.")
    return args


def mqtt_policy(topic: str) -> tuple[int, bool]:
    policy = topic_policy(topic)
    return policy.qos, policy.retain


def publish_mqtt(client: MqttClient | None, topic: str, payload: dict[str, Any]) -> None:
    if client is None:
        return
    qos, retain = mqtt_policy(topic)
    try:
        client.publish(topic, payload, qos=qos, retain=retain)
    except MqttPublishError as error:
        print(f"[MQTT] {error}", file=sys.stderr)


def scale_bbox(bbox: tuple[int, int, int, int], scale: float) -> tuple[int, int, int, int]:
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


def format_score(score: float | None) -> str:
    if score is None:
        return "n/a"
    return f"{score:.3f}"


def matched_track_color(wanted: object | None, label: str | None) -> tuple[int, int, int]:
    if label is not None and wanted is not None and wanted.is_wanted(label):
        return (0, 0, 255)
    return (0, 180, 0)


def draw_tracks(frame: np.ndarray, tracks: list[DisplayTrack], scale: float, stale: bool, wanted=None) -> None:
    for track in tracks:
        x1, y1, x2, y2 = scale_bbox(track.bbox, scale)
        if stale:
            color = (150, 150, 150)
            text = f"#{track.track_id} stale"
        elif track.status == "matched":
            color = matched_track_color(wanted, track.label)
            text = f"#{track.track_id} {track.label} {format_score(track.score)}"
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
        message = f'MATCH track={event.track_id} person="{event.label}" score={format_score(event.score)}'
    elif event.kind == "identity_changed":
        message = (
            f'IDENTITY_CHANGED track={event.track_id} from="{event.previous_label}" '
            f'to="{event.label}" score={format_score(event.score)}'
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
    def __init__(
        self,
        source: str,
        mirror: bool,
        reconnect_delay: float,
        capture_enabled: threading.Event | None = None,
    ) -> None:
        self.source = source
        self.mirror = mirror
        self.reconnect_delay = reconnect_delay
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        if capture_enabled is None:
            capture_enabled = threading.Event()
            capture_enabled.set()
        self._capture_enabled = capture_enabled
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

    def _release_capture(self, camera, capture_active: bool) -> tuple[None, bool]:
        if camera is not None:
            camera.release()
            camera = None
        if capture_active:
            print("[RTSP] capture released; waiting for edge stream")
            capture_active = False
        with self._lock:
            self._latest = None
        return camera, capture_active

    def _open_camera(self, camera, reconnecting: bool) -> tuple[object | None, bool]:
        if camera is not None:
            return camera, reconnecting
        camera = open_capture(self.source)
        if not camera.isOpened():
            camera.release()
            camera = None
            if not reconnecting:
                print(
                    f"Could not open RTSP stream: {display_source(self.source)}. Retrying...",
                    file=sys.stderr,
                )
            reconnecting = True
            self._stop_event.wait(self.reconnect_delay)
            return camera, reconnecting
        self._source_fps = camera.get(cv2.CAP_PROP_FPS)
        return camera, False

    def _run(self) -> None:
        camera = None
        frame_id = 0
        reconnecting = False
        capture_active = False
        try:
            while not self._stop_event.is_set():
                if not self._capture_enabled.is_set():
                    camera, capture_active = self._release_capture(camera, capture_active)
                    self._capture_enabled.wait(0.1)
                    continue
                if not capture_active:
                    print("[RTSP] capture enabled; waiting for edge RTSP stream")
                    capture_active = True
                camera, reconnecting = self._open_camera(camera, reconnecting)
                if camera is None:
                    continue

                success, frame = camera.read()
                if not success:
                    camera.release()
                    camera = None
                    continue
                if not self._capture_enabled.is_set():
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
        max_embeddings_per_cycle: int,
        top_k: int,
        threshold: float,
        embedding_change_threshold: float = 0.6,
        on_pipeline_error=None,
    ) -> None:
        self.reader = reader
        self.engine = engine
        self.recognizer = recognizer
        self.tracker = tracker
        self.period = 1.0 / recognition_fps
        self.max_embeddings_per_cycle = max_embeddings_per_cycle
        self.top_k = top_k
        self.threshold = threshold
        self.embedding_change_threshold = embedding_change_threshold
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
        self._embeddings_generated = 0
        self._last_detection_latency_ms = 0.0
        self._detection_latency_total_ms = 0.0
        self._last_embedding_latency_ms = 0.0
        self._embedding_latency_total_ms = 0.0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=3)

    def latest_result(self) -> RecognitionResult | None:
        with self._lock:
            return self._latest_result

    def stats(self) -> tuple[int, int, float, float, float, float, float, float, int, int, int]:
        with self._lock:
            average = self._latency_total_ms / self._processed_frames if self._processed_frames else 0.0
            average_detection = self._detection_latency_total_ms / self._processed_frames if self._processed_frames else 0.0
            average_embedding = self._embedding_latency_total_ms / self._processed_frames if self._processed_frames else 0.0
            return (
                self._processed_frames,
                self._embeddings_generated,
                self._last_latency_ms,
                average,
                self._last_detection_latency_ms,
                average_detection,
                self._last_embedding_latency_ms,
                average_embedding,
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
            outcome = self._process_frame(stream_frame)
            result_id = self._store_result(result_id, stream_frame, started, outcome)

    def _process_frame(self, stream_frame: StreamFrame):
        try:
            detection_started = time.monotonic()
            detections = self.engine.detect_faces(stream_frame.frame)
            detection_latency_ms = (time.monotonic() - detection_started) * 1000.0
            tracks, assignments = self.tracker.update_with_assignments(
                [detection.bbox for detection in detections], stream_frame.frame_id
            )
            detection_by_track = {
                assignment.track_id: detections[assignment.box_index]
                for assignment in assignments
            }
            events, embeddings_generated, embedding_latency_ms = self._recognize_tracks(
                stream_frame.frame_id,
                stream_frame.frame,
                detection_by_track,
            )
            tracks_to_display = snapshot_tracks(tracks)
            return (
                tracks_to_display,
                events,
                track_counts(tracks, tracks_to_display),
                len(detections),
                embeddings_generated,
                detection_latency_ms,
                embedding_latency_ms,
            )
        except Exception as error:
            print(f"[WARNING] Could not run InsightFace on frame {stream_frame.frame_id}: {error}", file=sys.stderr)
            if self.on_pipeline_error is not None:
                self.on_pipeline_error(stream_frame.frame_id, error)
            tracks = list(self.tracker.tracks.values())
            tracks_to_display = snapshot_tracks(tracks)
            return tracks_to_display, [], track_counts(tracks, tracks_to_display), 0, 0, 0.0, 0.0

    def _recognize_tracks(self, frame_id: int, frame: np.ndarray, detection_by_track: dict):
        events = []
        embeddings_generated = 0
        embedding_started = time.monotonic()
        selected = self.tracker.select_for_recognition(frame_id, maximum=self.max_embeddings_per_cycle)
        for track in selected:
            event, embedded = self._recognize_track(frame, track, detection_by_track.get(track.track_id))
            embeddings_generated += int(embedded)
            if event is not None:
                events.append(event)
        embedding_latency_ms = (time.monotonic() - embedding_started) * 1000.0
        return events, embeddings_generated, embedding_latency_ms

    def _recognize_track(self, frame: np.ndarray, track, detection):
        if detection is None:
            return None, False
        embedding = self.engine.embed_detected_face(frame, detection)
        if embedding is None:
            return None, False
        self.tracker.record_embedding(track.track_id, embedding.embedding, self.embedding_change_threshold)
        name, score = self.recognizer.search(embedding.embedding, self.top_k)[0]
        return self.tracker.apply_recognition(track.track_id, name, score, self.threshold), True

    def _store_result(self, result_id: int, stream_frame: StreamFrame, started: float, outcome) -> int:
        tracks, events, counts, detected_faces, embeddings_generated, detection_latency_ms, embedding_latency_ms = outcome
        active_tracks, visible_tracks, stale_tracks = counts
        latency_ms = (time.monotonic() - started) * 1000.0
        result_id += 1
        result = RecognitionResult(
            result_id=result_id,
            frame_id=stream_frame.frame_id,
            timestamp=time.monotonic(),
            latency_ms=latency_ms,
            tracks=tracks,
            events=events,
            active_tracks=active_tracks,
            visible_tracks=visible_tracks,
            stale_tracks=stale_tracks,
            detected_faces=detected_faces,
            embeddings_generated=embeddings_generated,
            detection_latency_ms=detection_latency_ms,
            embedding_latency_ms=embedding_latency_ms,
        )
        with self._lock:
            self._latest_result = result
            self._processed_frames += 1
            self._embeddings_generated += embeddings_generated
            self._latency_total_ms += latency_ms
            self._last_latency_ms = latency_ms
            self._last_detection_latency_ms = detection_latency_ms
            self._detection_latency_total_ms += detection_latency_ms
            self._last_embedding_latency_ms = embedding_latency_ms
            self._embedding_latency_total_ms += embedding_latency_ms
            self._active_tracks = active_tracks
            self._visible_tracks = visible_tracks
            self._stale_tracks = stale_tracks
        return result_id


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
        embeddings_generated,
        last_latency_ms,
        average_latency_ms,
        last_detection_latency_ms,
        average_detection_latency_ms,
        last_embedding_latency_ms,
        average_embedding_latency_ms,
        active_tracks,
        visible_tracks,
        stale_tracks,
    ) = worker.stats()
    capture_fps = (capture_frames - last_capture_frames) / elapsed
    recognition_fps = (recognition_frames - last_recognition_frames) / elapsed
    embedding_fps = embeddings_generated / max(1, recognition_frames)
    display_fps = (display_frames - last_display_frames) / elapsed
    print(
        "PROFILE "
        f"capture_fps={capture_fps:.1f} "
        f"display_fps={display_fps:.1f} "
        f"recognition_fps={recognition_fps:.1f} "
        f"embedding_per_cycle={embedding_fps:.1f} "
        f"last_latency_ms={last_latency_ms:.1f} "
        f"avg_latency_ms={average_latency_ms:.1f} "
        f"last_detection_ms={last_detection_latency_ms:.1f} "
        f"avg_detection_ms={average_detection_latency_ms:.1f} "
        f"last_embedding_ms={last_embedding_latency_ms:.1f} "
        f"avg_embedding_ms={average_embedding_latency_ms:.1f} "
        f"active_tracks={active_tracks} "
        f"visible_tracks={visible_tracks} "
        f"stale_tracks={stale_tracks}",
        file=sys.stderr,
    )
    return capture_frames, recognition_frames, display_frames, now


def poll_exit() -> bool:
    return cv2.waitKey(1) & 0xFF in (27, ord("q"))


def render_recognition_result(
    args,
    result: RecognitionResult | None,
    source_frame: np.ndarray,
    display_frame: np.ndarray,
    display_scale: float,
    output,
    mqtt_client,
    consumed_result_id: int,
) -> int:
    if result is None:
        return consumed_result_id
    stale = time.monotonic() - result.timestamp > max(0.5, 2.0 / args.recognition_fps)
    draw_tracks(display_frame, result.tracks, display_scale, stale, getattr(args, "wanted", None))
    if result.result_id == consumed_result_id:
        return consumed_result_id
    event_payloads = handle_result_events(result, source_frame, output)
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
    edge_session = getattr(args, "_edge_session", None)
    if edge_session is not None:
        session_id = edge_session.presence_due(result.detected_faces, args.face_presence_interval)
        if session_id is not None:
            publish_mqtt(
                mqtt_client,
                stream_activity_topic(args.source_device_id),
                payloads.face_presence(
                    device_id=args.source_device_id,
                    stream_session_id=session_id,
                    face_count=result.detected_faces,
                ),
            )
            print(f"[MQTT] face_presence published session={session_id} faces={result.detected_faces}")
    return result.result_id


def update_profile(
    args,
    reader: LatestFrameReader,
    worker: RecognitionWorker,
    display_frames: int,
    last_capture_frames: int,
    last_recognition_frames: int,
    last_display_frames: int,
    last_profile_time: float,
) -> tuple[int, int, int, float]:
    if not args.profile or time.monotonic() - last_profile_time < 2.0:
        return last_capture_frames, last_recognition_frames, last_display_frames, last_profile_time
    return print_profile(
        reader,
        worker,
        display_frames,
        last_capture_frames,
        last_recognition_frames,
        last_display_frames,
        last_profile_time,
    )


def render_next_frame(
    args,
    result: RecognitionResult | None,
    source_frame: np.ndarray,
    source_fps: float,
    output,
    mqtt_client,
    consumed_result_id: int,
) -> int:
    """Render one frame's recognition result; returns the consumed result id."""
    display_frame, display_scale = resize_for_display(source_frame, 1280)
    if display_frame is source_frame:
        display_frame = display_frame.copy()
    consumed_result_id = render_recognition_result(
        args,
        result,
        source_frame,
        display_frame,
        display_scale,
        output,
        mqtt_client,
        consumed_result_id,
    )
    output.write_frame(display_frame, source_fps)
    cv2.imshow(WINDOW_TITLE, display_frame)
    return consumed_result_id


def run_display_loop(args, reader: LatestFrameReader, worker: RecognitionWorker, output, mqtt_client) -> None:
    display_frames = 0
    consumed_result_id = 0
    last_rendered_frame_id = 0
    last_rendered_result_id = 0
    last_capture_frames = 0
    last_recognition_frames = 0
    last_display_frames = 0
    last_profile_time = time.monotonic()
    while True:
        stream_frame = reader.latest()
        if stream_frame is None:
            if poll_exit():
                return
            continue

        result = worker.latest_result()
        result_id = result.result_id if result is not None else 0
        if stream_frame.frame_id == last_rendered_frame_id and result_id == last_rendered_result_id:
            if poll_exit():
                return
            continue
        last_rendered_frame_id = stream_frame.frame_id
        last_rendered_result_id = result_id
        consumed_result_id = render_next_frame(
            args,
            result,
            stream_frame.frame,
            stream_frame.source_fps,
            output,
            mqtt_client,
            consumed_result_id,
        )
        display_frames += 1
        last_capture_frames, last_recognition_frames, last_display_frames, last_profile_time = update_profile(
            args,
            reader,
            worker,
            display_frames,
            last_capture_frames,
            last_recognition_frames,
            last_display_frames,
            last_profile_time,
        )
        if poll_exit():
            return


def handle_result_events(result: RecognitionResult, frame: np.ndarray, output) -> list[dict[str, Any]]:
    event_payloads = []
    for event in result.events:
        snapshot = None
        if event.kind in {"identity_confirmed", "identity_changed"}:
            snapshot = output.save_snapshot(frame, event.track_id, event.label or "unknown", event.score or 0.0)
        log_event(event, snapshot)
        event_payloads.append(event_payload(event, str(snapshot) if snapshot is not None else None))
    return event_payloads


def connect_mqtt_client(args, edge_session) -> MqttClient | None:
    """Build and connect the MQTT client; raises on broker failure."""
    if not args.mqtt_host:
        return None
    client = MqttClient(
        host=args.mqtt_host,
        port=args.mqtt_port,
        client_id=args.mqtt_client_id,
        username=args.mqtt_username,
        password=password_from_env(args.mqtt_username, args.mqtt_password_env),
        ca_cert=args.mqtt_ca_cert,
        on_message_metadata=edge_session.update if edge_session is not None else None,
    )
    if edge_session is not None:
        client.subscribe(system_status_topic(args.source_device_id), qos=0)
    client.connect()
    publish_mqtt(
        client,
        system_status_topic(args.mqtt_client_id),
        payloads.system_status(
            device_id=args.mqtt_client_id,
            component="recognition",
            state="starting",
            message="Recognition pipeline is starting.",
        ),
    )
    return client


def main() -> int:
    args = parse_args()
    if platform.system() != "Windows":
        print("InsightFace + FAISS recognition is currently supported only on Windows. Use python app.py for detection.", file=sys.stderr)
        return 1

    from aiot.recognition.face_engine import FaceEngine
    from aiot.recognition.face_recognizer import FaceRecognizer
    from aiot.recognition.wanted import WantedList
    from aiot.streaming.stream_output import StreamOutput
    from aiot.tracking.face_tracker import FaceTracker

    args.wanted = WantedList(args.wanted_config)

    edge_session = CloudEdgeSession(args.source_device_id) if args.edge_triggered_session else None
    args._edge_session = edge_session
    try:
        mqtt_client = connect_mqtt_client(args, edge_session)
    except (MqttUnavailable, MqttConnectionError, MqttSubscriptionError) as error:
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
    if engine.startup_output:
        print(engine.startup_output, file=sys.stderr)
    print(f"SCRFD providers: {', '.join(engine.detector_providers)}", file=sys.stderr)
    print(f"ArcFace providers: {', '.join(engine.recognition_providers)}", file=sys.stderr)
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
    reader = LatestFrameReader(
        args.source,
        mirror=not args.no_mirror,
        reconnect_delay=args.reconnect_delay,
        capture_enabled=edge_session.capture_enabled if edge_session is not None else None,
    )
    def on_pipeline_error(frame_id: int, error: Exception) -> None:
        publish_mqtt(
            mqtt_client,
            error_pipeline_topic(args.source_device_id or args.mqtt_client_id),
            payloads.error_event(
                component="recognition",
                device_id=args.source_device_id or args.mqtt_client_id,
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
        max_embeddings_per_cycle=args.max_embeddings_per_cycle,
        top_k=args.top_k,
        threshold=args.threshold,
        embedding_change_threshold=args.embedding_change_threshold,
        on_pipeline_error=on_pipeline_error,
    )

    reader.start()
    worker.start()
    try:
        run_display_loop(args, reader, worker, output, mqtt_client)
    except KeyboardInterrupt:
        return 0
    finally:
        publish_mqtt(
            mqtt_client,
            system_status_topic(args.mqtt_client_id),
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
