import tempfile
import unittest
from pathlib import Path

from aiot.recognition.chokepoint_groundtruth import (
    BoundingBoxDetection,
    GroundTruthPerson,
    discover_sequences,
    match_persons_to_detections,
    parse_sequence,
)


def _write_xml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


_P1L_XML = """<!DOCTYPE GroundTruth>
<dataset name="P1L_S1_C1">
 <frame number="00000000"/>
 <frame number="00000001">
  <person id="0014">
   <leftEye x="228" y="136"/>
   <rightEye x="244" y="134"/>
  </person>
 </frame>
 <frame number="00000002">
  <person id="0005">
   <leftEye x="100" y="200"/>
   <rightEye x="120" y="201"/>
  </person>
 </frame>
</dataset>
"""


class SequenceParsingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _layout_p1l(self) -> Path:
        image_dir = self.root / "P1L_S1" / "P1L_S1_C1" / "P1L_S1_C1"
        _touch(image_dir / "00000000.jpg")
        _touch(image_dir / "00000001.jpg")
        _touch(image_dir / "00000002.jpg")
        _write_xml(self.root / "P1L_S1_C1.xml", _P1L_XML)
        return image_dir

    def test_parses_p1l_sequence_with_empty_and_person_frames(self):
        image_dir = self._layout_p1l()
        sequence = parse_sequence(self.root / "P1L_S1_C1.xml", image_dir)
        self.assertEqual(sequence.name, "P1L_S1_C1")
        self.assertEqual(sequence.frames[1].sequence_name, "P1L_S1_C1")
        self.assertEqual(sequence.portal, "P1L")
        self.assertEqual(sequence.session, "S1")
        self.assertEqual(sequence.camera, "C1")
        self.assertEqual(sequence.partition, ("P1L", "S1"))
        self.assertIsNone(sequence.sequence_suffix)
        self.assertEqual(sequence.frame_count, 3)
        self.assertEqual(sequence.person_frame_count, 2)
        self.assertEqual(sequence.empty_frame_count, 1)
        self.assertTrue(sequence.frames[0].is_empty)
        self.assertFalse(sequence.frames[1].is_empty)
        person = sequence.frames[1].persons[0]
        self.assertEqual(person.identity, "0014")
        self.assertEqual(person.left_eye, (228.0, 136.0))
        self.assertEqual(person.right_eye, (244.0, 134.0))
        self.assertEqual(person.eye_midpoint, (236.0, 135.0))
        self.assertEqual(sequence.frames[1].image_path, image_dir / "00000001.jpg")

    def test_parses_p2e_suffixed_sequence(self):
        image_dir = self.root / "P2E_S1" / "P2E_S1_C2" / "P2E_S1_C2.2"
        _touch(image_dir / "00000174.jpg")
        _write_xml(
            self.root / "P2E_S1_C2.2.xml",
            """<!DOCTYPE GroundTruth>
<dataset name="P2E_S1_C2">
 <frame number="00000174">
  <person id="0015">
   <leftEye x="616" y="148"/>
   <rightEye x="632" y="149"/>
  </person>
 </frame>
</dataset>
""",
        )
        sequence = parse_sequence(self.root / "P2E_S1_C2.2.xml", image_dir)
        self.assertEqual(sequence.name, "P2E_S1_C2.2")
        self.assertEqual(sequence.frames[174].sequence_name, "P2E_S1_C2.2")
        self.assertEqual(sequence.sequence_suffix, ".2")
        self.assertEqual(sequence.partition, ("P2E", "S1"))
        self.assertEqual(sequence.frame_count, 1)
        self.assertEqual(sequence.frames[174].persons[0].identity, "0015")

    def test_discover_sequences_maps_p1l_and_p2e_directories(self):
        p1l_dir = self.root / "P1L_S1" / "P1L_S1_C1" / "P1L_S1_C1"
        p2e_dir = self.root / "P2E_S1" / "P2E_S1_C2" / "P2E_S1_C2.1"
        for number in ("00000000", "00000001", "00000002"):
            _touch(p1l_dir / f"{number}.jpg")
        _touch(p2e_dir / "00000000.jpg")
        groundtruth = self.root / "groundtruth" / "groundtruth"
        _write_xml(groundtruth / "P1L_S1_C1.xml", _P1L_XML)
        _write_xml(
            groundtruth / "P2E_S1_C2.1.xml",
            """<!DOCTYPE GroundTruth>
<dataset name="P2E_S1_C2">
 <frame number="00000000">
  <person id="0010">
   <leftEye x="1" y="1"/>
   <rightEye x="2" y="1"/>
  </person>
 </frame>
</dataset>
""",
        )
        sequences = discover_sequences(self.root)
        self.assertEqual([s.name for s in sequences], ["P1L_S1_C1", "P2E_S1_C2.1"])
        self.assertEqual(sequences[0].image_dir, p1l_dir)
        self.assertEqual(sequences[1].image_dir, p2e_dir)

    def test_overlapping_frame_numbers_across_p2e_pairs_stay_separate(self):
        dir_one = self.root / "P2E_S2" / "P2E_S2_C3" / "P2E_S2_C3.1"
        dir_two = self.root / "P2E_S2" / "P2E_S2_C3" / "P2E_S2_C3.2"
        _touch(dir_one / "00000400.jpg")
        _touch(dir_two / "00000400.jpg")
        _write_xml(
            self.root / "P2E_S2_C3.1.xml",
            """<!DOCTYPE GroundTruth>
<dataset name="P2E_S2_C3">
 <frame number="00000400">
  <person id="0028">
   <leftEye x="1" y="1"/>
   <rightEye x="2" y="1"/>
  </person>
 </frame>
</dataset>
""",
        )
        _write_xml(
            self.root / "P2E_S2_C3.2.xml",
            """<!DOCTYPE GroundTruth>
<dataset name="P2E_S2_C3">
 <frame number="00000400">
  <person id="0002">
   <leftEye x="10" y="10"/>
   <rightEye x="12" y="10"/>
  </person>
 </frame>
</dataset>
""",
        )
        first = parse_sequence(self.root / "P2E_S2_C3.1.xml", dir_one)
        second = parse_sequence(self.root / "P2E_S2_C3.2.xml", dir_two)
        self.assertEqual(first.frames[400].persons[0].identity, "0028")
        self.assertEqual(second.frames[400].persons[0].identity, "0002")
        self.assertIsNot(first.frames[400], second.frames[400])

    def test_missing_eyes_parsed_as_none(self):
        image_dir = self.root / "P1L_S1" / "P1L_S1_C1" / "P1L_S1_C1"
        _touch(image_dir / "00000000.jpg")
        _write_xml(
            self.root / "P1L_S1_C1.xml",
            """<!DOCTYPE GroundTruth>
<dataset name="P1L_S1_C1">
 <frame number="00000000">
  <person id="0003"/>
 </frame>
</dataset>
""",
        )
        sequence = parse_sequence(self.root / "P1L_S1_C1.xml", image_dir)
        person = sequence.frames[0].persons[0]
        self.assertIsNone(person.left_eye)
        self.assertIsNone(person.right_eye)
        self.assertIsNone(person.eye_midpoint)

    def test_rejects_frame_without_jpg(self):
        image_dir = self.root / "P1L_S1" / "P1L_S1_C1" / "P1L_S1_C1"
        _touch(image_dir / "00000000.jpg")
        _write_xml(
            self.root / "P1L_S1_C1.xml",
            """<!DOCTYPE GroundTruth>
<dataset name="P1L_S1_C1">
 <frame number="00000000"/>
 <frame number="00000001"/>
</dataset>
""",
        )
        with self.assertRaises(FileNotFoundError):
            parse_sequence(self.root / "P1L_S1_C1.xml", image_dir)

    def test_rejects_unrecognized_xml_name(self):
        image_dir = self.root / "somewhere"
        _write_xml(self.root / "not_a_sequence.xml", "<dataset/>")
        with self.assertRaises(ValueError):
            parse_sequence(self.root / "not_a_sequence.xml", image_dir)

    def test_rejects_xml_without_frames(self):
        image_dir = self.root / "P1L_S1" / "P1L_S1_C1" / "P1L_S1_C1"
        _touch(image_dir / "00000000.jpg")
        _write_xml(self.root / "P1L_S1_C1.xml", "<dataset/>")
        with self.assertRaises(ValueError):
            parse_sequence(self.root / "P1L_S1_C1.xml", image_dir)


