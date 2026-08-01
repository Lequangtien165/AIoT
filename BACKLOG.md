# Backlog

## P0 - Validate the Production Pipeline

- [x] Run webcam -> RTSP -> MediaPipe -> InsightFace -> FAISS on Windows with a real camera.
- [ ] Create an enrollment dataset in `dataset/<person>/` with multiple valid images per person.
- [x] Run `build_index.py` and verify static-image recognition for every enrolled person.
- [ ] Calibrate `--threshold` using genuine and impostor images; do not retain the `0.45` default if real data indicates otherwise.
- [ ] Verify snapshot/video output and storage consumption during long-running sessions.

## P1 - Realtime Reliability

- [ ] Benchmark FPS, CPU usage, concurrent faces, and recognition latency.
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

### Validation Performed

- [x] Ran full unit test suite after the GPU pipeline refactor: `venv\Scripts\python.exe -m unittest discover -s tests -v` passed 36 tests.
- [x] Ran full unit test suite after the tracking overlay fix: `venv\Scripts\python.exe -m unittest discover -s tests -v` passed 41 tests.
- [x] Ran `git diff --check` after edits; only Windows LF/CRLF warnings were observed, with no whitespace errors.
- [x] Created and pushed `fix/full-pipeline` with the full GPU pipeline and tracking overlay fixes.

### Still Open

- [ ] Benchmark sustained runtime with multiple faces and record target values for `capture_fps`, `display_fps`, `recognition_fps`, GPU utilization, and recognition latency.
- [ ] Calibrate `--threshold`, `--recognition-fps`, `--track-iou-threshold`, `--track-ttl-frames`, and `--matched-recognition-interval-frames` using real genuine/impostor samples.
- [ ] Run long-duration tests for RTSP reconnects, snapshot/video output, VRAM stability, and storage growth.
- [ ] Decide whether long occlusions or crowded face crossings require replacing the lightweight tracker with a stronger tracker such as SORT/DeepSORT.

## 2026-08-01 Progress Notes

### Completed - Linux ARM64 Edge Publisher Validation

- [x] Added and validated the Linux ARM64 V4L2 publisher: webcam -> FFmpeg -> MediaMTX -> LAN RTSP -> Windows detection and recognition.
- [x] Verified Windows cloud consumers reconnect after the Linux ARM64 publisher is restarted.
- [x] Confirmed stable sustained streaming from the Ubuntu ARM64 VM with the project publisher code.
- [ ] Validate the separate Raspberry Pi 4 and Pi Camera hardware path.
