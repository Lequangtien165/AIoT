"""Lightweight IoU tracking and identity confirmation for local streams."""

from __future__ import annotations

from dataclasses import dataclass


BBox = tuple[int, int, int, int]


def bbox_center(box: BBox) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def bbox_area(box: BBox) -> float:
    return float(max(0, box[2] - box[0]) * max(0, box[3] - box[1]))


def normalized_center_distance(first: BBox, second: BBox) -> float:
    first_center = bbox_center(first)
    second_center = bbox_center(second)
    distance = ((first_center[0] - second_center[0]) ** 2 + (first_center[1] - second_center[1]) ** 2) ** 0.5
    first_size = max(1.0, ((first[2] - first[0]) ** 2 + (first[3] - first[1]) ** 2) ** 0.5)
    second_size = max(1.0, ((second[2] - second[0]) ** 2 + (second[3] - second[1]) ** 2) ** 0.5)
    return distance / ((first_size + second_size) / 2.0)


def iou(first: BBox, second: BBox) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


@dataclass
class Track:
    track_id: int
    bbox: BBox
    last_seen_frame: int
    age_frames: int = 1
    missed_frames: int = 0
    last_recognition_frame: int = -1_000_000
    label: str | None = None
    score: float | None = None
    status: str = "pending"
    candidate_label: str | None = None
    candidate_count: int = 0


@dataclass(frozen=True)
class TrackEvent:
    kind: str
    track_id: int
    label: str | None
    previous_label: str | None
    score: float | None


class FaceTracker:
    """Assign IDs by IoU and cache labels by ID rather than bounding box coordinates."""

    def __init__(
        self,
        iou_threshold: float = 0.30,
        ttl_frames: int = 20,
        min_age_frames: int = 3,
        min_face_size: int = 80,
        recognition_interval_frames: int = 15,
        matched_recognition_interval_frames: int = 30,
        label_confirmations: int = 2,
        unknown_confirmations: int = 2,
        label_switch_margin: float = 0.05,
        center_distance_threshold: float = 0.70,
        size_ratio_threshold: float = 0.50,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.ttl_frames = ttl_frames
        self.min_age_frames = min_age_frames
        self.min_face_size = min_face_size
        self.recognition_interval_frames = recognition_interval_frames
        self.matched_recognition_interval_frames = matched_recognition_interval_frames
        self.label_confirmations = label_confirmations
        self.unknown_confirmations = unknown_confirmations
        self.label_switch_margin = label_switch_margin
        self.center_distance_threshold = center_distance_threshold
        self.size_ratio_threshold = size_ratio_threshold
        self.tracks: dict[int, Track] = {}
        self._next_track_id = 1

    def update(self, boxes: list[BBox], frame_number: int) -> list[Track]:
        candidates = sorted(
            (
                (self._match_score(track.bbox, box), track_id, box_index)
                for track_id, track in self.tracks.items()
                for box_index, box in enumerate(boxes)
            ),
            reverse=True,
        )
        matched_tracks: set[int] = set()
        matched_boxes: set[int] = set()
        for score, track_id, box_index in candidates:
            if score <= 0 or track_id in matched_tracks or box_index in matched_boxes:
                continue
            track = self.tracks[track_id]
            track.bbox = boxes[box_index]
            track.last_seen_frame = frame_number
            track.age_frames += 1
            track.missed_frames = 0
            matched_tracks.add(track_id)
            matched_boxes.add(box_index)

        expired_track_ids: list[int] = []
        for track_id, track in self.tracks.items():
            if track_id not in matched_tracks:
                track.missed_frames += 1
                if track.missed_frames > self.ttl_frames:
                    expired_track_ids.append(track_id)
        for track_id in expired_track_ids:
            del self.tracks[track_id]

        for box_index, box in enumerate(boxes):
            if box_index not in matched_boxes:
                track = Track(self._next_track_id, box, frame_number)
                self.tracks[track.track_id] = track
                self._next_track_id += 1

        return list(self.tracks.values())

    def select_for_recognition(self, frame_number: int, maximum: int = 1) -> list[Track]:
        eligible = [
            track
            for track in self.tracks.values()
            if track.missed_frames == 0
            and track.age_frames >= self.min_age_frames
            and min(track.bbox[2] - track.bbox[0], track.bbox[3] - track.bbox[1]) >= self.min_face_size
            and frame_number - track.last_recognition_frame >= self._recognition_interval(track)
        ]
        eligible.sort(
            key=lambda track: (
                self._recognition_priority(track),
                track.last_recognition_frame,
                track.track_id,
            )
        )
        selected = eligible[:maximum]
        for track in selected:
            track.last_recognition_frame = frame_number
        return selected

    def apply_recognition(
        self,
        track_id: int,
        label: str | None,
        score: float | None,
        threshold: float,
    ) -> TrackEvent | None:
        track = self.tracks.get(track_id)
        if track is None:
            return None
        matched_label = label if score is not None and score >= threshold else None
        self._record_candidate(track, matched_label)
        if track.candidate_count < self._required_confirmations(matched_label):
            return None
        if not self._label_switch_allowed(track, matched_label, score):
            return None

        previous_label = track.label
        previous_status = track.status
        track.label = matched_label
        track.score = score
        track.status = "matched" if matched_label else "unknown"
        return self._transition_event(track_id, matched_label, previous_label, previous_status, score)

    def _record_candidate(self, track: Track, label: str | None) -> None:
        if label != track.candidate_label:
            track.candidate_label = label
            track.candidate_count = 1
            return
        track.candidate_count += 1

    def _required_confirmations(self, label: str | None) -> int:
        if label:
            return self.label_confirmations
        return self.unknown_confirmations

    def _label_switch_allowed(self, track: Track, label: str | None, score: float | None) -> bool:
        if not label or not track.label or label == track.label:
            return True
        if score is None:
            return False
        return track.score is None or score >= track.score + self.label_switch_margin

    @staticmethod
    def _transition_event(
        track_id: int,
        label: str | None,
        previous_label: str | None,
        previous_status: str,
        score: float | None,
    ) -> TrackEvent | None:
        if previous_status != "matched" and label:
            return TrackEvent("identity_confirmed", track_id, label, previous_label, score)
        if previous_status == "matched" and not label:
            return TrackEvent("identity_lost", track_id, None, previous_label, score)
        if previous_status == "matched" and label != previous_label:
            return TrackEvent("identity_changed", track_id, label, previous_label, score)
        return None

    def _match_score(self, first: BBox, second: BBox) -> float:
        overlap = iou(first, second)
        if overlap >= self.iou_threshold:
            return 2.0 + overlap

        first_area = bbox_area(first)
        second_area = bbox_area(second)
        if first_area == 0 or second_area == 0:
            return 0.0
        area_ratio = min(first_area, second_area) / max(first_area, second_area)
        if area_ratio < self.size_ratio_threshold:
            return 0.0

        distance = normalized_center_distance(first, second)
        if distance > self.center_distance_threshold:
            return 0.0
        return 1.0 + (1.0 - distance)

    def _recognition_interval(self, track: Track) -> int:
        if track.status == "matched":
            return self.matched_recognition_interval_frames
        return self.recognition_interval_frames

    @staticmethod
    def _recognition_priority(track: Track) -> int:
        if track.status == "pending":
            return 0
        if track.status == "unknown":
            return 1
        return 2
