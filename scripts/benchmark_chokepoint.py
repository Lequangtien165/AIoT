"""ChokePoint end-to-end full-frame recognition benchmark.

Gallery embeddings are extracted once from the PGM face crops under
``chokepoint/<portal>/<portal>_S<d>_C<d>/<identity>/*.pgm`` and cached, then
one evaluation runs per gallery partition: each ``(portal, session)`` builds
its gallery from that partition's crops and probes the XML-listed full-frame
JPGs of the other seven partitions. Every probe frame is read with OpenCV,
passed through ``FaceEngine.detect_faces``, matched to the XML ground truth by
eye-midpoint containment, embedded with ``embed_detected_face``, and searched
in a FAISS ``IndexFlatIP`` index at the unchanged threshold (``--threshold``).

Raw probe inference (SCRFD detections + ArcFace embeddings) is a fixed,
partition-independent transform and may be persisted with ``--probe-cache``:
``build`` runs one inference pass over every unique frame, ``read`` evaluates
the 8 runs read-only and fails on any cache miss, and ``auto`` (default)
builds when missing or stale and reads otherwise. Matching, FAISS search,
thresholding, and recognition outcomes are always recomputed per run and are
never cached. P2E ``.1``/``.2`` sequences stay separate internally and are
aggregated per session-camera in the summaries. See
docs/plans/CHOKEPOINT_BENCHMARK.md for the design.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2
import faiss
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aiot.recognition.chokepoint_groundtruth import (
    ChokepointSequence,
    GroundTruthFrame,
    discover_sequences,
    match_persons_to_detections,
)
from aiot.recognition.face_engine import FaceEngine, FaceDetection
from aiot.recognition.probe_cache import (
    ProbeCacheNotFound,
    ProbeCacheStale,
    build_cache,
    build_fingerprint,
    load_cache as load_probe_cache,
)

PORTAL_SESSION_PATTERN = re.compile(r"^(?P<portal>[A-Z]+\d+[A-Z]+)_S(?P<session>\d+)_C(?P<camera>\d+)$")
SESSION_PATTERN = re.compile(r"^S(\d+)$")


@dataclass(frozen=True)
class Crop:
    path: Path
    portal: str
    session: str
    camera: str
    identity: str


@dataclass
class EmbeddingRecord:
    path: str
    portal: str
    session: str
    camera: str
    identity: str
    status: str = "pending"
    reason: str | None = None
    latency_ms: float | None = None
    vector: np.ndarray | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the ChokePoint cross-portal recognition benchmark."
    )
    parser.add_argument("--chokepoint-dir", type=Path, default=Path("chokepoint"))
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-output"))
    parser.add_argument("--threshold", type=float, default=0.45)
    parser.add_argument("--precheck", type=int, default=0, metavar="N")
    parser.add_argument("--limit", type=int, default=0, metavar="N")
    parser.add_argument("--run", type=str, default="", metavar="RUN-ID",
                        help="Evaluate only one partition, e.g. run-p1l-s1 (default: all).")
    parser.add_argument("--probe-cache", type=str, default="auto",
                        choices=["build", "read", "auto"],
                        help="build: one inference pass over all unique frames; "
                             "read: evaluate read-only, fail on any miss; "
                             "auto (default): build when missing or stale, else read.")
    parser.add_argument("--det-size", type=int, default=640,
                        help="SCRFD detection input size (fingerprinted into the probe cache).")
    parser.add_argument("--det-thresh", type=float, default=0.5,
                        help="SCRFD detection confidence threshold (fingerprinted into the probe cache).")
    parser.add_argument("--template-fill", type=float, default=0.9)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1.")
    if args.precheck < 0 or args.limit < 0:
        parser.error("--precheck and --limit must be >= 0.")
    if not 0 < args.template_fill <= 1:
        parser.error("--template-fill must be in (0, 1].")
    if args.det_size <= 0 or not 0 <= args.det_thresh <= 1:
        parser.error("--det-size must be > 0 and --det-thresh must be in [0, 1].")
    if args.run and args.probe_cache == "auto":
        parser.error("--run requires --probe-cache read (parallel workers must not build).")
    return args


def discover_crops(chokepoint_dir: Path) -> list[Crop]:
    crops: list[Crop] = []
    for session_dir in sorted(chokepoint_dir.glob("*/*")):
        match = PORTAL_SESSION_PATTERN.fullmatch(session_dir.name)
        if match is None or not session_dir.is_dir():
            continue
        portal = match.group("portal")
        if session_dir.parent.name != portal:
            continue
        session = f"S{match.group('session')}"
        camera = f"C{match.group('camera')}"
        for identity_dir in sorted(session_dir.iterdir()):
            if not identity_dir.is_dir():
                continue
            for image_path in sorted(identity_dir.glob("*.pgm")):
                crops.append(Crop(image_path, portal, session, camera, identity_dir.name))
    return crops


def embed_crop(engine: FaceEngine, path: Path, fill: float) -> tuple[np.ndarray | None, str | None]:
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None, "read_error"
    face = engine.embed_aligned_image(gray, fill=fill)
    if face is None:
        return None, "embed_error"
    return face.embedding, None


def embed_all(
    engine: FaceEngine,
    records: list[EmbeddingRecord],
    fill: float,
) -> None:
    for record in records:
        if record.status == "ok":
            continue
        started = time.monotonic()
        vector, reason = embed_crop(engine, Path(record.path), fill)
        record.latency_ms = (time.monotonic() - started) * 1000.0
        if vector is None:
            record.status = "skipped"
            record.reason = reason
        else:
            record.status = "ok"
            record.vector = vector


def save_cache(output_dir: Path, records: list[EmbeddingRecord]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    vectors = [record.vector for record in records if record.vector is not None]
    if vectors:
        np.save(output_dir / "embeddings.npy", np.vstack(vectors).astype("float32"))
    manifest = [
        {
            "path": record.path,
            "portal": record.portal,
            "session": record.session,
            "camera": record.camera,
            "identity": record.identity,
            "status": record.status,
            "reason": record.reason,
            "latency_ms": record.latency_ms,
        }
        for record in records
    ]
    with (output_dir / "embedding_manifest.json").open("w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)


def load_cache(output_dir: Path, crops: list[Crop]) -> tuple[list[EmbeddingRecord], bool]:
    vectors_path = output_dir / "embeddings.npy"
    manifest_path = output_dir / "embedding_manifest.json"
    if not vectors_path.exists() or not manifest_path.exists():
        return [], False
    with manifest_path.open(encoding="utf-8") as file:
        manifest = json.load(file)
    by_path = {crop.path.as_posix(): crop for crop in crops}
    vectors = np.load(vectors_path)
    vector_index = 0
    records: list[EmbeddingRecord] = []
    for entry in manifest:
        crop = by_path.get(entry["path"])
        if crop is None:
            continue
        record = EmbeddingRecord(
            path=entry["path"],
            portal=entry.get("portal") or Path(entry["path"]).parts[-4],
            session=crop.session,
            camera=crop.camera,
            identity=crop.identity,
            status=entry["status"],
            reason=entry.get("reason"),
            latency_ms=entry.get("latency_ms"),
        )
        if record.status == "ok":
            record.vector = vectors[vector_index]
            vector_index += 1
        records.append(record)
    return records, True


def collect_probes(
    sequences: Sequence[ChokepointSequence],
    gallery_portal: str,
    gallery_session: str,
    limit: int = 0,
) -> list[GroundTruthFrame]:
    """Return XML-listed frames of every partition except the gallery's."""
    frames: list[GroundTruthFrame] = []
    for sequence in sequences:
        if sequence.partition == (gallery_portal, gallery_session):
            continue
        frames.extend(sequence.frames[number] for number in sorted(sequence.frames))
    if limit > 0:
        frames = frames[:limit]
    return frames


