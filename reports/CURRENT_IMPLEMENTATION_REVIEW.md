# Current Implementation Review

## Scope

This review compares the current codebase with `reports/KE_HOACH_TRIEN_KHAI.md` and `reports/BaoCao_KienTruc_AIoT.docx`. It is a code and documentation review; it does not replace real Pi Camera, LAN, endurance, or benchmark validation.

## Progress Summary

| Area | Status |
| --- | --- |
| Generic Windows/Linux ARM64 V4L2 RTSP publisher | Implemented |
| Cloud MediaPipe detection | Implemented |
| Windows InsightFace and FAISS recognition | Implemented |
| MQTT broker, scoped topics, TLS, ACL, audit logger | Implemented as an MVP |
| Software motion-triggered edge session | Implemented, hardware validation pending |
| Raspberry Pi Camera CSI | Not implemented or validated |
| Browser live-surveillance web service | Not implemented |
| Full stream control (`start`, `restart`, settings, snapshot) | Not implemented |
| Calibration, endurance, and benchmark evidence | Incomplete |

The current demonstrable flow is:

```text
Generic edge camera
-> software motion trigger
-> RTSP session
-> cloud recognition
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
2. The report describes Raspberry Pi Camera CSI. The code supports Linux ARM64 V4L2/UVC capture only. Pi Camera CSI remains unimplemented and unvalidated.
3. The report describes dlib ResNet embeddings. The code uses InsightFace `buffalo_l`: SCRFD detection, ArcFace embeddings, and FAISS `IndexFlatIP`.
4. The report includes a web server/browser UI as a cloud component. No Flask/FastAPI service, MJPEG, WebSocket, HLS, WebRTC, or browser UI exists.
5. The report describes cloud control for start, stop, resolution, and snapshot. Current code implements only the stop MVP; start and restart have no supervisor implementation.

## Current Functional Gaps

### Motion Session Control

1. `stop` can terminate the entire edge daemon while motion mode is idle. In the intended design, stop in motion mode should end the active FFmpeg session and return to monitoring without stopping MediaMTX or MQTT.
2. `start` and `restart` are accepted by basic validation but are operational no-ops. A persistent edge supervisor is required before they can work after a publisher stops.
3. An immediate FFmpeg startup failure publishes `error/rtsp` but does not publish `motion/detected` with `active=false` or a retained `monitoring` status. Consumers can retain stale starting or motion-active state.
4. If MediaMTX exits during a motion session, the runtime stops FFmpeg and returns to monitoring without restarting or terminating the failed MediaMTX process. Later motion can start FFmpeg against a dead RTSP server.
5. The motion strategy says the edge waits for RTSP path readiness. Current code waits one second and only checks that FFmpeg has not exited; it does not probe the RTSP path before publishing `streaming`.

### MQTT Reliability And Validation

1. Retained status has no MQTT Last Will fallback. A power loss or hard crash can leave stale retained `running` or `streaming` state and prompt cloud RTSP connection attempts to an offline edge.
2. Control payload validation checks schema version, target device ID, and action only. It does not validate timestamp, requester, parameters type, or a stricter payload schema.
3. Broker integration covers authentication, audit persistence/redaction, and scoped control delivery. It does not cover TLS handshake, restart/reconnect, retained-status replay, unauthorized controller publish, or a real process-level edge/cloud/logger flow.

### Hardware And Performance

1. No automated test covers `run_motion_triggered`, camera handoff, or actual FFmpeg and OpenCV ownership transitions.
2. Pi Camera CSI, `rpicam-*`, hardware H.264 behavior, temperature, and session cycling remain unverified.
3. Recognition threshold calibration, sustained runtime, FPS/latency measurements, VRAM/RAM measurements, and multi-face fairness evidence remain incomplete.

## Existing Test Coverage

- Unit tests cover session timeout and face-presence lease semantics.
- Unit tests cover Linux V4L2 device parsing and FFmpeg command construction.
- MQTT integration tests cover broker authentication, selected audit persistence, RTSP credential redaction, and controller-to-edge topic delivery.
- Tests do not replace real hardware validation or process-level end-to-end testing.

## Documentation Accuracy

### Accurate

- `BACKLOG.md` correctly keeps web UI, Pi Camera CSI, camera tuning, and several MQTT integration cases open.
- README correctly identifies Linux ARM64 V4L2 support and does not claim Pi Camera CSI is ready.
- README documents stop as the only current control MVP action.

### Requires Update

1. `reports/KE_HOACH_TRIEN_KHAI.md` still says Linux ARM64 is unsupported and untested. It should distinguish validated generic V4L2/UVC support from pending Pi Camera CSI support.
2. `reports/KE_HOACH_TRIEN_KHAI.md` says motion-triggered streaming is absent, but software MOG2 motion sessions and cloud face leases are implemented.
3. The plan's TLS/Pi validation wording conflicts with `BACKLOG.md`. Local Docker broker validation is complete; real Pi-originated TLS validation remains pending unless it has been recorded with actual hardware evidence.
4. README should not say software motion integration is outside the MQTT MVP. Only Pi-specific validation and web UI remain outside the completed software MVP.
5. `reports/EDGE_MOTION_TRIGGERED_STREAM_STRATEGY.md` mixes implemented behavior with future architecture. ROI filtering, RTSP readiness probes, error/stopping state publication, MJPEG buffering, web service, and WebSocket/SSE should be marked as future work until implemented.
6. The README CUDA verification command checks only the detector session and uses a personal hard-coded model path. It does not prove ArcFace CUDA availability required by `--require-gpu`.

## Recommended Priority

1. Fix motion-session state/status cleanup, MediaMTX failure behavior, and stop semantics.
2. Validate the generic camera handoff loop repeatedly on available Windows/Linux hardware.
3. Reconcile the implementation plan, architecture report, README, backlog, and motion strategy with actual code.
4. Build the browser live-surveillance consumer and annotated-video delivery path.
5. Validate Pi Camera CSI only after the generic session lifecycle is stable.
6. Add benchmark/calibration/endurance evidence for the final demo.
7. Review and resolve newly reported SonarCloud issues last. Do not suppress or mark them false-positive without confirming the analyzer context, the affected code path, and regression coverage.
