# Backlog

## P0 - Validate the Production Pipeline

- [ ] Run webcam -> RTSP -> MediaPipe -> InsightFace -> FAISS on Windows with a real camera.
- [ ] Create an enrollment dataset in `dataset/<person>/` with multiple valid images per person.
- [ ] Run `build_index.py` and verify static-image recognition for every enrolled person.
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

- [ ] Support RTSP from network cameras/Raspberry Pi instead of only `127.0.0.1`.
- [ ] Add JSON/API events for external systems.
- [ ] Upgrade the IoU tracker if long occlusions or crowded crossings become necessary.
- [ ] Define recording policy, retention, and biometric-data protections before retaining data long term.
