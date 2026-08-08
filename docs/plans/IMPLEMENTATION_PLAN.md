# Implementation Plan (Status Update 2026-08-08)

> **Status**: Current (2026-08-08) — what is implemented vs. remaining work.
> Part of the [documentation hub](../README.md).

> Updated after Gate 1 (profile-based edge deployment) and Gate 2 (MQTT edge
> control). Earlier versions of this file predate both gates and described them
> as outstanding; they are now implemented.

## Current Status

| Area | Status |
|---|---|
| Raspberry Pi 4 edge: CSI direct publisher | Implemented (`rpi-csi` profile, `config/mediamtx-rpi.yml`, MediaMTX `rpiCamera` + hardware H.264, systemd unit `deploy/systemd/aiot-rpi-csi.service`). Manually validated on 2026-08-05; automated profile/preflight/systemd re-validation on real hardware pending. |
| Raspberry Pi 4 edge: V4L2/UVC publisher | Implemented and validated (Linux ARM64, `/dev/videoN`, `v4l2` profile). |
| MQTT control plane | Implemented MVP: broker (Docker Mosquitto, TLS profile on 8883), persistent agent (`scripts/run_edge_agent.py`), `status`/`start`/`stop`/`restart` with command-id idempotency and acks carrying the resulting state. |
| Motion-triggered streaming | Implemented: OpenCV MOG2 software motion detector (no PIR hardware), cloud `face_presence` lease (30s discovery, 120s keepalive). Validated on Windows; Pi software-motion adapter with a CSI camera is a separate unvalidated adapter. |
| Consumers and audit logging | Implemented: `scripts/run_mqtt_logger.py` persists `recognition/result`, `motion/detected`, `error/#` to SQLite with schema validation, redaction, and retention. |
| Live-surveillance web application | Not implemented (Flask/FastAPI + MJPEG/WebSocket/HLS/WebRTC + `recognition/result` UI remain future work). |
| Real-world validation and tuning | Incomplete: threshold calibration intentionally deferred to close the demo; FPS/latency/GPU benchmarks and endurance tests remain open. |

## End-To-End Flow

The verified local demo sequence (Windows edge + Docker Mosquitto, recorded in
`../RUNBOOK.md`) is:

```text
Docker Mosquitto broker
  -> edge agent (supervises stream_server.py)
  -> MediaMTX + FFmpeg (or MediaMTX rpiCamera for rpi-csi)
  -> RTSP 1280x720@30 H.264 on 8554
  -> controller status/stop/start (acks with state, retained status)
  -> audit logger -> SQLite (recognition/result, error/#)
```

## Remaining Work

- Re-validate the `rpi-csi` profile, preflight, and systemd boot recovery on the target Pi hardware (planned at school).
- Verify the demo sequence with `recognize_stream.py` publishing real `recognition/result` events in the same run.
- Web application (optional post-demo).
- Calibration, endurance, and benchmark evidence (optional post-demo).
