import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from aiot.recognition.face_engine import FaceDetection, FaceEmbedding
from aiot.tracking.face_tracker import TrackAssignment
from recognize_stream import (
    DisplayTrack,
    LatestFrameReader,
    RecognitionResult,
    RecognitionWorker,
    StreamFrame,
    handle_result_events,
    parse_args,
    render_recognition_result,
    run_display_loop,
    scale_bbox,
    snapshot_tracks,
    track_counts,
)


class ParseArgsTests(unittest.TestCase):
    @patch(
        "sys.argv",
        [
            "recognize_stream.py",
            "--recognition-fps",
            "8",
            "--profile",
            "--require-gpu",
            "--det-size",
            "512",
        ],
    )
    def test_parse_args_supports_new_gpu_and_profile_flags(self):
        args = parse_args()

        self.assertEqual(args.recognition_fps, 8.0)
        self.assertTrue(args.profile)
        self.assertTrue(args.require_gpu)
        self.assertEqual(args.det_size, 512)
        self.assertEqual(args.max_embeddings_per_cycle, 1)

    @patch(
        "sys.argv",
        [
            "recognize_stream.py",
            "--mqtt-host",
            "127.0.0.1",
            "--mqtt-port",
            "1884",
            "--mqtt-client-id",
            "recognition-test",
            "--mqtt-username",
            "recognizer",
            "--mqtt-password-env",
            "AIOT_MQTT_PASSWORD",
        ],
    )
    @patch.dict("os.environ", {"AIOT_MQTT_PASSWORD": "secret"})
    def test_parse_args_supports_mqtt_flags(self):
        args = parse_args()

        self.assertEqual(args.mqtt_host, "127.0.0.1")
        self.assertEqual(args.mqtt_port, 1884)
        self.assertEqual(args.mqtt_client_id, "recognition-test")
        self.assertEqual(args.mqtt_username, "recognizer")
        self.assertEqual(args.mqtt_password_env, "AIOT_MQTT_PASSWORD")

    @patch("sys.argv", ["recognize_stream.py", "--mqtt-username", "recognizer"])
    @patch.dict("os.environ", {}, clear=True)
    def test_mqtt_username_requires_password_env(self):
        with self.assertRaises(SystemExit):
            parse_args()


class ScaleBBoxTests(unittest.TestCase):
    def test_scale_bbox_supports_identity_scale_without_float_equality_branch(self):
        self.assertEqual(scale_bbox((1, 2, 3, 4), 1.0), (1, 2, 3, 4))

    def test_scale_bbox_scales_coordinates(self):
        self.assertEqual(scale_bbox((10, 20, 30, 40), 0.5), (5, 10, 15, 20))


class SnapshotTracksTests(unittest.TestCase):
    def test_snapshot_tracks_copies_runtime_fields(self):
        track = type(
            "Track",
            (),
            {
                "track_id": 7,
                "bbox": (1, 2, 3, 4),
                "label": "Alice",
                "score": 0.9,
                "status": "matched",
                "missed_frames": 0,
            },
        )()

        snapshot = snapshot_tracks([track])

        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0].track_id, 7)
        self.assertEqual(snapshot[0].bbox, (1, 2, 3, 4))
        self.assertEqual(snapshot[0].label, "Alice")
        self.assertEqual(snapshot[0].score, 0.9)
        self.assertEqual(snapshot[0].status, "matched")
        self.assertEqual(snapshot[0].missed_frames, 0)

    def test_snapshot_tracks_excludes_missed_tracks(self):
        active = type(
            "Track",
            (),
            {
                "track_id": 1,
                "bbox": (1, 2, 3, 4),
                "label": None,
                "score": None,
                "status": "pending",
                "missed_frames": 0,
            },
        )()
        missed = type(
            "Track",
            (),
            {
                "track_id": 2,
                "bbox": (5, 6, 7, 8),
                "label": "Alice",
                "score": 0.9,
                "status": "matched",
                "missed_frames": 1,
            },
        )()

        snapshot = snapshot_tracks([active, missed])

        self.assertEqual([track.track_id for track in snapshot], [1])

    def test_track_counts_reports_active_visible_and_stale(self):
        active = type("Track", (), {"missed_frames": 0})()
        stale = type("Track", (), {"missed_frames": 2})()

        self.assertEqual(track_counts([active, stale], [active]), (1, 1, 1))


class LatestFrameReaderTests(unittest.TestCase):
    def test_latest_without_frames_returns_none(self):
        reader = LatestFrameReader("rtsp://127.0.0.1:8554/camera", mirror=False, reconnect_delay=1.0)
        self.assertIsNone(reader.latest())


