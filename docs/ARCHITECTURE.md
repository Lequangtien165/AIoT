# AIoT System Architecture (Current, 2026-08-08)

> This document describes the **implemented** system. The idea-stage
> architecture report is legacy material in `legacy/` and differs in
> several decisions: PIR hardware became a software MOG2 motion detector, dlib
> became InsightFace, the actuator became the MQTT control plane + audit trail,
> and the web UI is the dashboard described in section 7. See the
> [documentation hub](README.md).

## 1. Overview

A two-tier AIoT face recognition pipeline. The **edge** captures and publishes
video; the **cloud** runs detection, recognition, and identity search; MQTT
carries control and discrete events; a browser dashboard combines live WebRTC
video with the audit timeline. Two planes are strictly separated:

- **Data plane (video)**: edge camera -> RTSP (TCP, H.264) -> cloud consumers;
  MediaMTX also serves WebRTC (`:8889`) for browser playback.
- **Control plane (events)**: MQTT (Mosquitto, MQTTv5) for status, health,
  commands, recognition results, motion events, and audit.

```text
Edge (Windows / macOS / Linux ARM64 / Raspberry Pi)
  camera -> [FFmpeg ->] MediaMTX -> RTSP :8554/camera   (H.264 1280x720@30)
                                    -> WebRTC :8889/camera (browser)
              ^ supervised by stream_server.py (per profile)
              |
Cloud laptop (Windows AMD64)
  app.py               MediaPipe preview (reconnecting RTSP client)
  recognize_stream.py  InsightFace SCRFD + ArcFace -> FAISS -> MQTT recognition/result
  run_mqtt_logger.py   audit -> SQLite (recognition/result, motion/detected, error/#, control/ack/+)
  run_dashboard.py     FastAPI + WebSocket: live video, boxes, timeline, edge control
  Mosquitto (Docker)   broker: localhost plaintext 1883, LAN TLS 8883, ACLs
  run_edge_agent.py    persistent MQTT supervisor for a publisher child
```

Only the edge (1 device) and the cloud tier (1 machine, all services) are
required; browsers/clients are consumers over the LAN.

## 2. Edge Publisher: Deployment Profiles

`aiot/streaming/profiles.py` owns the profile registry, auto-detection, and
preflight checks. MediaMTX is **always** supervised; FFmpeg is an optional
publisher child used only by FFmpeg-based profiles.

| Profile | Platform | Camera | Publisher chain | FFmpeg |
|---|---|---|---|---|
| `dshow` | Windows AMD64 | USB/webcam | FFmpeg (dshow) -> MediaMTX | required |
| `avfoundation` | macOS Apple Silicon | built-in/USB | FFmpeg (avfoundation) -> MediaMTX | required |
| `v4l2` | Linux ARM64 | USB `/dev/videoN` | FFmpeg (v4l2) -> MediaMTX | required |
| `rpi-csi` | Linux ARM64 (Pi) | CSI module | MediaMTX `rpiCamera` -> hardware H.264 | not used |

- Auto-detection: Windows -> `dshow`, macOS -> `avfoundation`, Linux -> `v4l2`.
  `rpi-csi` is **never** auto-detected (a Pi camera may be CSI or USB/V4L2) and
  must be requested with `--profile rpi-csi`.
- `preflight()` returns a problems list before any process starts: tools per
  profile, the per-profile MediaMTX config file, and for `rpi-csi` also the
  `rpicam-*` stack, camera enumeration, and a free RTSP port — without
  requiring V4L2 or `libx264`.
- `--motion-triggered` is rejected with `rpi-csi` (MediaMTX owns the camera via
  libcamera; motion detection needs an OpenCV/V4L2 device).
- The Pi can run `deploy/systemd/aiot-rpi-csi.service` (`Restart=always`,
  `User=pi`, `Group=video`) for boot start and crash recovery. It must not run
  concurrently with `run_edge_agent.py`.

