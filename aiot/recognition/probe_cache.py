"""Persistent cache of raw SCRFD/ArcFace inference for full-frame probes.

Caching is valid because detection and embedding are a fixed,
partition-independent transform: ``JPG -> SCRFD raw detections -> ArcFace
embeddings``. None of it depends on the gallery partition, the FAISS index,
gallery identities, or the 0.45 threshold. Matching, FAISS search,
thresholding, and recognition outcomes are never cached and are always
recomputed per run (see docs/plans/CHOKEPOINT_BENCHMARK.md).

The cache is keyed by a fingerprint of the models, ONNX Runtime providers,
detection/alignment configuration, and library versions so stale entries are
never silently reused; read-only evaluation must reach 100% cache hits.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2
import insightface
import numpy as np
import onnxruntime as ort

from aiot.recognition.chokepoint_groundtruth import ChokepointSequence
from aiot.recognition.face_engine import FaceEngine

CACHE_SCHEMA_VERSION = 1

MANIFEST_NAME = "probe_cache_manifest.json"
EMBEDDINGS_NAME = "probe_cache_embeddings.npy"
FINGERPRINT_NAME = "probe_cache_fingerprint.json"

PROGRESS_EVERY = 5000


class ProbeCacheError(RuntimeError):
    """Base error for probe cache problems."""


class ProbeCacheNotFound(ProbeCacheError):
    """No usable probe cache exists in the directory."""


class ProbeCacheStale(ProbeCacheError):
    """The probe cache fingerprint does not match the current configuration."""


@dataclass(frozen=True)
class CachedDetection:
    """One raw SCRFD detection with its ArcFace input landmarks."""

    bbox: tuple[int, int, int, int]
    confidence: float
    landmarks: list[list[float]] | None


@dataclass(frozen=True)
class ProbeCacheEntry:
    """Raw model inference for one unique full-frame JPG."""

    key: str
    path: str
    size: int
    mtime: float
    status: str  # "ok" | "read_error"
    detection_latency_ms: float | None
    detections: tuple[CachedDetection, ...]
    embedding_indices: tuple[int | None, ...]
    embedding_latency_ms: tuple[float | None, ...]


@dataclass(frozen=True)
class LoadedCache:
    """A cache loaded for read-only evaluation."""

    cache_dir: Path
    fingerprint: dict
    probe_cache_id: str
    build_seconds: float
    vectors: np.ndarray
    entries: dict[str, ProbeCacheEntry]

    def get(self, key: str) -> ProbeCacheEntry | None:
        """Return the entry for ``key`` or None on a miss."""
        return self.entries.get(key)

    def __len__(self) -> int:
        return len(self.entries)


def frame_key(sequence: ChokepointSequence, number: int) -> str:
    """Stable unique key for one frame across sequences and P2E suffixes."""
    return f"{sequence.name}/{number:08d}"


def _frame_fingerprint(image_path: Path) -> tuple[int, float]:
    stat = image_path.stat()
    return stat.st_size, stat.st_mtime


def build_fingerprint(
    engine: FaceEngine,
    det_size: int,
    det_thresh: float,
    template_fill: float,
) -> dict:
    """Fingerprint every property that invalidates cached probe inference."""
    models_dir = Path.home() / ".insightface" / "models" / "buffalo_l"
    model_hashes: dict[str, str] = {}
    if models_dir.is_dir():
        for path in sorted(models_dir.glob("*.onnx")):
            digest = hashlib.sha256()
            with path.open("rb") as file:
                for chunk in iter(lambda: file.read(1 << 20), b""):
                    digest.update(chunk)
            model_hashes[path.name] = digest.hexdigest()
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "det_size": det_size,
        "det_thresh": det_thresh,
        "template_fill": template_fill,
        "requested_providers": list(engine.requested_providers),
        "detector_providers": list(engine.detector_providers),
        "recognition_providers": list(engine.recognition_providers),
        "model_hashes": model_hashes,
        "insightface_version": insightface.__version__,
        "onnxruntime_version": ort.__version__,
        "opencv_version": cv2.__version__,
    }


def fingerprint_id(fingerprint: dict) -> str:
    """Short content hash identifying one cache configuration."""
    canonical = json.dumps(fingerprint, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _read_error_entry(key: str, image_path: Path, size: int, mtime: float) -> ProbeCacheEntry:
    return ProbeCacheEntry(
        key=key,
        path=str(image_path),
        size=size,
        mtime=mtime,
        status="read_error",
        detection_latency_ms=None,
        detections=(),
        embedding_indices=(),
        embedding_latency_ms=(),
    )


def _embed_detections(
    image: np.ndarray,
    detections: list,
    engine: FaceEngine,
    vectors: list[np.ndarray],
) -> tuple[list[CachedDetection], list[int | None], list[float | None]]:
    """Embed every detection, appending new vectors and tracking indices."""
    cached_detections: list[CachedDetection] = []
    embedding_indices: list[int | None] = []
    embedding_latencies: list[float | None] = []
    for detection in detections:
        cached_detections.append(
            CachedDetection(
                bbox=detection.bbox,
                confidence=detection.confidence,
                landmarks=(
                    detection.landmarks.tolist()
                    if detection.landmarks is not None
                    else None
                ),
            )
        )
        embed_started = time.monotonic()
        face = engine.embed_detected_face(image, detection)
        embedding_latencies.append((time.monotonic() - embed_started) * 1000.0)
        if face is None:
            embedding_indices.append(None)
        else:
            embedding_indices.append(len(vectors))
            vectors.append(face.embedding)
    return cached_detections, embedding_indices, embedding_latencies


def _infer_frame(
    sequence: ChokepointSequence,
    number: int,
    engine: FaceEngine,
    vectors: list[np.ndarray],
) -> ProbeCacheEntry:
    """Detect and embed one frame, returning its raw cached inference."""
    frame = sequence.frames[number]
    key = frame_key(sequence, number)
    size, mtime = _frame_fingerprint(frame.image_path)
    image = cv2.imread(str(frame.image_path))
    if image is None:
        return _read_error_entry(key, frame.image_path, size, mtime)
    detect_started = time.monotonic()
    detections = engine.detect_faces(image)
    detection_latency_ms = (time.monotonic() - detect_started) * 1000.0
    cached_detections, embedding_indices, embedding_latencies = _embed_detections(
        image, detections, engine, vectors
    )
    return ProbeCacheEntry(
        key=key,
        path=str(frame.image_path),
        size=size,
        mtime=mtime,
        status="ok",
        detection_latency_ms=detection_latency_ms,
        detections=tuple(cached_detections),
        embedding_indices=tuple(embedding_indices),
        embedding_latency_ms=tuple(embedding_latencies),
    )


def _progress_report(processed: int, total: int, started: float) -> None:
    if processed % PROGRESS_EVERY != 0:
        return
    elapsed = time.monotonic() - started
    print(
        f"  probe cache: {processed}/{total} frames "
        f"({elapsed:.0f}s, {processed / elapsed:.0f} frames/s)"
    )


def _manifest_rows(entries: dict[str, ProbeCacheEntry]) -> list[dict]:
    return [
        {
            "key": entry.key,
            "path": entry.path,
            "size": entry.size,
            "mtime": entry.mtime,
            "status": entry.status,
            "detection_latency_ms": entry.detection_latency_ms,
            "detections": [
                {
                    "bbox": list(detection.bbox),
                    "confidence": detection.confidence,
                    "landmarks": detection.landmarks,
                }
                for detection in entry.detections
            ],
            "embedding_indices": list(entry.embedding_indices),
            "embedding_latency_ms": list(entry.embedding_latency_ms),
        }
        for entry in entries.values()
    ]


def _write_vectors(cache_dir: Path, vectors: list[np.ndarray]) -> None:
    if vectors:
        np.save(cache_dir / EMBEDDINGS_NAME, np.vstack(vectors).astype("float32"))


def _write_fingerprint(cache_dir: Path, fingerprint: dict, build_seconds: float) -> dict:
    stored_fingerprint = dict(fingerprint)
    stored_fingerprint["probe_cache_id"] = fingerprint_id(fingerprint)
    stored_fingerprint["build_seconds"] = build_seconds
    stored_fingerprint["built_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (cache_dir / FINGERPRINT_NAME).write_text(
        json.dumps(stored_fingerprint, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return stored_fingerprint


def build_cache(
    cache_dir: Path,
    sequences: Sequence[ChokepointSequence],
    engine: FaceEngine,
    fingerprint: dict,
) -> LoadedCache:
    """Run one inference pass over every unique frame and persist the result."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    total = sum(len(sequence.frames) for sequence in sequences)
    entries: dict[str, ProbeCacheEntry] = {}
    vectors: list[np.ndarray] = []
    started = time.monotonic()
    processed = 0
    for sequence in sequences:
        for number in sorted(sequence.frames):
            processed += 1
            _progress_report(processed, total, started)
            entries[frame_key(sequence, number)] = _infer_frame(sequence, number, engine, vectors)
    build_seconds = round(time.monotonic() - started, 2)
    _write_vectors(cache_dir, vectors)
    (cache_dir / MANIFEST_NAME).write_text(
        json.dumps(_manifest_rows(entries), ensure_ascii=False), encoding="utf-8"
    )
    stored_fingerprint = _write_fingerprint(cache_dir, fingerprint, build_seconds)
    vectors_array = np.vstack(vectors).astype("float32") if vectors else np.zeros((0, 512), dtype="float32")
    return LoadedCache(
        cache_dir=cache_dir,
        fingerprint=stored_fingerprint,
        probe_cache_id=fingerprint_id(fingerprint),
        build_seconds=build_seconds,
        vectors=vectors_array,
        entries=entries,
    )


