import unittest
from unittest.mock import patch

from recognize_stream import LatestFrameReader, parse_args, snapshot_tracks


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
            },
        )()

        snapshot = snapshot_tracks([track])

        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0].track_id, 7)
        self.assertEqual(snapshot[0].bbox, (1, 2, 3, 4))
        self.assertEqual(snapshot[0].label, "Alice")
        self.assertEqual(snapshot[0].score, 0.9)
        self.assertEqual(snapshot[0].status, "matched")


class LatestFrameReaderTests(unittest.TestCase):
    def test_latest_without_frames_returns_none(self):
        reader = LatestFrameReader("rtsp://127.0.0.1:8554/camera", mirror=False, reconnect_delay=1.0)
        self.assertIsNone(reader.latest())


if __name__ == "__main__":
    unittest.main()
