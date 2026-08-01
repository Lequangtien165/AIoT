import unittest
from unittest.mock import patch

from recognize_stream import LatestFrameReader, parse_args, scale_bbox, snapshot_tracks, track_counts


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


if __name__ == "__main__":
    unittest.main()
