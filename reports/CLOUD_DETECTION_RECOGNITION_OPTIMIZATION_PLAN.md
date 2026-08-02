# InsightFace Detection and Recognition Optimization Plan (DONE)

## Decision

The production realtime recognition pipeline uses InsightFace `buffalo_l`
only. MediaPipe remains limited to `app.py`, a lightweight cross-platform
detection preview and RTSP smoke test. It is not part of realtime recognition.

The first implementation uses one bounded worker and one source frame per
cycle. SCRFD detects all faces, then ArcFace embeds at most one scheduled
track. This removes unnecessary embedding work without adding a second worker,
a frame queue, or stale-frame races.

## Current Problem

The previous realtime loop called `FaceAnalysis.get(frame)`. That call runs
SCRFD detection and every non-detection model for every detected face before
the tracker can decide which face needs recognition. Tracker scheduling then
reduced FAISS searches, but did not reduce ArcFace GPU work.

## Target Architecture

```text
RTSP capture
  -> latest frame buffer, size 1
  -> InsightFace SCRFD detects all faces
  -> FaceTracker updates every visible track
  -> scheduler chooses at most one eligible track
  -> InsightFace ArcFace aligns and embeds the selected SCRFD detection
  -> FAISS IndexFlatIP search
  -> confirmation, events, MQTT, display, and optional output
```

## Invariants

- The realtime path does not call `FaceAnalysis.get()`.
- Every SCRFD detection is supplied to the tracker.
- ArcFace runs only for scheduler-selected tracks.
- Default embedding budget is one per cycle.
- Detection bbox and five SCRFD landmarks used for ArcFace come from the same
  source frame and same detection.
- Tracker identity state remains attached to `track_id`, not bbox coordinates.
- The tracker does not persist landmarks or embeddings between frames.
- A failed alignment or ArcFace inference is not evidence that a person is
  unknown. It leaves identity state unchanged and is reported as pipeline work
  that can be retried.
- Embeddings and FAISS gallery vectors remain normalized `float32`; inner
  product remains cosine similarity.
- Latest-frame behavior remains bounded. Do not add an unbounded queue.
- `--require-gpu` remains strict: CUDA must be active for both SCRFD and
  ArcFace.

## InsightFace API Boundary

`FaceEngine` owns all InsightFace internal APIs. Callers must not depend on
model-zoo classes or `FaceAnalysis.get()`.

```python
FaceEngine.detect_faces(frame) -> list[FaceDetection]
FaceEngine.embed_detected_face(frame, detection) -> FaceEmbedding | None
```

`FaceDetection` contains:

- integer clipped bbox;
- SCRFD detection confidence;
- copied `float32` five-point landmarks with shape `(5, 2)`, when available.

`detect_faces()` calls `app.det_model.detect(frame, max_num=0)` only.
`embed_detected_face()` creates an InsightFace `Face` with the same bbox and
landmarks, then calls `app.models["recognition"].get(frame, face)`. The
recognition model performs ArcFace landmark alignment before ONNX inference.

Only `detection` and `recognition` modules are loaded from `buffalo_l`. Age,
gender, and extra landmark models are excluded because the stream does not use
them.

## Scheduling Policy

At each `--recognition-fps` cycle:

1. Run SCRFD detection on the latest frame.
2. Update all tracks.
3. Build a frame-local mapping from `track_id` to SCRFD detection through
   `TrackAssignment`, not bbox equality.
4. Select no more than `--max-embeddings-per-cycle` tracks; default is `1`.
5. Prioritize `pending`, then `unknown`, then `matched` tracks due for refresh.
6. ArcFace embed only selected tracks that still have current landmarks.
7. Search FAISS and apply the existing threshold, confirmation, and
   label-switch-margin rules.

The existing scheduler tie-breakers (`last_recognition_frame`, then `track_id`)
give pending tracks fair turns under budget one.

## CLI Contract