## 3. Data Plane: RTSP And WebRTC

- MediaMTX listens on `0.0.0.0:8554`, RTSP over TCP only (`rtspTransports: [tcp]`).
- Path `camera`; cloud clients read `rtsp://<EDGE_IP>:8554/camera`.
- `rpi-csi` uses `config/mediamtx-rpi.yml` (`source: rpiCamera`,
  `rpiCameraCodec: hardwareH264`); keys are verified against the pinned
  MediaMTX version's source (`rpiCameraCodec` replaced the legacy boolean).
- Browser output: both MediaMTX configs enable WebRTC (`webrtc: true`,
  `webrtcAddress: :8889`, `webrtcEncryption: false` on the trusted LAN, UDP mux
  `webrtcLocalUDPAddress: :8189`). Browsers consume the path via WHEP
  (`POST /camera/whep`); this is a separate output and does not change the RTSP
  TCP transport. Multi-NIC hosts may need `webrtcLocalIP` (see RUNBOOK
  troubleshooting).
- Health: `aiot/streaming/rtsp_probe.py` sends a DESCRIBE probe; MediaMTX
  answers 200 only while a publisher serves the path (OPTIONS was rejected as a
  false-positive health signal).

## 4. Control Plane: MQTT

Broker: Docker Mosquitto 2.0. Plaintext `1883` binds to localhost only; LAN
clients use the TLS profile on `8883`. ACLs are per-user and device-scoped
(`config/mosquitto/aclfile`, LF-only). Client uses MQTTv5 so ACL-rejected
publishes surface as `MqttPublishError`.

Topics (QoS/retention centralized in `aiot/mqtt/topics.py`):

| Topic | Direction | Retained | Purpose |
|---|---|---|---|
| `system/status/<device>` | edge -> cloud | yes | state, heartbeat metrics, `rtsp_healthy`, `rtsp_stream_active` |
| `control/stream/<device>` | controller -> edge | no | `status`, `start`, `stop`, `restart` commands |
| `control/ack/<device>` | edge -> controller | no | command ack with `result`, `state`, echoed `command_id` |
| `error/rtsp/<device>`, `error/pipeline/<device>` | edge/cloud | no | RTSP and pipeline failures |
| `motion/detected` | edge | no | software motion trigger on/off |
| `stream/activity/<device>` | cloud -> edge | no | `face_presence` session lease |
| `recognition/result` | cloud | no | recognition audit events |

### Persistent Edge Agent (`scripts/run_edge_agent.py`)

Supervises a fixed `stream_server.py --no-mqtt` child and owns the publisher
process tree (stop releases it: `taskkill /T /F` on Windows, SIGTERM -> SIGINT
on POSIX). State machine (`aiot/streaming/edge_supervisor.py`):

```text
offline -> starting -> streaming -> stopping -> stopped
                    \-> error (child exit / failed stop)
start / restart recover from stopped or error
```

- Commands validated against a strict schema (no command strings executed);
  duplicate `command_id`s are answered idempotently.
- Acks report the resulting state (`stop` -> `state: stopped`).
- `--motion-triggered` mode: the child stays alive as the motion monitor while
  the camera publisher is started/stopped per session policy.

### Motion-Triggered Sessions (`aiot/streaming/edge_session.py`)

State flow `monitoring -> starting -> awaiting_face -> streaming -> stopping`.
First face must arrive within 30 s; valid `face_presence` renews a 120 s lease.
`MotionDetector` (MOG2) owns the camera only while idle and releases it before
FFmpeg starts.

## 5. Cloud Recognition

- `app.py`: reconnecting MediaPipe preview (cross-platform).
- `recognize_stream.py` (Windows AMD64 only): latest-frame capture thread +
  background recognition worker + display loop. InsightFace `buffalo_l`:
  SCRFD detects all faces, `FaceTracker` assigns by `track_id`, ArcFace embeds
  only scheduler-selected tracks (default budget: 1 embedding/cycle) using
  matching five-point landmarks — never `FaceAnalysis.get()` in the realtime
  path. FAISS `IndexFlatIP` over normalized embeddings = cosine similarity;
  `FaceRecognizer` + `FaceTracker` confirmation/TTL rules.
