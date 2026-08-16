import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from scripts.benchmark_chokepoint import (
    EmbeddingRecord,
    _overall_summary,
    collect_precheck_frames,
    collect_probes,
    percentile,
    run_evaluation,
    run_precheck,
)
from aiot.recognition.chokepoint_groundtruth import (
    BoundingBoxDetection,
    ChokepointSequence,
    GroundTruthFrame,
    GroundTruthPerson,
)
from aiot.recognition.face_engine import FaceDetection
from aiot.recognition.probe_cache import (
    build_cache,
    build_fingerprint,
)

GALLERY_VECTOR_A = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
GALLERY_VECTOR_B = np.array([0.0, 1.0, 0.0, 0.0], dtype="float32")
PROBE_VECTOR_A = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
PROBE_VECTOR_B = np.array([0.0, 1.0, 0.0, 0.0], dtype="float32")
PROBE_VECTOR_ORTHOGONAL = np.array([0.0, 0.0, 1.0, 0.0], dtype="float32")

FRAME_IMAGE = np.zeros((160, 160, 3), dtype="uint8")


def _person(identity="0001", left=(100.0, 100.0), right=(110.0, 100.0)):
    return GroundTruthPerson(identity, left, right)


def _frame(portal, session, camera, number, persons, suffix=None):
    return GroundTruthFrame(
        portal=portal,
        session=session,
        camera=camera,
        sequence_suffix=suffix,
        frame_number=number,
        image_path=Path(f"/tmp/{portal}_S{session[1:]}_C{camera[1:]}_{number:08d}.jpg"),
        persons=tuple(persons),
    )