```text
--recognition-fps N
    SCRFD/tracking/scheduling cycles per second. Default: 6.

--max-embeddings-per-cycle N
    Maximum selected ArcFace embeddings per cycle. Default: 1.

--det-size N
    SCRFD input size. Default: 640.
```

The first implementation does not have an independent detector cadence. Do not
interpret `--max-embeddings-per-cycle` as a detector face limit: SCRFD always
sees all faces.

## Tracker Association Contract

`FaceTracker.update_with_assignments(boxes, frame_id)` returns both tracks and
one `TrackAssignment(track_id, box_index)` for every visible matched or newly
created track. The worker resolves the selected track to the detection at that
index. This guarantees that ArcFace receives the exact current landmarks.

`FaceTracker.update()` remains as a compatibility wrapper for callers that only
need tracks.

## Metrics

Each `RecognitionResult` records:

- `detected_faces`;
- `embeddings_generated`;
- `detection_latency_ms`;
- `embedding_latency_ms`;
- total cycle latency and track counts.

`--profile` reports capture/display/recognition rate, embeddings per cycle,
detector and embedding latency, and visible/stale track counts. MQTT schema is
unchanged in this phase; metrics remain local profile data.

## Test Plan

Unit tests must cover:

1. SCRFD detection conversion, clipping, confidence, and landmarks.
2. ArcFace selected-detection alignment, normalization, dtype, shape, and
   invalid landmark handling.
3. No `FaceAnalysis.get()` call in split stream APIs.
4. One-to-one tracker assignments for new and matched tracks.
5. All detections update tracker state, while unselected detections do not call
   ArcFace or FAISS.
6. Budget one, override budgets, scheduler fairness, and confirmation behavior.
7. Detection/embedding failures do not create false unknown identities.
8. Latest-frame behavior, provider diagnostics, and static image enrollment/
   query compatibility.

## Real-Model Validation

Run on the Windows CUDA target with the installed `insightface==1.0.1` model:

1. Compare a baseline `FaceAnalysis.get()` embedding with split SCRFD + ArcFace
   for the same face.
2. Require cosine similarity `>= 0.99999` for representative images.
3. Validate one face, unknown face, three faces, motion, and short occlusion.
4. Verify CUDA is active for both detector and recognition sessions.

Do not lower recognition thresholds to mask an alignment mismatch.

## Benchmark Protocol

Use 1280x720 at 30 FPS, `--det-size 640`, `--recognition-fps 6`, CUDA required,
30-second warm-up, and at least 120 seconds per scenario.

| Scenario          | Required observation                                  |
| ----------------- | ----------------------------------------------------- |
| One enrolled face | Stable confirmation and periodic refresh              |
| One unknown face  | Valid unknown result without repeat overload          |
| Three faces       | All tracks visible; max one embedding per cycle       |
| Motion            | Track IDs and selected landmarks remain aligned       |
| Short occlusion   | Track TTL and recognition revalidation remain correct |

Record before/after capture FPS, display FPS, p50/p95 cycle latency, detector
latency, embedding latency, GPU use, VRAM, time-to-first identity, detected
faces, and embeddings per cycle.

## Acceptance Criteria

- No stream-path use of `FaceAnalysis.get()`.
- Every cycle detects all visible faces.
- `embeddings_generated <= max_embeddings_per_cycle`.
- Default runtime generates at most one ArcFace embedding per cycle.
- Static enrollment and image recognition continue to work.
- Existing confirmation, unknown, label-switch, snapshot, MQTT, and display
  behavior do not regress.
- Full unit suite passes.
- Real-model split embeddings meet equivalence target.
- Multi-face benchmark shows embeddings no longer scale with detected face count
  per cycle.

## Deferred Work

- Separate detector and recognition workers.
- Frame ring buffer and immutable recognition jobs.
- Independent detector cadence.
- Multiple in-flight ArcFace jobs.
- GPU FAISS.
- SORT/DeepSORT for crowded crossings or long occlusion.
- MQTT performance metrics and schema versioning.