def load_cache(
    cache_dir: Path,
    expected_fingerprint: dict | None = None,
) -> LoadedCache:
    """Load a previously built cache, failing on absence or staleness."""
    manifest_path = cache_dir / MANIFEST_NAME
    vectors_path = cache_dir / EMBEDDINGS_NAME
    fingerprint_path = cache_dir / FINGERPRINT_NAME
    if not (manifest_path.exists() and fingerprint_path.exists()):
        raise ProbeCacheNotFound(f"no probe cache found in {cache_dir}")
    stored = json.loads(fingerprint_path.read_text(encoding="utf-8"))
    stored_id = stored.get("probe_cache_id") or fingerprint_id(stored)
    if expected_fingerprint is not None and stored_id != fingerprint_id(expected_fingerprint):
        raise ProbeCacheStale(
            f"probe cache fingerprint mismatch in {cache_dir}: "
            f"cache {stored_id} != expected {fingerprint_id(expected_fingerprint)}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if vectors_path.exists():
        vectors = np.load(vectors_path)
    else:
        vectors = np.zeros((0, 512), dtype="float32")
    entries: dict[str, ProbeCacheEntry] = {}
    for item in manifest:
        entries[item["key"]] = ProbeCacheEntry(
            key=item["key"],
            path=item["path"],
            size=item["size"],
            mtime=item["mtime"],
            status=item["status"],
            detection_latency_ms=item["detection_latency_ms"],
            detections=tuple(
                CachedDetection(
                    bbox=tuple(detection["bbox"]),
                    confidence=detection["confidence"],
                    landmarks=detection["landmarks"],
                )
                for detection in item["detections"]
            ),
            embedding_indices=tuple(item["embedding_indices"]),
            embedding_latency_ms=tuple(item["embedding_latency_ms"]),
        )
    return LoadedCache(
        cache_dir=cache_dir,
        fingerprint=stored,
        probe_cache_id=stored_id,
        build_seconds=float(stored.get("build_seconds", 0.0)),
        vectors=vectors,
        entries=entries,
    )