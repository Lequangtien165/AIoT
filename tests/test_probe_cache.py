import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from aiot.recognition.chokepoint_groundtruth import ChokepointSequence, GroundTruthFrame
from aiot.recognition.face_engine import FaceDetection
from aiot.recognition.probe_cache import (
    EMBEDDINGS_NAME,
    FINGERPRINT_NAME,
    MANIFEST_NAME,
    ProbeCacheNotFound,
    ProbeCacheStale,
    build_cache,
    build_fingerprint,
    fingerprint_id,
    frame_key,
    load_cache,
)

FRAME_IMAGE = np.zeros((160, 160, 3), dtype="uint8")
EMBEDDING = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")


def _frame(portal, session, camera, number, image_path, persons=()):
    return GroundTruthFrame(
        portal=portal,
        session=session,
        camera=camera,
        sequence_suffix=None,
        frame_number=number,
        image_path=image_path,
        persons=tuple(persons),
    )


def _sequence(portal, session, camera, frames):
    name = f"{portal}_S{session[1:]}_C{camera[1:]}"
    return ChokepointSequence(
        portal=portal,
        session=session,
        camera=camera,
        sequence_suffix=None,
        xml_path=Path(f"/tmp/{name}.xml"),
        image_dir=Path(f"/tmp/{portal}_S{session[1:]}/{name}"),
        frames={frame.frame_number: frame for frame in frames},
    )


def _engine():
    engine = mock.MagicMock()
    engine.requested_providers = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    engine.detector_providers = list(engine.requested_providers)
    engine.recognition_providers = list(engine.requested_providers)
    engine.detect_faces.return_value = [FaceDetection((10, 20, 110, 210), 0.93, None)]
    engine.embed_detected_face.return_value = SimpleNamespace(embedding=EMBEDDING)
    return engine


class ProbeCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.frames = [
            _frame("P1L", "S1", "C1", 0, self.tmp / "00000000.jpg"),
            _frame("P1L", "S1", "C1", 1, self.tmp / "00000001.jpg"),
        ]
        for frame in self.frames:
            frame.image_path.write_bytes(b"fake-jpeg")
        self.sequence = _sequence("P1L", "S1", "C1", self.frames)

    def _build(self):
        engine = _engine()
        fingerprint = build_fingerprint(engine, 640, 0.5, 0.9)
        with mock.patch("aiot.recognition.probe_cache.cv2.imread", return_value=FRAME_IMAGE):
            cache = build_cache(self.tmp / "probe_cache", [self.sequence], engine, fingerprint)
        return cache, fingerprint

    def test_build_then_load_round_trips_entries(self):
        cache, fingerprint = self._build()
        self.assertEqual(len(cache), 2)
        self.assertTrue((self.tmp / "probe_cache" / MANIFEST_NAME).exists())
        self.assertTrue((self.tmp / "probe_cache" / EMBEDDINGS_NAME).exists())
        self.assertTrue((self.tmp / "probe_cache" / FINGERPRINT_NAME).exists())
        entry = cache.get(frame_key(self.sequence, 0))
        self.assertEqual(entry.status, "ok")
        self.assertIsNotNone(entry.detection_latency_ms)
        self.assertGreater(entry.detection_latency_ms, 0.0)
        self.assertEqual(len(entry.detections), 1)
        self.assertEqual(entry.detections[0].bbox, (10, 20, 110, 210))
        self.assertEqual(entry.detections[0].confidence, 0.93)
        self.assertEqual(entry.embedding_indices, (0,))
        self.assertEqual(len(entry.embedding_latency_ms), 1)
        self.assertIsNotNone(entry.embedding_latency_ms[0])
        self.assertTrue(np.allclose(cache.vectors[0], EMBEDDING))
        loaded = load_cache(self.tmp / "probe_cache", fingerprint)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded.probe_cache_id, cache.probe_cache_id)
        self.assertEqual(loaded.get(frame_key(self.sequence, 1)).status, "ok")
        self.assertGreaterEqual(loaded.build_seconds, 0.0)

    def test_load_missing_cache_raises_not_found(self):
        with self.assertRaises(ProbeCacheNotFound):
            load_cache(self.tmp / "missing")

    def test_load_stale_fingerprint_raises(self):
        cache, fingerprint = self._build()
        stale = dict(fingerprint)
        stale["det_size"] = 320
        with self.assertRaises(ProbeCacheStale):
            load_cache(self.tmp / "probe_cache", stale)

    def test_fingerprint_id_changes_with_det_size(self):
        engine = _engine()
        base = build_fingerprint(engine, 640, 0.5, 0.9)
        smaller = build_fingerprint(engine, 320, 0.5, 0.9)
        self.assertEqual(fingerprint_id(base), fingerprint_id(base))
        self.assertNotEqual(fingerprint_id(base), fingerprint_id(smaller))

    def test_get_unknown_key_returns_none(self):
        cache, _ = self._build()
        self.assertIsNone(cache.get("P1L_S1_C1/99999999"))

    def test_read_error_frames_are_cached_with_status(self):
        engine = _engine()
        fingerprint = build_fingerprint(engine, 640, 0.5, 0.9)

        def fake_imread(path, *args):
            if str(path).endswith("00000001.jpg"):
                return None
            return FRAME_IMAGE

        with mock.patch("aiot.recognition.probe_cache.cv2.imread", side_effect=fake_imread):
            cache = build_cache(self.tmp / "probe_cache", [self.sequence], engine, fingerprint)
        bad = cache.get(frame_key(self.sequence, 1))
        self.assertEqual(bad.status, "read_error")
        self.assertEqual(bad.detections, ())
        self.assertEqual(bad.embedding_indices, ())
        loaded = load_cache(self.tmp / "probe_cache", fingerprint)
        self.assertEqual(loaded.get(frame_key(self.sequence, 1)).status, "read_error")


if __name__ == "__main__":
    unittest.main()