def collect_precheck_frames(
    sequences: Sequence[ChokepointSequence], count: int
) -> list[GroundTruthFrame]:
    """Select a deterministic person/empty frame sample per portal."""
    person_frames: dict[str, list[GroundTruthFrame]] = {}
    empty_frames: dict[str, list[GroundTruthFrame]] = {}
    for sequence in sequences:
        for number in sorted(sequence.frames):
            frame = sequence.frames[number]
            bucket = person_frames if not frame.is_empty else empty_frames
            selected = bucket.setdefault(frame.portal, [])
            if len(selected) < count:
                selected.append(frame)
    frames: list[GroundTruthFrame] = []
    for portal in sorted(person_frames):
        frames.extend(person_frames[portal])
    for portal in sorted(empty_frames):
        frames.extend(empty_frames[portal])
    return frames


def run_precheck(
    frames: Sequence[GroundTruthFrame],
    engine: FaceEngine,
) -> int:
    """Read, detect, match, and embed a small deterministic probe sample."""
    print(f"precheck: {len(frames)} probe frames")
    person_stats: dict[str, dict[str, int]] = {}
    empty_stats: dict[str, dict[str, int]] = {}
    for frame in frames:
        image = cv2.imread(str(frame.image_path))
        detections = engine.detect_faces(image) if image is not None else []
        if frame.is_empty:
            stats = empty_stats.setdefault(
                frame.portal, {"frames": 0, "read_ok": 0, "with_detections": 0}
            )
            stats["frames"] += 1
            if image is not None:
                stats["read_ok"] += 1
                if detections:
                    stats["with_detections"] += 1
            print(
                f"  {frame.sequence_name} {frame.frame_number:08d} empty "
                f"read={'ok' if image is not None else 'fail'} "
                f"detections={len(detections)}"
            )
            continue
        stats = person_stats.setdefault(
            frame.portal,
            {"frames": 0, "read_ok": 0, "detected": 0, "faces": 0, "matched": 0, "embedded": 0},
        )
        stats["frames"] += 1
        if image is None:
            print(
                f"  {frame.sequence_name} {frame.frame_number:08d} person read=fail"
            )
            continue
        stats["read_ok"] += 1
        stats["faces"] += len(frame.persons)
        matching = match_persons_to_detections(frame.persons, detections)
        if detections:
            stats["detected"] += 1
        stats["matched"] += len(matching.matches)
        embedded = 0
        for match in matching.matches:
            detection = detections[match.detection_index]
            if engine.embed_detected_face(image, detection) is not None:
                embedded += 1
        stats["embedded"] += embedded
        print(
            f"  {frame.sequence_name} {frame.frame_number:08d} person "
            f"read=ok detections={len(detections)} "
            f"matched={len(matching.matches)} missed={len(matching.missed_persons)} "
            f"embedded={embedded}"
        )
    for portal in sorted(person_stats):
        stats = person_stats[portal]
        frames_total = stats["frames"]
        read_ok = stats["read_ok"]
        if read_ok:
            detected = f"{stats['detected']}/{read_ok}"
            matched = f"{stats['matched']}/{stats['faces']}"
            embedded = f"{stats['embedded']}/{stats['matched']}"
        else:
            detected = matched = embedded = "n/a"
        print(
            f"  {portal} person: {frames_total} frames, read {read_ok}/{frames_total} ok, "
            f"detected {detected} frames, matched {matched} faces, embedded {embedded}"
        )
    for portal in sorted(empty_stats):
        stats = empty_stats[portal]
        frames_total = stats["frames"]
        read_ok = stats["read_ok"]
        ratio = f"{stats['with_detections']}/{read_ok}" if read_ok else "n/a"
        print(
            f"  {portal} empty: {frames_total} frames, read {read_ok}/{frames_total} ok, "
            f"with detections {ratio}"
        )
    return 0


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return round(sorted(values)[max(0, int(len(values) * fraction) - 1)], 4)