class DetectionMatchingTests(unittest.TestCase):
    @staticmethod
    def _person(identity, left=(100.0, 100.0), right=(110.0, 100.0)):
        return GroundTruthPerson(identity, left, right)

    def _detection(self, bbox, confidence=0.9):
        return BoundingBoxDetection(bbox, confidence)

    def test_no_detections_means_all_missed(self):
        persons = (self._person("0001"), self._person("0002"))
        result = match_persons_to_detections(persons, [])
        self.assertEqual(result.matches, ())
        self.assertEqual(tuple(p.identity for p in result.missed_persons), ("0001", "0002"))
        self.assertEqual(result.spurious_detection_indices, ())

    def test_midpoint_inside_bbox_matches(self):
        persons = (self._person("0001"),)
        detections = [self._detection((90, 90, 130, 130))]
        result = match_persons_to_detections(persons, detections)
        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.matches[0].identity, "0001")
        self.assertEqual(result.matches[0].detection_index, 0)
        self.assertEqual(result.missed_persons, ())
        self.assertEqual(result.spurious_detection_indices, ())

    def test_midpoint_outside_bbox_is_missed_and_detection_spurious(self):
        persons = (self._person("0001", left=(50.0, 50.0), right=(60.0, 50.0)),)
        detections = [self._detection((200, 200, 260, 260))]
        result = match_persons_to_detections(persons, detections)
        self.assertEqual(result.matches, ())
        self.assertEqual(tuple(p.identity for p in result.missed_persons), ("0001",))
        self.assertEqual(result.spurious_detection_indices, (0,))

    def test_nearest_bbox_center_wins_among_candidates(self):
        persons = (self._person("0001"),)
        detections = [
            self._detection((0, 0, 220, 220), confidence=0.99),
            self._detection((95, 95, 115, 115), confidence=0.5),
        ]
        result = match_persons_to_detections(persons, detections)
        self.assertEqual(result.matches[0].detection_index, 1)
        self.assertEqual(result.spurious_detection_indices, (0,))

    def test_higher_confidence_wins_on_equal_distance(self):
        persons = (self._person("0001", left=(95.0, 100.0), right=(105.0, 100.0)),)
        detections = [
            self._detection((80, 80, 120, 120), confidence=0.5),
            self._detection((90, 90, 110, 110), confidence=0.95),
        ]
        result = match_persons_to_detections(persons, detections)
        self.assertEqual(result.matches[0].detection_index, 1)

    def test_lower_detection_index_wins_on_full_tie(self):
        persons = (self._person("0001", left=(95.0, 100.0), right=(105.0, 100.0)),)
        detections = [
            self._detection((80, 80, 120, 120), confidence=0.8),
            self._detection((90, 90, 110, 110), confidence=0.8),
        ]
        result = match_persons_to_detections(persons, detections)
        self.assertEqual(result.matches[0].detection_index, 0)

    def test_each_detection_assigned_to_at_most_one_person(self):
        persons = (
            self._person("0001", left=(100.0, 100.0), right=(110.0, 100.0)),
            self._person("0002", left=(100.0, 130.0), right=(110.0, 130.0)),
        )
        detections = [self._detection((80, 80, 140, 160))]
        result = match_persons_to_detections(persons, detections)
        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.matches[0].identity, "0002")
        self.assertEqual(tuple(p.identity for p in result.missed_persons), ("0001",))
        self.assertEqual(result.spurious_detection_indices, ())

    def test_missing_eyes_person_always_missed(self):
        persons = (GroundTruthPerson("0003", None, None),)
        detections = [self._detection((0, 0, 200, 200))]
        result = match_persons_to_detections(persons, detections)
        self.assertEqual(result.matches, ())
        self.assertEqual(tuple(p.identity for p in result.missed_persons), ("0003",))
        self.assertEqual(result.spurious_detection_indices, (0,))

    def test_works_with_face_engine_detection_shape(self):
        try:
            from aiot.recognition.face_engine import FaceDetection
        except ImportError:
            self.skipTest("recognition dependencies not installed")
        persons = (self._person("0001"),)
        detections = [FaceDetection((90, 90, 130, 130), 0.9, None)]
        result = match_persons_to_detections(persons, detections)
        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.matches[0].identity, "0001")


if __name__ == "__main__":
    unittest.main()