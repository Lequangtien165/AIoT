# Backlog

## P0 - Validate the Production Pipeline

- [x] Run webcam -> RTSP -> MediaPipe -> InsightFace -> FAISS on Windows with a real camera.
- [ ] Create an enrollment dataset in `dataset/<person>/` with multiple valid images per person.
- [x] Run `build_index.py` and verify static-image recognition for every enrolled person.
- [ ] Calibrate `--threshold` using genuine and impostor images; do not retain the `0.45` default if real data indicates otherwise.
- [ ] Verify snapshot/video output and storage consumption during long-running sessions.

## P1 - Realtime Reliability

- [ ] Benchmark SCRFD latency, ArcFace latency, embeddings per cycle, FPS, CPU/GPU usage, concurrent faces, and recognition latency.
- [ ] Tune the IoU threshold, track TTL, and recognition interval using a real camera.
- [ ] Test reconnection after prolonged publisher, MediaMTX, or RTSP interruptions.
- [ ] Test `VideoWriter` codec fallback on the target Windows machine.
- [ ] Add tests for FAISS batch search, snapshot transitions, and VideoWriter failures.

## P2 - Operations and Quality

- [ ] Add a configuration file for the RTSP URL, threshold, and output instead of relying only on CLI flags.
- [ ] Add Windows CI to test MediaPipe, ONNX Runtime, FAISS, and InsightFace imports on Python 3.14.
- [ ] Record calibrated benchmarks and thresholds in the operations documentation.
- [ ] Confirm that the InsightFace `buffalo_l` model license fits the intended use before deploying beyond a demo.

## P3 - Expansion

- [x] Accept a custom network RTSP URL in cloud detection and recognition clients.
- [x] Validate a real-camera RTSP source from Ubuntu Linux ARM64 over the LAN.
- [ ] Validate RTSP input from Raspberry Pi 4 and Pi Camera.
- [ ] Add JSON/API events for external systems.
- [ ] Upgrade the IoU tracker if long occlusions or crowded crossings become necessary.
- [ ] Define recording policy, retention, and biometric-data protections before retaining data long term.

## 2026-07-28 Progress Notes

### Completed - Full Pipeline GPU Path

- [x] Refactored realtime recognition into a latest-frame capture thread, background `RecognitionWorker`, and independent display loop so UI rendering no longer blocks on InsightFace inference.
- [x] Removed MediaPipe from the realtime recognition path; `recognize_stream.py` now uses InsightFace for detection + embeddings and FAISS for identity lookup.
- [x] Added GPU diagnostics and fail-fast behavior: `FaceEngine` reports requested/effective ONNX Runtime providers, `--require-gpu` exits when CUDA is unavailable, and startup logs show `GPU active` when `CUDAExecutionProvider` is actually bound.
- [x] Diagnosed CUDA fallback causes: `get_available_providers()` was not enough proof of GPU execution; missing `cublasLt64_13.dll`, CUDA 13 runtime loading, and old NVIDIA driver support caused CPU fallback.
- [x] Validated the Windows GPU path after updating the NVIDIA driver: `FaceEngine.providers` became `['CUDAExecutionProvider', 'CPUExecutionProvider']` and `gpu_active=True`.
- [x] Updated Windows run instructions in `README.md`, including PowerShell venv activation, exact DirectShow camera names, GPU provider validation, `--recognition-fps`, `--profile`, `--require-gpu`, and `nvidia-smi -l 1`.

### Completed - Duplicate Tracking Overlay Fix

- [x] Fixed duplicate/stale overlay boxes by excluding tracks with `missed_frames > 0` from the display snapshot.
- [x] Added center-distance + size-ratio fallback matching so a moving face can keep the same `track_id` when IoU briefly drops.
- [x] Reduced realtime recognition track TTL default and added `--matched-recognition-interval-frames` so already matched tracks are refreshed less aggressively.
- [x] Prioritized recognition scheduling as `pending -> unknown -> matched` to reduce unnecessary repeated identity checks.
- [x] Added profile counters for `active_tracks`, `visible_tracks`, and `stale_tracks` to confirm that boxes are not accumulating on screen.
- [x] Split the realtime InsightFace `buffalo_l` path: SCRFD detects all faces, the tracker assigns all detections, and ArcFace embeds only scheduler-selected tracks (default budget: one per cycle).