- `build_index.py` builds `database/faces.index` + `metadata.json` (one-to-one)
  from `dataset/<person>/`.
- `--require-gpu` fails unless both SCRFD and ArcFace use CUDA.
- Emits `recognition/result` and `error/pipeline/<device>` to MQTT.

## 6. Audit And Security

- `scripts/run_mqtt_logger.py` persists `recognition/result`,
  `motion/detected`, `error/#`, and `control/ack/+` to
  `database/audit_log.sqlite3` with schema validation, RTSP credential
  redaction, payload-size limits, and retention (30 days / 100k records).
  `system/status/*` is not persisted. Reads go through `query_audit_events()`
  (read-only per call); the logger process owns the write connection.
- Credentials come from environment variables (`--mqtt-password-env`); secrets
  and raw RTSP URLs are never logged.
- Tool setup (`scripts/setup_tools.py`) uses pinned downloads, checksums, and
  archive path-traversal protection; the Mosquitto configs and systemd unit are
  LF-enforced via `.gitattributes` (CRLF breaks ACL pattern matching and
  systemd).

## 7. Web Dashboard (`aiot/dashboard/`, `scripts/run_dashboard.py`)

A FastAPI viewer-plus-controller for the guard role, running on the cloud tier
next to the broker and audit logger:

- Video: the browser plays MediaMTX WebRTC directly via WHEP (`--video-url`,
  default `http://127.0.0.1:8889`, path `camera`). Recognition boxes are drawn
  as a Canvas overlay from realtime `recognition/result` events — the video is
  never re-encoded.
- Timeline: live events (recognition, motion, error, acks) over WebSocket
  `/ws`, plus history and filters over `GET /api/events` reading the audit DB;
  `control/ack/+` entries show command history with results.
- Control: `POST /api/control` validates `action` against the whitelist
  (`status`, `start`, `stop`, `restart`) and publishes a device-scoped
  `control/stream/<device>` command with a generated `command_id`; acks arrive
  live over the WebSocket.
- Wanted persons: `aiot/recognition/wanted.py` + `config/wanted.json` is the
  single source of truth shared with `recognize_stream.py`. A wanted
  `identity_confirmed` event draws a red box and plays a short synthesized
  alarm (8 s TTL, 30 s per-person cooldown).
- Security posture: binds `127.0.0.1` by default; broker credentials come from
  environment variables and are never embedded in the frontend; the
  `aiot-dashboard` broker principal has read access to events, status, and
  acks plus write access to `control/stream/+`.

## 8. Current Status Summary

- Gate 1 (profile-based edge deployment) and Gate 2 (MQTT edge control) are
  implemented and unit-tested. Gate 3 (web dashboard: WebRTC video, wanted
  alarms, audit timeline, edge control) is implemented and unit-tested
  (250 tests; 7 skips). The local end-to-end demo sequence is verified
  (`docs/RUNBOOK.md` section 9).
- Pending hardware evidence: Pi `rpi-csi` + systemd boot recovery re-validation,
  `recognize_stream.py` publishing real `recognition/result` in the same
  sequence, and a browser WebRTC session against the LAN publisher.
  Calibration/benchmarks were intentionally deferred to close the project.
  See `BACKLOG.md`.

## 9. Related Documents

- `RUNBOOK.md` — how to deploy and demo everything.
- `plans/IMPLEMENTATION_REVIEW.md` — gaps vs. this architecture.
- `plans/RECOGNITION_OPTIMIZATION_PLAN.md` — recognition pipeline contract.
- `plans/MOTION_TRIGGERED_STREAM_STRATEGY.md` — session protocol.
- `../AGENTS.md` — developer invariants.
