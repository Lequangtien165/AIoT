# Current Implementation Review

> **Status**: Current (2026-08-08) — codebase vs. architecture review, current gaps.
> Part of the [documentation hub](../README.md).

> Updated 2026-08-08 after Gate 1 (profile-based edge deployment) and Gate 2
> (MQTT edge control). The original review predates both gates; stale claims
> below have been corrected to the current codebase state.

## Scope

This review compares the current codebase with `IMPLEMENTATION_PLAN.md` and `../legacy/ARCHITECTURE_REPORT_LEGACY.md`. It is a code and documentation review; it does not replace real Pi Camera, LAN, endurance, or benchmark validation.

## Progress Summary

| Area | Status |
| --- | --- |
| Generic Windows DirectShow / macOS AVFoundation / Linux ARM64 V4L2 RTSP publisher | Implemented, profile-based (`dshow`, `avfoundation`, `v4l2`) |
| Raspberry Pi Camera CSI direct publisher | Implemented (`rpi-csi` profile, MediaMTX `rpiCamera` + hardware H.264, no FFmpeg); validated manually on 2026-08-05, automated profile/systemd pending hardware re-validation |
| Cloud MediaPipe detection | Implemented |
| Windows InsightFace and FAISS recognition | Implemented |
| MQTT broker, scoped topics, TLS, ACL, audit logger | Implemented; broker restart/reconnect, retained replay, and unauthorized-publish cases covered by opt-in integration tests |
| Software motion-triggered edge session | Implemented and validated on Windows; Pi software-motion adapter pending |
| Persistent edge control (status/start/stop/restart) | Implemented (`run_edge_agent.py` + `EdgeSupervisor` state machine, command-id idempotency, ack with resulting state) |
| Browser live-surveillance web service | Not implemented |
| Calibration, endurance, and benchmark evidence | Incomplete (threshold calibration intentionally deferred; demo closes first) |

The current demonstrable flow is:

```text
Generic edge camera (or Pi CSI)
-> RTSP session
-> cloud recognition
-> MQTT control plane (status/start/stop/restart, acks, retained status)
-> MQTT face-presence lease
-> SQLite audit trail
```

## Alignment With Architecture

### Aligned

- RTSP carries continuous video while MQTT carries control and discrete events.
- Edge publishes status and RTSP errors; cloud publishes recognition and pipeline errors.
- Mosquitto topic fan-out plus SQLite audit logging replaces Kafka for the demo scope.
- Recognition stays in the cloud tier instead of running face AI on the edge.
- Mosquitto can run on the cloud laptop through Docker with password authentication, ACLs, and an optional TLS profile.

### Architecture Gaps Or Changes

1. The report describes a PIR GPIO sensor. The code uses an OpenCV MOG2 software motion detector at the edge. The report should describe significant-motion triggering and cloud face-presence session renewal instead of PIR hardware.
2. The report describes Raspberry Pi Camera CSI. This is now implemented as the `rpi-csi` profile (`config/mediamtx-rpi.yml`, MediaMTX `rpiCamera` source, hardware H.264, systemd unit in `deploy/systemd/`), with the V4L2/FFmpeg profile retained for USB cameras.
3. The report describes dlib ResNet embeddings. The code uses InsightFace `buffalo_l`: SCRFD detection, ArcFace embeddings, and FAISS `IndexFlatIP`.
4. The report includes a web server/browser UI as a cloud component. No Flask/FastAPI service, MJPEG, WebSocket, HLS, WebRTC, or browser UI exists.
5. The report describes cloud control for start, stop, resolution, and snapshot. `start`, `stop`, `restart`, and `status` are implemented through the persistent edge agent; resolution/snapshot control remains future work.

## Current Functional Gaps

### Motion Session Control

1. `stop` can terminate the entire edge daemon while motion mode is idle. In the intended design, stop in motion mode should end the active FFmpeg session and return to monitoring without stopping MediaMTX or MQTT.
2. An immediate FFmpeg startup failure publishes `error/rtsp` but does not publish `motion/detected` with `active=false` or a retained `monitoring` status. Consumers can retain stale starting or motion-active state.
3. If MediaMTX exits during a motion session, the runtime stops FFmpeg and returns to monitoring without restarting or terminating the failed MediaMTX process. Later motion can start FFmpeg against a dead RTSP server.
4. The motion strategy says the edge waits for RTSP path readiness. Current code waits one second and only checks that FFmpeg has not exited; it does not probe the RTSP path before publishing `streaming`.

### MQTT Reliability And Validation

1. Retained status has no MQTT Last Will fallback. A power loss or hard crash can leave stale retained `running` or `streaming` state and prompt cloud RTSP connection attempts to an offline edge.
2. Control payload validation in `stream_server.py` checks schema version, target device ID, and action only. The edge agent's `EdgeSupervisor` additionally rejects unknown fields, empty/oversized command IDs, empty requester, and non-empty `parameters`; it never executes command strings.
3. Broker integration covers authentication, audit persistence/redaction, scoped control delivery, broker restart/reconnect, retained-status replay, and unauthorized controller publishes. TLS handshake and a real process-level edge/cloud/logger flow remain unverified.

### Hardware And Performance

1. No automated test covers `run_motion_triggered`, camera handoff, or actual FFmpeg and OpenCV ownership transitions.
2. Pi Camera CSI with the `rpi-csi` profile, `rpicam-*` preflight on the real device, hardware H.264 behavior, temperature, systemd boot recovery, and session cycling remain unverified since the Gate 1 automation.
3. Recognition threshold calibration (intentionally deferred), sustained runtime, FPS/latency measurements, VRAM/RAM measurements, and multi-face fairness evidence remain incomplete.

## Existing Test Coverage

- Unit tests cover profile lifecycle (`tests/test_profiles.py`), session timeout and face-presence lease semantics, Linux V4L2 and Windows DirectShow device parsing, FFmpeg command construction, edge supervisor state transitions, and agent command handling.
- MQTT integration tests cover broker authentication, selected audit persistence, RTSP credential redaction, controller-to-edge topic delivery, retained delivery, broker restart replay, and unauthorized controller publish rejection.
- Tests do not replace real hardware validation or process-level end-to-end testing; the verified local end-to-end demo sequence is recorded in `../RUNBOOK.md`.

## Documentation Accuracy

### Accurate

- `BACKLOG.md` correctly keeps web UI, Pi software-motion adapter, calibration, endurance, and benchmark evidence open while closing Gate 1 and Gate 2 items.
- `README.md` documents the four deployment profiles, the `rpi-csi` direct publisher, the full control MVP, and the Pi systemd deployment; it does not claim the Pi software-motion adapter is ready.
- `../RUNBOOK.md` is the single end-to-end operations runbook with the verified demo sequence.
- `IMPLEMENTATION_PLAN.md` was updated to the current status table.
- The README CUDA verification command checks only the detector session and uses a personal hard-coded model path. It does not prove ArcFace CUDA availability required by `--require-gpu`.

## Recommended Priority

1. Validate the generic camera handoff loop repeatedly on available Windows/Linux hardware.
2. Re-validate Pi Camera CSI on hardware with the `rpi-csi` profile, preflight, and systemd boot recovery (scheduled; Pi stream already ran before Gate 1 automation).
3. Verify the demo sequence with `recognize_stream.py` publishing real `recognition/result` events.
4. Build the browser live-surveillance consumer and annotated-video delivery path.
5. Add benchmark/endurance evidence for the final demo (threshold calibration intentionally skipped to close the project).
6. Review and resolve newly reported SonarCloud issues last. Do not suppress or mark them false-positive without confirming the analyzer context, the affected code path, and regression coverage.
