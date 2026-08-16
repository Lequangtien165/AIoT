"""Parse ChokePoint ground-truth XML files and map detections to people.

ChokePoint annotates every camera sequence with one XML file listing all
frames. Frames that contain a face carry ``<person>`` blocks with ``leftEye``
and ``rightEye`` coordinates; the remaining frames are empty. P1L sequences
have a single XML and an unsuffixed image directory, while P2E sequences come
as ``.1``/``.2`` pairs, each with its own XML and a matching suffixed image
directory. The two P2E sequences of a camera are kept separate: their frame
numbers overlap but they annotate disjoint people.

Matching maps ground-truth people to detections by requiring the midpoint of
the two annotated eyes to fall inside a detection bounding box. Candidate
detections are resolved by nearest bbox center first, then highest
confidence, then lowest detection index.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

PORTAL_SEQUENCE_PATTERN = re.compile(
    r"^(?P<portal>[A-Z]+\d+[A-Z]+)_S(?P<session>\d+)_C(?P<camera>\d+)(?P<suffix>\.\d+)?$"
)


@dataclass(frozen=True)
class GroundTruthPerson:
    """One annotated person in a frame with raw eye coordinates."""

    identity: str
    left_eye: tuple[float, float] | None
    right_eye: tuple[float, float] | None

    @property
    def eye_midpoint(self) -> tuple[float, float] | None:
        """Midpoint of the two annotated eyes, or None when either is missing."""
        if self.left_eye is None or self.right_eye is None:
            return None
        return (
            (self.left_eye[0] + self.right_eye[0]) / 2.0,
            (self.left_eye[1] + self.right_eye[1]) / 2.0,
        )


@dataclass(frozen=True)
class GroundTruthFrame:
    """One annotated frame of a sequence and the people visible in it."""

    portal: str
    session: str
    camera: str
    sequence_suffix: str | None
    frame_number: int
    image_path: Path
    persons: tuple[GroundTruthPerson, ...]

    @property
    def is_empty(self) -> bool:
        return not self.persons

    @property
    def sequence_name(self) -> str:
        return _format_sequence_name(self.portal, self.session, self.camera, self.sequence_suffix)


def _format_sequence_name(
    portal: str, session: str, camera: str, suffix: str | None
) -> str:
    return f"{portal}_S{session[1:]}_C{camera[1:]}{suffix or ''}"


@dataclass(frozen=True)
class ChokepointSequence:
    """One annotated recording: a single XML plus its full-frame JPG directory."""

    portal: str
    session: str
    camera: str
    sequence_suffix: str | None
    xml_path: Path
    image_dir: Path
    frames: dict[int, GroundTruthFrame]

    @property
    def name(self) -> str:
        return _format_sequence_name(self.portal, self.session, self.camera, self.sequence_suffix)

    @property
    def partition(self) -> tuple[str, str]:
        return self.portal, self.session

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def person_frame_count(self) -> int:
        return sum(1 for frame in self.frames.values() if not frame.is_empty)

    @property
    def empty_frame_count(self) -> int:
        return sum(1 for frame in self.frames.values() if frame.is_empty)


@dataclass(frozen=True)
class BoundingBoxDetection:
    """Minimal detection shape compatible with FaceEngine.FaceDetection."""

    bbox: tuple[int, int, int, int]
    confidence: float = 0.0


@dataclass(frozen=True)
class PersonMatch:
    """Assignment of one ground-truth person to one detection."""

    identity: str
    detection_index: int
    confidence: float
    center_distance: float


@dataclass(frozen=True)
class MatchingResult:
    """Outcome of matching ground-truth people against frame detections."""

    matches: tuple[PersonMatch, ...]
    missed_persons: tuple[GroundTruthPerson, ...]
    spurious_detection_indices: tuple[int, ...]


def parse_sequence(xml_path: Path, image_dir: Path) -> ChokepointSequence:
    """Parse one ground-truth XML and resolve every annotated frame to a JPG."""
    match = PORTAL_SEQUENCE_PATTERN.fullmatch(xml_path.stem)
    if match is None:
        raise ValueError(f"unrecognized sequence name: {xml_path.name}")
    if not image_dir.is_dir():
        raise FileNotFoundError(f"image directory not found: {image_dir}")
    portal = match.group("portal")
    session = f"S{match.group('session')}"
    camera = f"C{match.group('camera')}"
    suffix = match.group("suffix")
    frames: dict[int, GroundTruthFrame] = {}
    for element in ET.parse(xml_path).getroot():
        if element.tag != "frame":
            continue
        number_text = element.get("number")
        if number_text is None:
            raise ValueError(f"frame element missing number attribute: {xml_path}")
        try:
            frame_number = int(number_text)
        except ValueError:
            raise ValueError(
                f"non-integer frame number {number_text!r} in {xml_path}"
            ) from None
        image_path = image_dir / f"{frame_number:08d}.jpg"
        if not image_path.is_file():
            raise FileNotFoundError(f"annotated frame has no JPG: {image_path}")
        persons = tuple(_parse_person(person) for person in element.findall("person"))
        frames[frame_number] = GroundTruthFrame(
            portal=portal,
            session=session,
            camera=camera,
            sequence_suffix=suffix,
            frame_number=frame_number,
            image_path=image_path,
            persons=persons,
        )
    if not frames:
        raise ValueError(f"no frames found in {xml_path}")
    return ChokepointSequence(
        portal=portal,
        session=session,
        camera=camera,
        sequence_suffix=suffix,
        xml_path=xml_path,
        image_dir=image_dir,
        frames=frames,
    )


def _parse_person(element: ET.Element) -> GroundTruthPerson:
    identity = element.get("id", "")
    left_eye = _parse_eye(element.find("leftEye"))
    right_eye = _parse_eye(element.find("rightEye"))
    return GroundTruthPerson(identity, left_eye, right_eye)


def _parse_eye(element: ET.Element | None) -> tuple[float, float] | None:
    if element is None:
        return None
    x = element.get("x")
    y = element.get("y")
    if x is None or y is None:
        return None
    return float(x), float(y)


def discover_sequences(chokepoint_dir: Path) -> list[ChokepointSequence]:
    """Discover all ground-truth XMLs under the dataset and parse each one."""
    sequences: list[ChokepointSequence] = []
    for xml_path in sorted(chokepoint_dir.glob("groundtruth/**/*.xml")):
        match = PORTAL_SEQUENCE_PATTERN.fullmatch(xml_path.stem)
        if match is None:
            continue
        suffix = match.group("suffix") or ""
        base = f"{match.group('portal')}_S{match.group('session')}_C{match.group('camera')}"
        image_dir = (
            chokepoint_dir
            / f"{match.group('portal')}_S{match.group('session')}"
            / base
            / f"{base}{suffix}"
        )
        sequences.append(parse_sequence(xml_path, image_dir))
    return sequences


def match_persons_to_detections(
    persons: Sequence[GroundTruthPerson],
    detections: Sequence[object],
) -> MatchingResult:
    """Assign ground-truth people to detections deterministically.

    A detection with ``bbox`` (and optional ``confidence``) qualifies for a
    person when the person's eye midpoint lies inside the bounding box.
    Every qualifying pair is ranked by bbox-center distance, then confidence
    (higher first), then detection index, and each detection is assigned to
    at most one person.
    """
    candidates: list[tuple[float, float, int, int]] = []
    for person_index, person in enumerate(persons):
        midpoint = person.eye_midpoint
        if midpoint is None:
            continue
        for detection_index, detection in enumerate(detections):
            bbox = detection.bbox
            x1, y1, x2, y2 = bbox
            if not (x1 <= midpoint[0] <= x2 and y1 <= midpoint[1] <= y2):
                continue
            center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            distance = ((center[0] - midpoint[0]) ** 2 + (center[1] - midpoint[1]) ** 2) ** 0.5
            candidates.append((distance, -float(detection.confidence), detection_index, person_index))
    candidates.sort()

    assigned_detections: set[int] = set()
    matches_by_person: dict[int, PersonMatch] = {}
    for distance, neg_confidence, detection_index, person_index in candidates:
        if detection_index in assigned_detections or person_index in matches_by_person:
            continue
        assigned_detections.add(detection_index)
        matches_by_person[person_index] = PersonMatch(
            identity=persons[person_index].identity,
            detection_index=detection_index,
            confidence=-neg_confidence,
            center_distance=distance,
        )

    matches = tuple(matches_by_person[index] for index in sorted(matches_by_person))
    missed = tuple(person for index, person in enumerate(persons) if index not in matches_by_person)
    spurious = tuple(index for index in range(len(detections)) if index not in assigned_detections)
    return MatchingResult(matches, missed, spurious)