### Validation Performed

- [x] Ran full unit test suite after the GPU pipeline refactor: `venv\Scripts\python.exe -m unittest discover -s tests -v` passed 36 tests.
- [x] Ran full unit test suite after the tracking overlay fix: `venv\Scripts\python.exe -m unittest discover -s tests -v` passed 41 tests.
- [x] Ran `git diff --check` after edits; only Windows LF/CRLF warnings were observed, with no whitespace errors.
- [x] Created and pushed `fix/full-pipeline` with the full GPU pipeline and tracking overlay fixes.

### Still Open

- [ ] Benchmark sustained runtime with multiple faces and record target values for `capture_fps`, `display_fps`, detector/embedding latency, embeddings per cycle, GPU utilization, and recognition latency.
- [ ] Calibrate `--threshold`, `--recognition-fps`, `--track-iou-threshold`, `--track-ttl-frames`, and `--matched-recognition-interval-frames` using real genuine/impostor samples.
- [ ] Run long-duration tests for RTSP reconnects, snapshot/video output, VRAM stability, and storage growth.
- [ ] Decide whether long occlusions or crowded face crossings require replacing the lightweight tracker with a stronger tracker such as SORT/DeepSORT.

## 2026-08-01 Progress Notes

### Completed - Linux ARM64 Edge Publisher Validation

- [x] Added and validated the Linux ARM64 V4L2 publisher: webcam -> FFmpeg -> MediaMTX -> LAN RTSP -> Windows detection and recognition.
- [x] Verified Windows cloud consumers reconnect after the Linux ARM64 publisher is restarted.
- [x] Confirmed stable sustained streaming from the Ubuntu ARM64 VM with the project publisher code.
- [ ] Validate the separate Raspberry Pi 4 and Pi Camera hardware path.

## 2026-08-02 Progress Notes

### Completed - IDOC Dataset Preparation

- [x] Downloaded and unpacked the IDOC mugshot dataset into local raw-data folders under `data_raw/` and `archive/`.
- [x] Created a 3,000-image demo subset under `dataset/IDOC_000001` through `dataset/IDOC_001500`, with each folder containing `front.jpg` and `side.jpg`.
- [x] Verified all 3,000 copied JPEG images decode successfully with OpenCV.
- [x] Added `dataset/IDOC_manifest.csv` as a lightweight folder-to-source-ID mapping for the selected subset.
- [x] Updated `build_index.py` so IDOC folders are relabeled from the manifest and `labels_utf8.csv` as `ID - Sex`, for example `A00147 - Male`.
- [x] Updated `recognize_stream.py` so matched IDOC labels draw red bounding boxes while ordinary enrolled names remain green.

### Completed - MQTT Runtime Validation Fixes

- [x] Installed `paho-mqtt` in the project virtual environment.
- [x] Fixed `scripts/run_mqtt_logger.py` so it can be run directly from the repository root without `PYTHONPATH=.`.
- [x] Fixed `aiot/mqtt/client.py` compatibility with `paho-mqtt 2.1.0` `ReasonCode` objects.
- [x] Added unit tests for MQTT reason-code handling.
- [x] Validated the MQTT audit flow through a local TCP MQTT broker harness: `recognition/result`, `motion/detected`, and `error/pipeline` were persisted to SQLite, while `system/status` was not persisted.
- [x] Ran the full unit suite after the MQTT and dataset-label changes: `venv\Scripts\python.exe -m unittest discover -s tests -v` passed 89 tests.

### Still Open

- [ ] Rebuild `database/faces.index` and `database/metadata.json` after the IDOC relabeling change before running the live recognition demo.
- [ ] Validate the MQTT flow with a real Mosquitto broker once Mosquitto is available on the target machine.
- [ ] Keep raw mugshot images, generated embeddings, metadata, and audit databases out of Git history unless the publication policy explicitly allows them.
