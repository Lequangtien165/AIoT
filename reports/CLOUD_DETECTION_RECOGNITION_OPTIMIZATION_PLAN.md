# Cloud Detection and Recognition Optimization Plan

## Current Architecture

The project currently has two separate pipelines.

### Detection Preview

`app.py` uses MediaPipe BlazeFace for a detection-only preview:

```text
RTSP -> MediaPipe detection -> green bounding boxes -> local preview window
```

This pipeline does not perform recognition.

### Realtime Recognition

`recognize_stream.py` does not use MediaPipe. It uses InsightFace `buffalo_l` for both face detection and embedding generation:

```text
RTSP capture
  -> retain only the latest frame
  -> run at the configured recognition FPS, default 6 FPS:
       InsightFace detects all faces
       InsightFace generates an embedding for every detected face
  -> IoU/center-distance tracker assigns track IDs
  -> FAISS matches identities and the tracker confirms labels
  -> annotated display output
```

Relevant implementation locations:

- Latest-frame capture: `recognize_stream.py:164-232`
- Recognition rate limiting: `recognize_stream.py:53-70`, `recognize_stream.py:287-304`
- InsightFace detection and embeddings: `recognize_stream.py:307`, `aiot/recognition/face_engine.py:126-145`
- Tracking: `aiot/tracking/face_tracker.py:95-129`
- FAISS matching and confirmation: `recognize_stream.py:322-331`, `aiot/tracking/face_tracker.py:152-189`

## Existing Performance Strategy

- Latest-frame capture discards old frames instead of accumulating processing latency.
- `--recognition-fps` caps costly inference below source video FPS.
- Identity state is attached to `track_id`, not bounding-box coordinates.
- A track must satisfy the minimum age and face-size requirements before recognition.
- Identity confirmation requires two consecutive recognition results.
- Confirmed matches are refreshed less often than pending or unknown tracks.
- Pending tracks have the highest recognition priority, followed by unknown and matched tracks.
- InsightFace can use CUDA on the Windows cloud laptop, while FAISS runs efficiently on CPU.

## Current Limitation

Tracking does not yet avoid the full embedding cost.

On every scheduled inference frame, this call detects all faces and produces an embedding for every face before recognition scheduling occurs:

```python
observations = self.engine.extract_faces(stream_frame.frame)
```

The tracker reduces FAISS searches, label changes, and refresh frequency. However, it does not prevent InsightFace from generating embeddings for faces that are not selected for recognition. In addition, `maximum=len(observations)` can select every eligible track in one inference cycle.

## Optimization Goal

Keep the current responsive, latest-frame architecture while separating detection from embedding work. Detection should update all tracks, while embeddings should be generated only for tracks selected by the recognition scheduler.

Target architecture:

```text
RTSP capture
  -> latest-frame buffer of size 1
  -> detector at a configured cadence
  -> tracker updates track IDs and bounding boxes
  -> scheduler selects eligible tracks
  -> crop/align/embed only selected tracks
  -> FAISS CPU similarity search
  -> confirmation, events, and annotated display
```

## Proposed Implementation Direction

### 1. Separate Detection and Embedding APIs

- Refactor `FaceEngine` so detection and embedding extraction are explicit, independently callable operations.
- Retain the existing `extract_face_from_bbox()` capability or evolve it into the embedding path for a selected tracked face.
- Ensure face alignment is retained before ArcFace embedding inference.

### 2. Preserve a Lightweight Detector Path

- Evaluate MediaPipe BlazeFace as the detector when cloud CPU capacity and frame rate make it suitable.
- Evaluate InsightFace SCRFD as the detector when CUDA is available and detection quality is more important.
- Use one detector per realtime-recognition pipeline; do not run MediaPipe and InsightFace detection on every frame.

### 3. Limit Embedding Work per Cycle

- Keep the existing scheduler conditions: track age, face size, status priority, and refresh interval.
- Set an explicit low maximum number of embeddings per cycle, initially one track.
- Prioritize pending tracks, then unknown tracks, then confirmed tracks that are due for refresh.
- Do not generate embeddings for tracks that are not selected.

### 4. Keep Identity Reliability Rules

- Preserve normalized `float32` embeddings and FAISS `IndexFlatIP`, where scores are cosine similarities.
- Preserve the calibrated recognition threshold requirement.
- Preserve repeated-result confirmation before exposing a stable identity.
- Preserve identity-change margin handling to avoid label flapping.

### 5. Instrument Before and After

- Record capture FPS, display FPS, detector FPS, embedding FPS, and end-to-end recognition latency.
- Record the number of detected faces, active tracks, and embeddings generated per inference cycle.
- Benchmark single face, multiple faces, unknown faces, and temporary occlusion scenarios.
- Compare GPU utilization and memory before and after the separation.

## When to Apply This Optimization

The current InsightFace-only approach is practical for the Windows RTX 3050 cloud laptop and is suitable for a simple demo. Prioritize this optimization when one or more of the following occurs:

- Multiple faces cause recognition latency or low display responsiveness.
- GPU utilization is consistently high at the required recognition rate.
- The system must support lower-spec cloud hardware.
- A measured benchmark demonstrates unnecessary embeddings are the bottleneck.

Until then, retain the current approach because it is simpler, accurate, and already supports tracking, confirmation, CUDA diagnostics, snapshots, and optional recording.
