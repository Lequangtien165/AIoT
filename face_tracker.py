"""Lightweight IoU tracking and identity confirmation for local streams."""

from __future__ import annotations

from dataclasses import dataclass


BBox = tuple[int, int, int, int]


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
    """Gan ID theo IoU; cache nhan theo ID thay vi theo toa do bounding box."""

    def __init__(
        self,
        iou_threshold: float = 0.30,
        ttl_frames: int = 20,
        min_age_frames: int = 3,
        min_face_size: int = 80,
        recognition_interval_frames: int = 15,
        label_confirmations: int = 2,
        unknown_confirmations: int = 2,
        label_switch_margin: float = 0.05,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.ttl_frames = ttl_frames
        self.min_age_frames = min_age_frames
        self.min_face_size = min_face_size
        self.recognition_interval_frames = recognition_interval_frames
        self.label_confirmations = label_confirmations
        self.unknown_confirmations = unknown_confirmations
        self.label_switch_margin = label_switch_margin
        self.tracks: dict[int, Track] = {}
        self._next_track_id = 1

    def update(self, boxes: list[BBox], frame_number: int) -> list[Track]:
        candidates = sorted(
            (
                (iou(track.bbox, box), track_id, box_index)
                for track_id, track in self.tracks.items()
                for box_index, box in enumerate(boxes)
            ),
            reverse=True,
        )
        matched_tracks: set[int] = set()
        matched_boxes: set[int] = set()
        for overlap, track_id, box_index in candidates:
            if overlap < self.iou_threshold or track_id in matched_tracks or box_index in matched_boxes:
                continue
            track = self.tracks[track_id]
            track.bbox = boxes[box_index]
            track.last_seen_frame = frame_number
            track.age_frames += 1
            track.missed_frames = 0
            matched_tracks.add(track_id)
            matched_boxes.add(box_index)

        for track_id, track in list(self.tracks.items()):
            if track_id not in matched_tracks:
                track.missed_frames += 1
                if track.missed_frames > self.ttl_frames:
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
            and frame_number - track.last_recognition_frame >= self.recognition_interval_frames
        ]
        eligible.sort(
            key=lambda track: (
                track.status != "pending",
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
        required = self.label_confirmations if matched_label else self.unknown_confirmations

        if matched_label != track.candidate_label:
            track.candidate_label = matched_label
            track.candidate_count = 1
        else:
            track.candidate_count += 1
        if track.candidate_count < required:
            return None

        if matched_label and track.label and matched_label != track.label:
            if score is None or track.score is not None and score < track.score + self.label_switch_margin:
                return None

        previous_label = track.label
        previous_status = track.status
        track.label = matched_label
        track.score = score
        track.status = "matched" if matched_label else "unknown"

        if previous_status != "matched" and matched_label:
            return TrackEvent("identity_confirmed", track_id, matched_label, previous_label, score)
        if previous_status == "matched" and not matched_label:
            return TrackEvent("identity_lost", track_id, None, previous_label, score)
        if previous_status == "matched" and matched_label != previous_label:
            return TrackEvent("identity_changed", track_id, matched_label, previous_label, score)
        return None