def _ratio(numerator: int, denominator: int) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _closed_metrics(counts: dict[str, int]) -> tuple[float | None, float | None, float | None]:
    closed = counts["correct"] + counts["false_reject"] + counts["misidentified"]
    if closed == 0:
        return None, None, None
    return (
        counts["correct"] / closed,
        counts["false_reject"] / closed,
        counts["misidentified"] / closed,
    )


@dataclass
class FrameInference:
    """Detections and embeddings for one probe frame, live or cached."""

    read_ok: bool
    detections: list[FaceDetection]
    detection_latency_ms: float | None
    embeddings: list[np.ndarray | None]
    embedding_latency_ms: list[float | None]
    source: str  # "live" | "cached"
    entry_id: str | None


def _probe_cache_key(frame: GroundTruthFrame) -> str:
    return f"{frame.sequence_name}/{frame.frame_number:08d}"


def _frame_inference(
    frame: GroundTruthFrame,
    engine: FaceEngine,
    cache: object | None,
    cache_stats: dict,
) -> FrameInference:
    """Infer one frame live, or read its raw cached inference read-only."""
    if cache is None:
        image = cv2.imread(str(frame.image_path))
        if image is None:
            return FrameInference(False, [], None, [], [], "live", None)
        started = time.monotonic()
        detections = engine.detect_faces(image)
        detection_latency_ms = (time.monotonic() - started) * 1000.0
        embeddings: list[np.ndarray | None] = []
        embedding_latency_ms: list[float | None] = []
        for detection in detections:
            started = time.monotonic()
            face = engine.embed_detected_face(image, detection)
            embedding_latency_ms.append((time.monotonic() - started) * 1000.0)
            embeddings.append(face.embedding if face is not None else None)
        return FrameInference(
            True, detections, detection_latency_ms, embeddings, embedding_latency_ms, "live", None
        )

    key = _probe_cache_key(frame)
    started = time.monotonic()
    entry = cache.get(key)
    cache_stats["lookup_times"].append((time.monotonic() - started) * 1000.0)
    if entry is None:
        cache_stats["misses"] += 1
        raise RuntimeError(f"probe cache miss for {key}; read-only evaluation cannot fall back to live inference")
    cache_stats["hits"] += 1
    cache_stats["unique_keys"].add(key)
    if entry.status == "read_error":
        return FrameInference(False, [], None, [], [], "cached", entry.key)
    detections = [
        FaceDetection(
            bbox=detection.bbox,
            confidence=detection.confidence,
            landmarks=(
                np.asarray(detection.landmarks, dtype="float32")
                if detection.landmarks is not None
                else None
            ),
        )
        for detection in entry.detections
    ]
    embeddings = [
        cache.vectors[index].copy() if index is not None else None
        for index in entry.embedding_indices
    ]
    return FrameInference(
        True,
        detections,
        entry.detection_latency_ms,
        embeddings,
        list(entry.embedding_latency_ms),
        "cached",
        entry.key,
    )