def _record(identity, vector, portal="P1L", session="S1", camera="C1"):
    return EmbeddingRecord(
        path=f"/tmp/{identity}.pgm",
        portal=portal,
        session=session,
        camera=camera,
        identity=identity,
        status="ok",
        vector=vector,
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


class RunEvaluationTests(unittest.TestCase):
    def _engine(self, embedding=PROBE_VECTOR_A, detections=None):
        engine = mock.MagicMock()
        if detections is None:
            detections = [BoundingBoxDetection((0, 0, 200, 200), 0.9)]
        engine.detect_faces.return_value = detections
        engine.embed_detected_face.return_value = SimpleNamespace(embedding=embedding)
        return engine

    def _evaluate(self, gallery, frames, engine, threshold=0.45):
        with mock.patch("scripts.benchmark_chokepoint.cv2.imread", return_value=FRAME_IMAGE):
            return run_evaluation("run-x", "P1L", "S1", gallery, frames, engine, threshold)

    def test_correct_match_keeps_metric_formulas_exact(self):
        gallery = [_record("0001", GALLERY_VECTOR_A), _record("0002", GALLERY_VECTOR_B)]
        frames = [_frame("P2E", "S2", "C1", 0, (_person("0001"),))]
        predictions, run_summary, _ = self._evaluate(gallery, frames, self._engine())
        self.assertEqual(predictions[0]["outcome"], "correct")
        self.assertEqual(run_summary["accuracy"], 1.0)
        self.assertEqual(run_summary["false_reject_rate"], 0.0)
        self.assertEqual(run_summary["misidentification_rate"], 0.0)
        self.assertEqual(
            run_summary["accuracy"] + run_summary["false_reject_rate"] + run_summary["misidentification_rate"],
            1.0,
        )

    def test_below_threshold_enrolled_counts_as_false_reject(self):
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        frames = [_frame("P2E", "S2", "C1", 0, (_person("0001"),))]
        predictions, run_summary, _ = self._evaluate(
            gallery, frames, self._engine(embedding=PROBE_VECTOR_ORTHOGONAL)
        )
        self.assertEqual(predictions[0]["outcome"], "false_reject")
        self.assertEqual(run_summary["accuracy"], 0.0)
        self.assertEqual(run_summary["false_reject_rate"], 1.0)
        self.assertEqual(run_summary["misidentification_rate"], 0.0)

    def test_detection_miss_counts_as_false_reject(self):
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        frames = [_frame("P2E", "S2", "C1", 0, (_person("0001"),))]
        predictions, run_summary, _ = self._evaluate(gallery, frames, self._engine(detections=[]))
        self.assertEqual(predictions[0]["outcome"], "false_reject")
        self.assertEqual(predictions[0]["detection_status"], "missed")
        self.assertEqual(run_summary["false_reject_rate"], 1.0)

    def test_read_error_counts_as_false_reject(self):
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        frames = [_frame("P2E", "S2", "C1", 0, (_person("0001"),))]
        with mock.patch("scripts.benchmark_chokepoint.cv2.imread", return_value=None):
            predictions, run_summary, _ = run_evaluation(
                "run-x", "P1L", "S1", gallery, frames, mock.MagicMock(), 0.45
            )
        self.assertEqual(predictions[0]["outcome"], "false_reject")
        self.assertEqual(predictions[0]["detection_status"], "read_error")
        self.assertEqual(run_summary["false_reject_rate"], 1.0)

    def test_embedding_failure_counts_as_false_reject(self):
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        frames = [_frame("P2E", "S2", "C1", 0, (_person("0001"),))]
        engine = self._engine()
        engine.embed_detected_face.return_value = None
        predictions, run_summary, _ = self._evaluate(gallery, frames, engine)
        self.assertEqual(predictions[0]["outcome"], "false_reject")
        self.assertEqual(predictions[0]["embedding_status"], "embed_error")
        self.assertEqual(run_summary["false_reject_rate"], 1.0)

    def test_misidentification_when_above_threshold_but_wrong_person(self):
        gallery = [_record("0001", GALLERY_VECTOR_A), _record("0002", GALLERY_VECTOR_B)]
        frames = [_frame("P2E", "S2", "C1", 0, (_person("0001"),))]
        predictions, run_summary, _ = self._evaluate(
            gallery, frames, self._engine(embedding=PROBE_VECTOR_B)
        )
        self.assertEqual(predictions[0]["outcome"], "misidentified")
        self.assertEqual(predictions[0]["predicted_identity"], "0002")
        self.assertEqual(run_summary["misidentification_rate"], 1.0)

    def test_detected_not_enrolled_with_above_threshold_match_false_accepts(self):
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        frames = [_frame("P2E", "S2", "C1", 0, (_person("9999"),))]
        predictions, run_summary, _ = self._evaluate(gallery, frames, self._engine())
        self.assertEqual(predictions[0]["outcome"], "not_enrolled")
        self.assertEqual(predictions[0]["detection_status"], "matched")
        self.assertEqual(run_summary["not_enrolled"], 1)
        self.assertEqual(run_summary["false_accept_rate"], 1.0)

    def test_missed_not_enrolled_stays_not_enrolled_without_false_accept(self):
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        frames = [_frame("P2E", "S2", "C1", 0, (_person("9999"),))]
        predictions, run_summary, _ = self._evaluate(
            gallery, frames, self._engine(detections=[])
        )
        self.assertEqual(predictions[0]["outcome"], "not_enrolled")
        self.assertEqual(predictions[0]["detection_status"], "missed")
        self.assertEqual(run_summary["not_enrolled"], 1)
        self.assertEqual(run_summary["false_accept_rate"], 0.0)

    def test_empty_frame_touches_only_detection_counts(self):
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        frames = [_frame("P2E", "S2", "C1", 0, ())]
        predictions, run_summary, _ = self._evaluate(gallery, frames, self._engine())
        self.assertEqual(predictions, [])
        self.assertEqual(run_summary["probe_images"], 0)
        self.assertEqual(run_summary["empty_frames"], 1)
        self.assertEqual(run_summary["empty_frames_with_detections"], 1)
        self.assertEqual(run_summary["total_detections"], 1)
        self.assertEqual(run_summary["spurious_detections"], 1)

    def test_unmatched_detection_counts_as_spurious(self):
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        frames = [_frame("P2E", "S2", "C1", 0, (_person("0001"),))]
        detections = [BoundingBoxDetection((300, 300, 350, 350), 0.9)]
        predictions, run_summary, _ = self._evaluate(
            gallery, frames, self._engine(detections=detections)
        )
        self.assertEqual(predictions[0]["outcome"], "false_reject")
        self.assertEqual(predictions[0]["detection_status"], "missed")
        self.assertEqual(run_summary["total_detections"], 1)
        self.assertEqual(run_summary["spurious_detections"], 1)
        self.assertEqual(run_summary["missed_faces"], 1)
        self.assertEqual(run_summary["detection_recall"], 0.0)
        self.assertEqual(run_summary["detection_precision"], 0.0)

    def test_multiple_detections_match_one_and_spur_one(self):
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        frames = [_frame("P2E", "S2", "C1", 0, (_person("0001"),))]
        detections = [
            BoundingBoxDetection((0, 0, 200, 200), 0.95),
            BoundingBoxDetection((300, 300, 350, 350), 0.8),
        ]
        predictions, run_summary, _ = self._evaluate(
            gallery, frames, self._engine(detections=detections)
        )
        self.assertEqual(predictions[0]["outcome"], "correct")
        self.assertEqual(run_summary["total_detections"], 2)
        self.assertEqual(run_summary["matched_faces"], 1)
        self.assertEqual(run_summary["spurious_detections"], 1)
        self.assertEqual(run_summary["detection_recall"], 1.0)
        self.assertEqual(run_summary["detection_precision"], 0.5)

    def test_same_portal_probe_counts_same_scope(self):
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        frames = [_frame("P1L", "S2", "C1", 0, (_person("0001"),))]
        predictions, run_summary, _ = self._evaluate(gallery, frames, self._engine())
        self.assertEqual(predictions[0]["scope"], "same_portal_cross_session")
        self.assertEqual(run_summary["same_correct"], 1)
        self.assertEqual(run_summary["same_closed_set"], 1)
        self.assertEqual(run_summary["cross_closed_set"], 0)

    def test_two_gt_persons_share_one_detection(self):
        gallery = [_record("0001", GALLERY_VECTOR_A), _record("0002", GALLERY_VECTOR_B)]
        persons = (
            _person("0001", left=(100.0, 100.0), right=(110.0, 100.0)),
            _person("0002", left=(100.0, 130.0), right=(110.0, 130.0)),
        )
        frames = [_frame("P2E", "S2", "C1", 0, persons)]
        predictions, run_summary, _ = self._evaluate(gallery, frames, self._engine())
        self.assertEqual([p["outcome"] for p in predictions], ["correct", "false_reject"])
        self.assertEqual(run_summary["matched_faces"], 1)
        self.assertEqual(run_summary["missed_faces"], 1)

    def test_partition_counts_start_at_zero_for_late_cameras(self):
        gallery = [_record("0001", GALLERY_VECTOR_A), _record("0002", GALLERY_VECTOR_B)]
        frames = [
            _frame("P2E", "S2", "C1", 0, (_person("0001"),)),
            _frame("P2E", "S2", "C2", 0, (_person("0001"),)),
        ]
        predictions, run_summary, per_partition = self._evaluate(gallery, frames, self._engine())
        self.assertEqual([p["outcome"] for p in predictions], ["correct", "correct"])
        self.assertEqual(per_partition["P2E-S2-C1"]["counts"]["correct"], 1)
        self.assertEqual(per_partition["P2E-S2-C2"]["counts"]["correct"], 1)
        self.assertEqual(per_partition["P2E-S2-C2"]["counts"]["probe_images"], 1)
        self.assertEqual(run_summary["probe_images"], 2)
        self.assertEqual(run_summary["cross_closed_set"], 2)


class ProbeCollectionTests(unittest.TestCase):
    def test_collect_probes_excludes_gallery_partition_and_honors_limit(self):
        sequences = [
            _sequence("P1L", "S1", "C1", [_frame("P1L", "S1", "C1", 0, ()), _frame("P1L", "S1", "C1", 1, ())]),
            _sequence("P1L", "S2", "C1", [_frame("P1L", "S2", "C1", 0, ()), _frame("P1L", "S2", "C1", 1, ()), _frame("P1L", "S2", "C1", 2, ())]),
            _sequence("P2E", "S1", "C1", [_frame("P2E", "S1", "C1", 0, ()), _frame("P2E", "S1", "C1", 1, ()), _frame("P2E", "S1", "C1", 2, ()), _frame("P2E", "S1", "C1", 3, ())]),
        ]
        all_probes = collect_probes(sequences, "P1L", "S1")
        self.assertEqual(len(all_probes), 7)
        limited = collect_probes(sequences, "P1L", "S1", limit=4)
        self.assertEqual([f.frame_number for f in limited], [0, 1, 2, 0])

    def test_collect_precheck_frames_selects_person_and_empty_per_portal(self):
        sequences = [
            _sequence("P1L", "S1", "C1", [_frame("P1L", "S1", "C1", 0, ()), _frame("P1L", "S1", "C1", 1, (_person("0001"),))]),
            _sequence("P1L", "S1", "C2", [_frame("P1L", "S1", "C2", 0, ()), _frame("P1L", "S1", "C2", 1, (_person("0001"),))]),
            _sequence("P2E", "S1", "C1", [_frame("P2E", "S1", "C1", 0, ()), _frame("P2E", "S1", "C1", 1, (_person("0015"),))]),
        ]
        frames = collect_precheck_frames(sequences, count=2)
        portals = [frame.portal for frame in frames]
        self.assertEqual(portals, ["P1L", "P1L", "P2E", "P1L", "P1L", "P2E"])
        person = [f for f in frames if not f.is_empty]
        empty = [f for f in frames if f.is_empty]
        self.assertEqual(len(person), 3)
        self.assertEqual(len(empty), 3)
        self.assertEqual({f.portal for f in person}, {"P1L", "P2E"})
        self.assertEqual({f.portal for f in empty}, {"P1L", "P2E"})


class PrecheckTests(unittest.TestCase):
    def test_run_precheck_reports_person_and_empty_lines_per_portal(self):
        frames = [
            _frame("P1L", "S1", "C1", 1, (_person("0001"),)),
            _frame("P1L", "S1", "C1", 0, ()),
            _frame("P2E", "S1", "C1", 1, (_person("0015"),)),
            _frame("P2E", "S1", "C1", 0, ()),
        ]
        engine = mock.MagicMock()
        engine.detect_faces.return_value = [BoundingBoxDetection((0, 0, 200, 200), 0.9)]
        engine.embed_detected_face.return_value = SimpleNamespace(embedding=PROBE_VECTOR_A)
        output = io.StringIO()
        with mock.patch("scripts.benchmark_chokepoint.cv2.imread", return_value=FRAME_IMAGE):
            with contextlib.redirect_stdout(output):
                rc = run_precheck(frames, engine)
        self.assertEqual(rc, 0)
        text = output.getvalue()
        self.assertIn(
            "P1L person: 1 frames, read 1/1 ok, detected 1/1 frames, matched 1/1 faces, embedded 1/1",
            text,
        )
        self.assertIn("P1L empty: 1 frames, read 1/1 ok, with detections 1/1", text)
        self.assertIn("P2E person: 1 frames, read 1/1 ok", text)
        self.assertIn("P2E empty: 1 frames, read 1/1 ok, with detections 1/1", text)

    def test_run_precheck_prints_n_a_ratios_when_read_fails(self):
        frames = [
            _frame("P1L", "S1", "C1", 1, (_person("0001"),)),
            _frame("P1L", "S1", "C1", 0, ()),
        ]
        engine = mock.MagicMock()
        output = io.StringIO()
        with mock.patch("scripts.benchmark_chokepoint.cv2.imread", return_value=None):
            with contextlib.redirect_stdout(output):
                rc = run_precheck(frames, engine)
        self.assertEqual(rc, 0)
        text = output.getvalue()
        self.assertIn(
            "P1L person: 1 frames, read 0/1 ok, detected n/a frames, matched n/a faces, embedded n/a",
            text,
        )
        self.assertIn("P1L empty: 1 frames, read 0/1 ok, with detections n/a", text)
        engine.detect_faces.assert_not_called()


class OverallSummaryTests(unittest.TestCase):
    def _run_row(self, **values):
        base = {
            "closed_set": 10,
            "accuracy": 0.9,
            "same_portal_accuracy": None,
            "same_correct": 0,
            "same_closed_set": 0,
            "cross_portal_accuracy": None,
            "cross_correct": 0,
            "cross_closed_set": 0,
            "probe_images": 10,
            "not_enrolled": 0,
            "false_accept_rate": None,
            "matched_faces": 0,
            "missed_faces": 0,
            "total_detections": 0,
            "spurious_detections": 0,
            "empty_frames": 0,
            "empty_frames_with_detections": 0,
            "gt_face_frames": 0,
            "gt_faces": 0,
        }
        base.update(values)
        return base

    def test_micro_same_and_cross_use_their_own_denominators(self):
        rows = [
            self._run_row(
                closed_set=100,
                accuracy=0.9,
                same_portal_accuracy=0.8,
                same_correct=80,
                same_closed_set=100,
                cross_portal_accuracy=None,
                cross_correct=0,
                cross_closed_set=0,
            ),
            self._run_row(
                closed_set=100,
                accuracy=0.5,
                same_portal_accuracy=None,
                same_correct=0,
                same_closed_set=0,
                cross_portal_accuracy=0.5,
                cross_correct=50,
                cross_closed_set=100,
            ),
        ]
        overall = _overall_summary(rows, [])
        self.assertEqual(overall["micro_accuracy"], 0.7)
        self.assertEqual(overall["micro_same_portal_accuracy"], 0.8)
        self.assertEqual(overall["micro_cross_portal_accuracy"], 0.5)

    def test_percentile_never_indexes_negatively(self):
        self.assertEqual(percentile([3.0], 0.01), 3.0)
        self.assertEqual(percentile([], 0.95), None)


class ProbeCacheEvaluationTests(unittest.TestCase):
    def _cache_for(self, frames):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for frame in frames:
            frame.image_path.write_bytes(b"fake-jpeg")
        sequence = _sequence("P1L", "S1", "C1", frames)
        build_engine = mock.MagicMock()
        build_engine.requested_providers = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
        build_engine.detector_providers = list(build_engine.requested_providers)
        build_engine.recognition_providers = list(build_engine.requested_providers)
        build_engine.detect_faces.return_value = [
            FaceDetection((0, 0, 200, 200), 0.9, None)
        ]
        build_engine.embed_detected_face.return_value = SimpleNamespace(embedding=PROBE_VECTOR_A)
        fingerprint = build_fingerprint(build_engine, 640, 0.5, 0.9)
        with mock.patch("aiot.recognition.probe_cache.cv2.imread", return_value=FRAME_IMAGE):
            cache = build_cache(tmp / "probe_cache", [sequence], build_engine, fingerprint)
        return cache, fingerprint

    def _stats(self):
        return {
            "hits": 0,
            "misses": 0,
            "stale": 0,
            "lookup_times": [],
            "unique_keys": set(),
            "mode": "read",
            "probe_cache_id": "",
            "build_seconds": 0.0,
        }

    def test_run_evaluation_reads_from_probe_cache_without_inferring(self):
        frame = _frame("P1L", "S1", "C1", 0, (_person("0001"),))
        cache, _ = self._cache_for([frame])
        eval_engine = mock.MagicMock()
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        stats = self._stats()
        predictions, run_summary, _ = run_evaluation(
            "run-x", "P1L", "S1", gallery, [frame], eval_engine, 0.45,
            cache=cache, cache_stats=stats,
        )
        eval_engine.detect_faces.assert_not_called()
        eval_engine.embed_detected_face.assert_not_called()
        self.assertEqual(predictions[0]["outcome"], "correct")
        self.assertEqual(predictions[0]["inference_source"], "cached")
        self.assertEqual(predictions[0]["cache_entry_id"], "P1L_S1_C1/00000000")
        self.assertEqual(predictions[0]["probe_cache_id"], cache.probe_cache_id)
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 0)
        self.assertEqual(len(stats["lookup_times"]), 1)
        self.assertEqual(stats["unique_keys"], {"P1L_S1_C1/00000000"})

    def test_run_evaluation_cache_miss_raises_without_live_fallback(self):
        cached = _frame("P1L", "S1", "C1", 0, (_person("0001"),))
        cache, _ = self._cache_for([cached])
        missing = _frame("P1L", "S1", "C1", 5, (_person("0001"),))
        eval_engine = mock.MagicMock()
        gallery = [_record("0001", GALLERY_VECTOR_A)]
        stats = self._stats()
        with self.assertRaisesRegex(RuntimeError, "probe cache miss for P1L_S1_C1/00000005"):
            run_evaluation(
                "run-x", "P1L", "S1", gallery, [missing], eval_engine, 0.45,
                cache=cache, cache_stats=stats,
            )
        eval_engine.detect_faces.assert_not_called()
        self.assertEqual(stats["misses"], 1)


if __name__ == "__main__":
    unittest.main()