class SplitRecognitionWorkerTests(unittest.TestCase):
    def test_worker_embeds_only_selected_track_with_default_budget(self):
        first = type("Track", (), {"track_id": 1, "bbox": (0, 0, 100, 100), "label": None, "score": None, "status": "pending", "missed_frames": 0})()
        second = type("Track", (), {"track_id": 2, "bbox": (200, 0, 300, 100), "label": None, "score": None, "status": "pending", "missed_frames": 0})()
        landmarks = np.array([[10, 10], [40, 10], [25, 25], [12, 40], [38, 40]], dtype="float32")
        detections = [
            FaceDetection(first.bbox, 0.9, landmarks),
            FaceDetection(second.bbox, 0.9, landmarks),
        ]

        class Engine:
            def __init__(self):
                self.embedded = []

            def detect_faces(self, _frame):
                return detections

            def embed_detected_face(self, _frame, detection):
                self.embedded.append(detection)
                return FaceEmbedding(detection.bbox, np.array([1.0, 0.0], dtype="float32"))

        class Tracker:
            def update_with_assignments(self, boxes, _frame_id):
                self.boxes = boxes
                return [first, second], [TrackAssignment(1, 0), TrackAssignment(2, 1)]

            def select_for_recognition(self, _frame_id, maximum):
                self.maximum = maximum
                return [first][:maximum]

            def apply_recognition(self, *_args):
                return None

        class Recognizer:
            def __init__(self):
                self.calls = 0

            def search(self, _embedding, _top_k):
                self.calls += 1
                return [("Alice", 0.9)]

        engine = Engine()
        tracker = Tracker()
        recognizer = Recognizer()
        worker = RecognitionWorker(None, engine, recognizer, tracker, 6.0, 1, 5, 0.45)
        frame = StreamFrame(1, np.zeros((320, 320, 3), dtype="uint8"), 0.0, 30.0)

        outcome = worker._process_frame(frame)

        self.assertEqual(tracker.boxes, [item.bbox for item in detections])
        self.assertEqual(tracker.maximum, 1)
        self.assertEqual(len(engine.embedded), 1)
        self.assertIs(engine.embedded[0], detections[0])
        self.assertEqual(recognizer.calls, 1)
        self.assertEqual(outcome[3], 2)
        self.assertEqual(outcome[4], 1)


class DisplayLoopTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(profile=False, recognition_fps=6.0, source="rtsp://camera")
        self.frame = np.zeros((100, 100, 3), dtype="uint8")
        self.track = DisplayTrack(1, (10, 10, 40, 40), "Alice", 0.9, "matched", 0)
        self.event = SimpleNamespace(
            kind="identity_confirmed", track_id=1, label="Alice", score=0.9, previous_label=None
        )
        self.result = RecognitionResult(
            result_id=4,
            frame_id=3,
            timestamp=10.0,
            latency_ms=12.0,
            tracks=[self.track],
            events=[self.event],
            active_tracks=1,
            visible_tracks=1,
            stale_tracks=0,
            detected_faces=1,
            embeddings_generated=1,
            detection_latency_ms=3.0,
            embedding_latency_ms=4.0,
        )

    @patch("recognize_stream.log_event")
    def test_handle_result_events_saves_snapshot_only_for_identity_events(self, log_event):
        output = Mock()
        output.save_snapshot.return_value = Path("snapshot.jpg")
        unknown = SimpleNamespace(
            kind="unknown", track_id=2, label=None, score=None, previous_label="Alice"
        )

        payloads = handle_result_events(
            RecognitionResult(
                **{**self.result.__dict__, "events": [self.event, unknown]}
            ),
            self.frame,
            output,
        )

        output.save_snapshot.assert_called_once_with(self.frame, 1, "Alice", 0.9)
        self.assertEqual(payloads[0]["snapshot_path"], "snapshot.jpg")
        self.assertNotIn("snapshot_path", payloads[1])
        self.assertEqual(log_event.call_count, 2)

    @patch("recognize_stream.publish_mqtt")
    @patch("recognize_stream.handle_result_events", return_value=[{"kind": "identity_confirmed"}])
    @patch("recognize_stream.draw_tracks")
    @patch("recognize_stream.time.monotonic", return_value=10.1)
    def test_render_result_uses_source_frame_and_publishes_once(
        self, _monotonic, draw_tracks, handle_events, publish_mqtt
    ):
        output = Mock()
        display_frame = self.frame.copy()

        consumed = render_recognition_result(
            self.args, self.result, self.frame, display_frame, 1.0, output, Mock(), 0
        )

        self.assertEqual(consumed, 4)
        draw_tracks.assert_called_once_with(display_frame, [self.track], 1.0, False)
        handle_events.assert_called_once_with(self.result, self.frame, output)
        self.assertEqual(publish_mqtt.call_args.args[1], "recognition/result")
        self.assertEqual(publish_mqtt.call_args.args[2]["result_id"], 4)

    @patch("recognize_stream.poll_exit", side_effect=[False, True])
    @patch("recognize_stream.cv2.imshow")
    @patch("recognize_stream.render_recognition_result", side_effect=[4, 4])
    def test_reuses_result_without_skipping_new_frames(self, render_result, _imshow, _poll_exit):
        reader = Mock()
        reader.latest.side_effect = [
            StreamFrame(1, self.frame, 0.0, 30.0),
            StreamFrame(2, self.frame.copy(), 0.1, 30.0),
        ]
        worker = Mock()
        worker.latest_result.return_value = self.result
        output = Mock()

        run_display_loop(self.args, reader, worker, output, Mock())

        self.assertEqual(render_result.call_count, 2)
        self.assertEqual(output.write_frame.call_count, 2)

    @patch("recognize_stream.poll_exit", return_value=True)
    def test_no_frame_exits_without_output(self, _poll_exit):
        reader = Mock()
        reader.latest.return_value = None
        output = Mock()

        run_display_loop(self.args, reader, Mock(), output, Mock())

        output.write_frame.assert_not_called()


if __name__ == "__main__":
    unittest.main()