def run_evaluation(
    run_id: str,
    gallery_portal: str,
    gallery_session: str,
    records: list[EmbeddingRecord],
    probe_frames: Sequence[GroundTruthFrame],
    engine: FaceEngine,
    threshold: float,
    cache: object | None = None,
    cache_stats: dict | None = None,
) -> tuple[list[dict], dict, dict]:
    """Probe live full-frame JPGs against one gallery partition.

    Recognition counts keep their documented meaning: a GT identity present in
    the gallery that cannot be read, detected, or embedded counts as
    ``false_reject``; a successful search is ``correct``, ``false_reject``, or
    ``misidentified``; an identity absent from the gallery stays
    ``not_enrolled`` and only an above-threshold match increments
    ``false_accept``. Empty frames never touch recognition counts and affect
    only the additive detection metrics.
    """
    gallery = [
        r
        for r in records
        if r.status == "ok" and r.portal == gallery_portal and r.session == gallery_session
    ]
    gallery_identities = {r.identity for r in gallery}
    matrix = np.vstack([r.vector for r in gallery]).astype("float32")
    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)

    predictions: list[dict] = []
    search_times: list[float] = []
    detection_times: list[float] = []
    embedding_times: list[float] = []
    counts: dict[str, int] = {
        "correct": 0,
        "false_reject": 0,
        "misidentified": 0,
        "not_enrolled": 0,
        "false_accept": 0,
        "probe_images": 0,
        "closed_set": 0,
    }
    detection_counts: dict[str, int] = {
        "gt_face_frames": 0,
        "gt_faces": 0,
        "matched_faces": 0,
        "missed_faces": 0,
        "total_detections": 0,
        "spurious_detections": 0,
        "empty_frames": 0,
        "empty_frames_with_detections": 0,
    }
    per_partition: dict[str, dict] = {}

    def update_counts(target: dict[str, int], outcome: str, score: float | None) -> None:
        target["probe_images"] += 1
        if outcome == "not_enrolled":
            target["not_enrolled"] += 1
            if score is not None and score >= threshold:
                target["false_accept"] += 1
        else:
            target["closed_set"] += 1
            target[outcome] += 1

    def partition_entry(frame: GroundTruthFrame) -> dict:
        key = f"{frame.portal}-{frame.session}-{frame.camera}"
        scope = "same_portal_cross_session" if frame.portal == gallery_portal else "cross_portal"
        return per_partition.setdefault(
            key,
            {
                "probe_portal": frame.portal,
                "probe_session": frame.session,
                "camera": frame.camera,
                "scope": scope,
                "counts": {k: 0 for k in counts},
                "detection": {k: 0 for k in detection_counts},
            },
        )

    def record_prediction(
        frame: GroundTruthFrame,
        identity: str,
        outcome: str,
        score: float | None,
        predicted: str,
        detection_status: str,
        confidence: float | None,
        bbox: tuple[int, int, int, int] | None,
        detection_latency_ms: float | None,
        embedding_status: str,
        embedding_latency_ms: float | None,
        inference_source: str = "live",
        cache_entry_id: str | None = None,
    ) -> None:
        scope = "same_portal_cross_session" if frame.portal == gallery_portal else "cross_portal"
        entry = partition_entry(frame)
        rounded_score = round(score, 4) if score is not None else None
        update_counts(counts, outcome, rounded_score)
        update_counts(entry["counts"], outcome, rounded_score)
        predictions.append(
            {
                "run_id": run_id,
                "gallery_portal": gallery_portal,
                "gallery_session": gallery_session,
                "probe_portal": frame.portal,
                "probe_session": frame.session,
                "camera": frame.camera,
                "sequence": frame.sequence_name,
                "identity": identity,
                "image_path": str(frame.image_path),
                "predicted_identity": predicted,
                "score": rounded_score,
                "outcome": outcome,
                "scope": scope,
                "inference_source": inference_source,
                "cache_entry_id": cache_entry_id,
                "probe_cache_id": cache.probe_cache_id if cache is not None else "",
                "detection_status": detection_status,
                "detection_confidence": round(confidence, 4) if confidence is not None else None,
                "detection_bbox": ",".join(str(value) for value in bbox) if bbox is not None else None,
                "detection_latency_ms": round(detection_latency_ms, 4) if detection_latency_ms is not None else None,
                "embedding_status": embedding_status,
                "embedding_latency_ms": round(embedding_latency_ms, 4) if embedding_latency_ms is not None else None,
            }
        )

    started = time.monotonic()
    for frame_index, frame in enumerate(probe_frames, start=1):
        if frame_index % 5000 == 0:
            print(
                f"  {run_id}: {frame_index}/{len(probe_frames)} frames "
                f"({time.monotonic() - started:.0f}s)"
            )
        entry = partition_entry(frame)
        entry_detection = entry["detection"]
        inference = _frame_inference(frame, engine, cache, cache_stats)
        if frame.is_empty:
            detection_counts["empty_frames"] += 1
            entry_detection["empty_frames"] += 1
            if not inference.read_ok:
                continue
            detection_times.append(inference.detection_latency_ms)
            if inference.detections:
                detection_counts["empty_frames_with_detections"] += 1
                entry_detection["empty_frames_with_detections"] += 1
                detection_counts["total_detections"] += len(inference.detections)
                detection_counts["spurious_detections"] += len(inference.detections)
                entry_detection["total_detections"] += len(inference.detections)
                entry_detection["spurious_detections"] += len(inference.detections)
            continue

        detection_counts["gt_face_frames"] += 1
        entry_detection["gt_face_frames"] += 1
        detection_counts["gt_faces"] += len(frame.persons)
        entry_detection["gt_faces"] += len(frame.persons)

        if not inference.read_ok:
            detection_counts["missed_faces"] += len(frame.persons)
            entry_detection["missed_faces"] += len(frame.persons)
            for person in frame.persons:
                outcome = "not_enrolled" if person.identity not in gallery_identities else "false_reject"
                record_prediction(frame, person.identity, outcome, None, "", "read_error", None, None, None, "not_applicable", None, inference.source, inference.entry_id)
            continue

        detections = inference.detections
        detection_latency_ms = inference.detection_latency_ms
        detection_times.append(detection_latency_ms)
        matching = match_persons_to_detections(frame.persons, detections)
        detection_counts["total_detections"] += len(detections)
        entry_detection["total_detections"] += len(detections)
        detection_counts["matched_faces"] += len(matching.matches)
        entry_detection["matched_faces"] += len(matching.matches)
        detection_counts["missed_faces"] += len(matching.missed_persons)
        entry_detection["missed_faces"] += len(matching.missed_persons)
        detection_counts["spurious_detections"] += len(matching.spurious_detection_indices)
        entry_detection["spurious_detections"] += len(matching.spurious_detection_indices)

        for match in matching.matches:
            detection = detections[match.detection_index]
            embedding_latency_ms = inference.embedding_latency_ms[match.detection_index]
            embedding_times.append(embedding_latency_ms)
            face = inference.embeddings[match.detection_index]
            if face is None:
                outcome = "not_enrolled" if match.identity not in gallery_identities else "false_reject"
                record_prediction(frame, match.identity, outcome, None, "", "matched", detection.confidence, detection.bbox, detection_latency_ms, "embed_error", embedding_latency_ms, inference.source, inference.entry_id)
                continue
            query = np.ascontiguousarray(face.reshape(1, -1), dtype="float32")
            started = time.monotonic()
            similarities, indices = index.search(query, 1)
            search_times.append((time.monotonic() - started) * 1000.0)
            predicted = gallery[indices[0][0]].identity if indices[0][0] >= 0 else ""
            score = float(similarities[0][0])
            if match.identity not in gallery_identities:
                outcome = "not_enrolled"
            elif score >= threshold and predicted == match.identity:
                outcome = "correct"
            elif score >= threshold:
                outcome = "misidentified"
            else:
                outcome = "false_reject"
            record_prediction(frame, match.identity, outcome, score, predicted, "matched", detection.confidence, detection.bbox, detection_latency_ms, "ok", embedding_latency_ms, inference.source, inference.entry_id)

        for person in matching.missed_persons:
            outcome = "not_enrolled" if person.identity not in gallery_identities else "false_reject"
            record_prediction(frame, person.identity, outcome, None, "", "missed", None, None, detection_latency_ms, "not_applicable", None, inference.source, inference.entry_id)

    same_counts = {key: 0 for key in counts}
    cross_counts = {key: 0 for key in counts}
    for prediction in predictions:
        target = same_counts if prediction["scope"] == "same_portal_cross_session" else cross_counts
        update_counts(target, prediction["outcome"], prediction["score"])

    accuracy, frr, misid = _closed_metrics(counts)
    same_accuracy, _, _ = _closed_metrics(same_counts)
    cross_accuracy, _, _ = _closed_metrics(cross_counts)
    matched_faces = detection_counts["matched_faces"]
    missed_faces = detection_counts["missed_faces"]
    run_summary = {
        "run_id": run_id,
        "gallery_portal": gallery_portal,
        "gallery_session": gallery_session,
        "gallery_vectors": len(gallery),
        "probe_images": counts["probe_images"],
        "closed_set": counts["closed_set"],
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "false_reject_rate": round(frr, 4) if frr is not None else None,
        "misidentification_rate": round(misid, 4) if misid is not None else None,
        "same_portal_accuracy": round(same_accuracy, 4) if same_accuracy is not None else None,
        "cross_portal_accuracy": round(cross_accuracy, 4) if cross_accuracy is not None else None,
        "same_correct": same_counts["correct"],
        "same_closed_set": same_counts["closed_set"],
        "cross_correct": cross_counts["correct"],
        "cross_closed_set": cross_counts["closed_set"],
        "not_enrolled": counts["not_enrolled"],
        "false_accept_rate": round(counts["false_accept"] / counts["not_enrolled"], 4) if counts["not_enrolled"] else None,
        "search_p50_ms": percentile(search_times, 0.5),
        "search_p95_ms": percentile(search_times, 0.95),
        "gt_face_frames": detection_counts["gt_face_frames"],
        "gt_faces": detection_counts["gt_faces"],
        "matched_faces": matched_faces,
        "missed_faces": missed_faces,
        "total_detections": detection_counts["total_detections"],
        "spurious_detections": detection_counts["spurious_detections"],
        "empty_frames": detection_counts["empty_frames"],
        "empty_frames_with_detections": detection_counts["empty_frames_with_detections"],
        "detection_recall": _ratio(matched_faces, matched_faces + missed_faces),
        "detection_precision": _ratio(matched_faces, detection_counts["total_detections"]),
        "empty_frame_fpr": _ratio(detection_counts["empty_frames_with_detections"], detection_counts["empty_frames"]),
        "detection_p50_ms": percentile(detection_times, 0.5),
        "detection_p95_ms": percentile(detection_times, 0.95),
        "probe_embedding_p50_ms": percentile(embedding_times, 0.5),
        "probe_embedding_p95_ms": percentile(embedding_times, 0.95),
    }
    return predictions, run_summary, per_partition


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as file:
        import csv

        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def mean_or_none(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


def _overall_summary(
    run_rows: list[dict], records: list[EmbeddingRecord], cache_stats: dict | None = None
) -> dict:
    closed_accuracy = [row["accuracy"] for row in run_rows if row["accuracy"] is not None]
    same_accuracy = [row["same_portal_accuracy"] for row in run_rows if row["same_portal_accuracy"] is not None]
    cross_accuracy = [row["cross_portal_accuracy"] for row in run_rows if row["cross_portal_accuracy"] is not None]
    total_closed = sum(row["closed_set"] for row in run_rows)
    total_correct = sum(round(row["accuracy"], 10) * row["closed_set"] for row in run_rows if row["accuracy"] is not None)
    same_closed = sum(row["same_closed_set"] for row in run_rows)
    same_correct = sum(row["same_correct"] for row in run_rows)
    cross_closed = sum(row["cross_closed_set"] for row in run_rows)
    cross_correct = sum(row["cross_correct"] for row in run_rows)
    embedding_latencies = [r.latency_ms for r in records if r.latency_ms is not None]
    ok_embedding = sum(1 for r in records if r.status == "ok")
    total_matched = sum(row["matched_faces"] for row in run_rows)
    total_missed = sum(row["missed_faces"] for row in run_rows)
    total_detections = sum(row["total_detections"] for row in run_rows)
    total_empty = sum(row["empty_frames"] for row in run_rows)
    total_empty_with_detections = sum(row["empty_frames_with_detections"] for row in run_rows)
    summary = {
        "total_crops": len(records),
        "embedded_ok": ok_embedding,
        "embedded_skipped": len(records) - ok_embedding,
        "total_probe_queries": sum(row["probe_images"] for row in run_rows),
        "total_closed_set": total_closed,
        "total_not_enrolled": sum(row["not_enrolled"] for row in run_rows),
        "total_false_accept": sum(
            round(row["false_accept_rate"], 10) * row["not_enrolled"]
            for row in run_rows
            if row["false_accept_rate"] is not None
        ),
        "micro_accuracy": round(total_correct / total_closed, 4) if total_closed else None,
        "macro_accuracy": mean_or_none(closed_accuracy),
        "micro_same_portal_accuracy": round(same_correct / same_closed, 4) if same_closed else None,
        "macro_same_portal_accuracy": mean_or_none(same_accuracy),
        "micro_cross_portal_accuracy": round(cross_correct / cross_closed, 4) if cross_closed else None,
        "macro_cross_portal_accuracy": mean_or_none(cross_accuracy),
        "embedding_p50_ms": percentile(embedding_latencies, 0.5),
        "embedding_p95_ms": percentile(embedding_latencies, 0.95),
        "total_gt_face_frames": sum(row["gt_face_frames"] for row in run_rows),
        "total_gt_faces": sum(row["gt_faces"] for row in run_rows),
        "total_matched_faces": total_matched,
        "total_missed_faces": total_missed,
        "total_detections": total_detections,
        "total_spurious_detections": sum(row["spurious_detections"] for row in run_rows),
        "total_empty_frames": total_empty,
        "total_empty_frames_with_detections": total_empty_with_detections,
        "detection_recall": _ratio(total_matched, total_matched + total_missed),
        "detection_precision": _ratio(total_matched, total_detections),
        "empty_frame_fpr": _ratio(total_empty_with_detections, total_empty),
    }
    if cache_stats is not None:
        hits = cache_stats["hits"]
        misses = cache_stats["misses"]
        lookup_times = cache_stats["lookup_times"]
        unique = len(cache_stats["unique_keys"])
        summary.update(
            {
                "probe_cache_mode": cache_stats["mode"],
                "probe_cache_id": cache_stats["probe_cache_id"],
                "probe_cache_build_seconds": cache_stats["build_seconds"],
                "probe_cache_hits": hits,
                "probe_cache_misses": misses,
                "probe_cache_stale": cache_stats["stale"],
                "probe_cache_hit_rate": round(hits / (hits + misses), 4) if hits + misses else None,
                "unique_probe_frames": unique,
                "logical_probe_frames": hits,
                "cache_reuse_factor": round(hits / unique, 4) if unique else None,
                "cache_lookup_p50_ms": percentile(lookup_times, 0.5),
                "cache_lookup_p95_ms": percentile(lookup_times, 0.95),
            }
        )
    return summary


def main() -> int:
    args = parse_args()
    crops = discover_crops(args.chokepoint_dir)
    if not crops:
        raise SystemExit("No PGM crops were found under the ChokePoint portal directories.")
    sequences = discover_sequences(args.chokepoint_dir)
    if not sequences:
        raise SystemExit(
            "No ground-truth XML files were found under the ChokePoint groundtruth directories."
        )

    if args.precheck > 0:
        engine = FaceEngine(det_size=args.det_size, det_thresh=args.det_thresh)
        frames = collect_precheck_frames(sequences, args.precheck)
        return run_precheck(frames, engine)

    partitions: list[tuple[str, str]] = []
    for portal in sorted({crop.portal for crop in crops}):
        for session in sorted(
            {crop.session for crop in crops if crop.portal == portal},
            key=lambda s: int(SESSION_PATTERN.fullmatch(s).group(1)),
        ):
            partitions.append((portal, session))

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.no_cache:
        records: list[EmbeddingRecord] = []
    else:
        records, cache_existed = load_cache(output_dir, crops)
        if not cache_existed:
            records = []
    known = {record.path for record in records}
    missing = [crop for crop in crops if crop.path.as_posix() not in known]
    engine = FaceEngine(det_size=args.det_size, det_thresh=args.det_thresh)
    if missing:
        records = records + [
            EmbeddingRecord(
                path=str(crop.path),
                portal=crop.portal,
                session=crop.session,
                camera=crop.camera,
                identity=crop.identity,
            )
            for crop in missing
        ]
        if not args.no_cache and known:
            print(f"cache: {len(records) - len(missing)} cached, {len(missing)} new crops to embed")
        started = time.monotonic()
        embed_all(engine, records, args.template_fill)
        embed_seconds = time.monotonic() - started
        ok_count = sum(1 for r in records if r.status == "ok")
        if embed_seconds:
            print(f"embedding: {ok_count}/{len(records)} ok in {embed_seconds:.1f}s ({ok_count / embed_seconds:.1f} embeddings/s)")
        save_cache(output_dir, records)
    else:
        print(f"cache: all {len(records)} crops loaded from cache")

    probe_cache = None
    cache_stats: dict = {
        "hits": 0,
        "misses": 0,
        "stale": 0,
        "lookup_times": [],
        "unique_keys": set(),
        "mode": args.probe_cache,
        "probe_cache_id": "",
        "build_seconds": 0.0,
    }
    fingerprint = build_fingerprint(engine, args.det_size, args.det_thresh, args.template_fill)
    probe_cache_dir = output_dir / "probe_cache"
    try:
        probe_cache = load_probe_cache(probe_cache_dir, fingerprint)
        print(
            f"probe cache: read {len(probe_cache)} entries, "
            f"id={probe_cache.probe_cache_id}, build={probe_cache.build_seconds:.0f}s"
        )
    except ProbeCacheNotFound as error:
        if args.probe_cache == "read":
            raise SystemExit(f"{error}; run with --probe-cache build first.") from None
        print(f"probe cache: not found, building ({error})")
        probe_cache = build_cache(probe_cache_dir, sequences, engine, fingerprint)
    except ProbeCacheStale as error:
        cache_stats["stale"] = 1
        if args.probe_cache == "read":
            raise SystemExit(f"{error}; rebuild with --probe-cache build.") from None
        print(f"probe cache: stale, rebuilding ({error})")
        probe_cache = build_cache(probe_cache_dir, sequences, engine, fingerprint)
    cache_stats["probe_cache_id"] = probe_cache.probe_cache_id
    cache_stats["build_seconds"] = probe_cache.build_seconds
    if args.probe_cache == "build":
        print(f"probe cache: built {len(probe_cache)} entries in {probe_cache.build_seconds:.0f}s")

    if args.limit > 0:
        print(f"limit: probing at most {args.limit} frames per run")

    all_predictions: list[dict] = []
    run_rows: list[dict] = []
    camera_rows: list[dict] = []
    for gallery_portal, gallery_session in partitions:
        run_id = f"run-{gallery_portal.lower()}-s{gallery_session[1:]}"
        if args.run and run_id != args.run:
            continue
        probe_frames = collect_probes(sequences, gallery_portal, gallery_session, args.limit)
        hits_before = cache_stats["hits"]
        misses_before = cache_stats["misses"]
        lookups_before = len(cache_stats["lookup_times"])
        started = time.monotonic()
        predictions, run_summary, per_partition = run_evaluation(
            run_id, gallery_portal, gallery_session, records, probe_frames, engine, args.threshold,
            cache=probe_cache, cache_stats=cache_stats,
        )
        run_summary["wall_seconds"] = round(time.monotonic() - started, 2)
        if probe_cache is not None:
            run_summary["probe_cache_hits"] = cache_stats["hits"] - hits_before
            run_summary["probe_cache_misses"] = cache_stats["misses"] - misses_before
            run_lookup_times = cache_stats["lookup_times"][lookups_before:]
            run_summary["cache_lookup_p50_ms"] = percentile(run_lookup_times, 0.5)
            run_summary["cache_lookup_p95_ms"] = percentile(run_lookup_times, 0.95)
        all_predictions.extend(predictions)
        run_rows.append(run_summary)
        for key, entry in sorted(per_partition.items()):
            camera_rows.append(
                {
                    "run_id": run_id,
                    "gallery_portal": gallery_portal,
                    "gallery_session": gallery_session,
                    "probe_portal": entry["probe_portal"],
                    "probe_session": entry["probe_session"],
                    "camera": entry["camera"],
                    "scope": entry["scope"],
                    **entry["counts"],
                    **entry["detection"],
                }
            )
        print(
            f"{run_id}: gallery={run_summary['gallery_vectors']} vectors, "
            f"probes={run_summary['probe_images']}, "
            f"accuracy={run_summary['accuracy']}, "
            f"same={run_summary['same_portal_accuracy']}, "
            f"cross={run_summary['cross_portal_accuracy']}, "
            f"det_recall={run_summary['detection_recall']}"
        )

    if args.run and not run_rows:
        raise SystemExit(f"No partition matched --run {args.run}.")

    overall = _overall_summary(run_rows, records, cache_stats if probe_cache is not None else None)

    write_csv(output_dir / "embedding_manifest.csv", [
        {"path": r.path, "portal": r.portal, "session": r.session, "camera": r.camera, "identity": r.identity, "status": r.status, "reason": r.reason, "latency_ms": r.latency_ms}
        for r in records
    ])
    write_csv(output_dir / "predictions.csv", all_predictions)
    write_csv(output_dir / "run_summary.csv", run_rows)
    write_csv(output_dir / "session_camera_summary.csv", camera_rows)
    write_csv(output_dir / "overall_summary.csv", [overall])

    print(
        f"overall: micro={overall['micro_accuracy']} macro={overall['macro_accuracy']} "
        f"same={overall['micro_same_portal_accuracy']} cross={overall['micro_cross_portal_accuracy']}"
    )
    print(f"outputs written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())