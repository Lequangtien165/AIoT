# AIoT CLI Reference

> **Status**: Current (2026-08-09). The flag tables in this document are
> generated from the argparse definitions — do not edit the generated section
> by hand (see "Keeping This Document Current").
> Part of the [documentation hub](README.md).

Every user-facing command line interface in this repository. The authoritative
source for each flag is the module's own `build_parser()` (run
`python <module> --help`); the tables below are generated from it so they
cannot drift. All commands run from the repository root.

<!-- CLI-REF:AUTO-START -->

## Commands At A Glance

| Command | Purpose | Platform | Flags | Required |
|---|---|---|---|---|
| `python app.py` | Reconnecting MediaPipe face-detection preview of an RTSP stream. | Windows AMD64 and macOS Apple Silicon (needs the BlazeFace model) | 3 flags | 0 |
| `python stream_server.py` | Publish a webcam to a MediaMTX RTSP stream; owns MediaMTX and optionally FFmpeg. | Windows, macOS, Linux ARM64 (profile auto-detected; rpi-csi must be explicit) | 25 flags | 0 |
| `python recognize_stream.py` | Realtime InsightFace + FAISS recognition of an RTSP stream; publishes recognition/result over MQTT. | Windows AMD64 (CUDA) and macOS Apple Silicon (CoreML) | 28 flags | 0 |
| `python recognize_image.py IMAGE` | One-shot image recognition against the FAISS enrollment index. | Windows AMD64 (CUDA); macOS Apple Silicon (CoreML, pending validation) | 2 flags + 1 positional | 1 |
| `python scripts/run_edge_agent.py` | Persistent MQTT supervisor that owns a stream_server.py publisher child. | Windows, macOS, Linux ARM64 | 23 flags | 2 |
| `python scripts/run_dashboard.py` | Web guard console: WebRTC video, recognition overlay, event timeline, edge control. | Windows, macOS (requires requirements-dashboard.txt) | 14 flags | 0 |
| `python scripts/run_mqtt_logger.py` | Persist recognition/motion/error/ack events to database/audit_log.sqlite3. | Windows, macOS, Linux | 9 flags | 0 |
| `python scripts/setup_tools.py` | Download, verify, and install the pinned FFmpeg and MediaMTX builds. | Windows, macOS Apple Silicon, Linux ARM64 | 1 flag | 0 |

### `python app.py`

Reconnecting MediaPipe face-detection preview of an RTSP stream.

Platform: Windows AMD64 and macOS Apple Silicon (needs the BlazeFace model).

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--source` | str | `rtsp://127.0.0.1:8554/camera` | no | RTSP URL to read (default: rtsp://127.0.0.1:8554/camera). |
| `--confidence` | float | `0.5` | no | Detection confidence from 0 to 1 (default: 0.5). |
| `--reconnect-delay` | float | `2.0` | no | Seconds between RTSP reconnect attempts (default: 2.0). |


### `python stream_server.py`

Publish a webcam to a MediaMTX RTSP stream; owns MediaMTX and optionally FFmpeg.

Platform: Windows, macOS, Linux ARM64 (profile auto-detected; rpi-csi must be explicit).

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--device` | str | — | no | Camera name on Windows, AVFoundation index on macOS, or /dev/videoN on Linux. |
| `--profile` | choice | — | no | Explicit capture/deployment profile. Auto-detected by default: dshow on Windows, avfoundation on macOS, v4l2 on Linux. rpi-csi (Raspberry Pi CSI camera, direct MediaMTX publishing) is never auto-detected because a Raspberry Pi camera can be CSI or USB/V4L2. Choices: `rpi-csi`, `v4l2`, `avfoundation`, `dshow`. |
| `--list-devices` | flag | `false` | no | List available video devices and exit. |
| `--framerate` | int | `30` | no | Requested camera frame rate (default: 30). |
| `--video-size` | str | `1280x720` | no | Requested size (default: 1280x720). |
| `--bitrate` | str | `2M` | no | H.264 bitrate (default: 2M). |
| `--mqtt-host` | str | — | no | MQTT broker host for edge status and control. |
| `--mqtt-port` | int | `1883` | no | MQTT broker port (default: 1883). |
| `--mqtt-client-id` | str | `aiot-edge-publisher` | no | MQTT client/device ID (default: aiot-edge-publisher). |
| `--mqtt-username` | str | — | no | MQTT username. Password is read from --mqtt-password-env. |
| `--mqtt-password-env` | str | — | no | Environment variable containing the MQTT password. |
| `--mqtt-ca-cert` | str | — | no | CA certificate path for TLS MQTT connections. |
| `--no-mqtt` | flag | `false` | no | Disable the publisher MQTT client when controlled by run_edge_agent.py. |
| `--heartbeat-interval` | float | `5.0` | no | Status heartbeat interval in seconds (default: 5.0). |
| `--motion-triggered` | flag | `false` | no | Start RTSP sessions only after significant motion. |
| `--motion-device` | str | — | no | OpenCV camera index/path used while monitoring; defaults to --device. |
| `--motion-width` | int | `320` | no | Motion monitor width (default: 320). |
| `--motion-height` | int | `240` | no | Motion monitor height (default: 240). |
| `--motion-fps` | float | `5.0` | no | Motion monitor frame rate (default: 5.0). |
| `--motion-area-threshold` | float | `0.02` | no | Changed-pixel fraction that counts as motion (default: 0.02). |
| `--motion-window-size` | int | `5` | no | Motion decision window in frames (default: 5). |
| `--motion-trigger-frames` | int | `3` | no | Motion frames required within the window (default: 3). |
| `--motion-warmup` | float | `2.0` | no | Seconds of background calibration before monitoring (default: 2.0). |
| `--face-discovery-timeout` | float | `30.0` | no | Seconds to wait for the first face presence (default: 30.0). |
| `--face-keepalive-timeout` | float | `120.0` | no | Face-presence session lease in seconds (default: 120.0). |


### `python recognize_stream.py`

Realtime InsightFace + FAISS recognition of an RTSP stream; publishes recognition/result over MQTT.

Platform: Windows AMD64 (CUDA) and macOS Apple Silicon (CoreML).

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--source` | str | `rtsp://127.0.0.1:8554/camera` | no | RTSP URL (default: rtsp://127.0.0.1:8554/camera). |
| `--threshold` | float | `0.45` | no | Cosine similarity threshold (default: 0.45). |
| `--top-k` | int | `5` | no | Number of FAISS vectors to retrieve (default: 5). |
| `--recognition-fps` | float | `6.0` | no | SCRFD detection/tracking cycles per second (default: 6.0). |
| `--max-embeddings-per-cycle` | int | `1` | no | Maximum ArcFace embeddings per SCRFD detection cycle (default: 1). |
| `--track-iou-threshold` | float | `0.3` | no | IoU threshold to associate a track with a detection (default: 0.30). |
| `--track-ttl-frames` | int | `8` | no | Missed frames before a track expires (default: 8). |
| `--min-track-age-frames` | int | `3` | no | Visible frames before a track can be recognized (default: 3). |
| `--min-face-size` | int | `80` | no | Minimum face box side in pixels for recognition (default: 80). |
| `--matched-recognition-interval-frames` | int | `30` | no | Frames between re-embeddings of a matched track (default: 30). |
| `--embedding-change-threshold` | float | `0.6` | no | Cosine similarity below which a matched track's face is treated as changed (default: 0.6). |
| `--det-size` | int | `640` | no | InsightFace detector size (default: 640). |
| `--record-video` | str | — | no | File or directory for annotated video output. |
| `--snapshot-dir` | str | — | no | Directory for snapshots on MATCH or identity change. |
| `--no-mirror` | flag | `false` | no | Do not mirror the preview; keep published boxes in the raw video space. |
| `--profile` | flag | `false` | no | Print capture, display, and recognition profiling. Not the camera profile flag used by stream_server.py. |
| `--require-gpu` | flag | `false` | no | Exit if the platform accelerator (CUDA on Windows, CoreML on macOS) is not active. |
| `--reconnect-delay` | float | `2.0` | no | Seconds between RTSP reconnect attempts (default: 2.0). |
| `--mqtt-host` | str | — | no | MQTT broker host for recognition/result events. |
| `--mqtt-port` | int | `1883` | no | MQTT broker port (default: 1883). |
| `--mqtt-client-id` | str | `aiot-recognition` | no | MQTT client ID (default: aiot-recognition). |
| `--mqtt-username` | str | — | no | MQTT username. Password is read from --mqtt-password-env. |
| `--mqtt-password-env` | str | — | no | Environment variable containing the MQTT password. |
| `--mqtt-ca-cert` | str | — | no | CA certificate path for TLS MQTT connections. |
| `--source-device-id` | str | — | no | Edge device ID for device-scoped pipeline MQTT errors; defaults to --mqtt-client-id. |
| `--edge-triggered-session` | flag | `false` | no | Enable edge-triggered sessions: subscribe to the edge status and publish face presence. |
| `--face-presence-interval` | float | `15.0` | no | Seconds between face-presence lease renewals (default: 15.0). |
| `--wanted-config` | str | — | no | Path to the wanted-person JSON config (default: config/wanted.json). |


### `python recognize_image.py IMAGE`

One-shot image recognition against the FAISS enrollment index.

Platform: Windows AMD64 (CUDA); macOS Apple Silicon (CoreML, pending validation).

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `image` (positional) | Path | — | yes | Path to the image to recognize. |
| `--threshold` | float | `0.45` | no | Cosine similarity threshold. Default: 0.45 |
| `--top-k` | int | `5` | no | Number of nearest vectors to retrieve. |


### `python scripts/run_edge_agent.py`

Persistent MQTT supervisor that owns a stream_server.py publisher child.

Platform: Windows, macOS, Linux ARM64.

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--device` | str | — | no | Camera input; required for FFmpeg-based profiles, ignored by rpi-csi. |
| `--profile` | choice | — | no | Explicit capture/deployment profile; auto-detected by default (dshow on Windows, avfoundation on macOS, v4l2 on Linux). rpi-csi is never auto-detected and requires no --device. Choices: `rpi-csi`, `v4l2`, `avfoundation`, `dshow`. |
| `--motion-triggered` | flag | `false` | no | Start RTSP sessions only after significant motion. |
| `--motion-device` | str | — | no | OpenCV camera index/path used while monitoring; defaults to --device. |
| `--motion-width` | int | `320` | no | Motion monitor width (default: 320). |
| `--motion-height` | int | `240` | no | Motion monitor height (default: 240). |
| `--motion-fps` | float | `5.0` | no | Motion monitor frame rate (default: 5.0). |
| `--motion-area-threshold` | float | `0.02` | no | Changed-pixel fraction that counts as motion (default: 0.02). |
| `--motion-window-size` | int | `5` | no | Motion decision window in frames (default: 5). |
| `--motion-trigger-frames` | int | `3` | no | Motion frames required within the window (default: 3). |
| `--motion-warmup` | float | `2.0` | no | Seconds of background calibration before monitoring (default: 2.0). |
| `--face-discovery-timeout` | float | `30.0` | no | Seconds to wait for the first face presence (default: 30.0). |
| `--face-keepalive-timeout` | float | `120.0` | no | Face-presence session lease in seconds (default: 120.0). |
| `--framerate` | int | `30` | no | Requested camera frame rate (default: 30). |
| `--video-size` | str | `1280x720` | no | Requested size (default: 1280x720). |
| `--bitrate` | str | `2M` | no | H.264 bitrate (default: 2M). |
| `--mqtt-host` | str | — | yes | MQTT broker host (required). |
| `--mqtt-port` | int | `1883` | no | MQTT broker port (default: 1883). |
| `--mqtt-client-id` | str | — | yes | MQTT client/edge device ID (required). |
| `--mqtt-username` | str | — | no | MQTT username. Password is read from --mqtt-password-env. |
| `--mqtt-password-env` | str | — | no | Environment variable containing the MQTT password. |
| `--mqtt-ca-cert` | str | — | no | CA certificate path for TLS MQTT connections. |
| `--heartbeat-interval` | float | `5.0` | no | Status heartbeat interval in seconds (default: 5.0). |


### `python scripts/run_dashboard.py`

Web guard console: WebRTC video, recognition overlay, event timeline, edge control.

Platform: Windows, macOS (requires requirements-dashboard.txt).

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--host` | str | `127.0.0.1` | no | Bind address (default: 127.0.0.1). |
| `--port` | int | `8080` | no | Dashboard HTTP port (default: 8080). |
| `--video-url` | str | `http://127.0.0.1:8889` | no | MediaMTX WebRTC base URL for WHEP (default: http://127.0.0.1:8889). |
| `--video-path` | str | `camera` | no | MediaMTX path to play (default: camera). |
| `--video-device-id` | str | — | no | Edge device ID that owns --video-path; drives WHEP lifecycle from its status. |
| `--mqtt-host` | str | `127.0.0.1` | no | MQTT broker host (default: 127.0.0.1). |
| `--mqtt-port` | int | `1883` | no | MQTT broker port (default: 1883). |
| `--mqtt-client-id` | str | `aiot-dashboard` | no | MQTT client ID (default: aiot-dashboard). |
| `--mqtt-username` | str | — | no | MQTT username. Password is read from --mqtt-password-env. |
| `--mqtt-password-env` | str | — | no | Environment variable containing the MQTT password. |
| `--mqtt-ca-cert` | str | — | no | CA certificate path for TLS MQTT connections. |
| `--audit-db` | str | `database/audit_log.sqlite3` | no | SQLite audit database to read (default: database/audit_log.sqlite3). |
| `--wanted-config` | str | — | no | Path to the wanted-person JSON config (default: config/wanted.json). |
| `--snapshot-dir` | str | — | no | Recognition snapshot directory served at /snapshots/* (optional). |


### `python scripts/run_mqtt_logger.py`

Persist recognition/motion/error/ack events to database/audit_log.sqlite3.

Platform: Windows, macOS, Linux.

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--mqtt-host` | str | `127.0.0.1` | no | MQTT broker host (default: 127.0.0.1). |
| `--mqtt-port` | int | `1883` | no | MQTT broker port (default: 1883). |
| `--client-id` | str | `aiot-audit-logger` | no | MQTT client ID (default: aiot-audit-logger). |
| `--mqtt-username` | str | — | no | MQTT username. Password is read from --mqtt-password-env. |
| `--mqtt-password-env` | str | — | no | Environment variable containing the MQTT password. |
| `--mqtt-ca-cert` | str | — | no | CA certificate path for TLS MQTT connections. |
| `--retention-days` | int | `30` | no | Retention period in days (default: 30). |
| `--max-records` | int | `100000` | no | Maximum stored audit records (default: 100000). |
| `--max-payload-bytes` | int | `16384` | no | Maximum accepted payload size in bytes (default: 16384). |

Flags defined in `aiot/mqtt/audit_logger.py`.


### `python scripts/setup_tools.py`

Download, verify, and install the pinned FFmpeg and MediaMTX builds.

Platform: Windows, macOS Apple Silicon, Linux ARM64.

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--force` | flag | `false` | no | Reinstall tools even when verified. |


<!-- CLI-REF:AUTO-END -->

## Commands Without A Parser

`python build_index.py` takes no CLI arguments. It rebuilds
`database/faces.index` and `database/metadata.json` from `dataset/<person>/`
(plus the IDOC CSV manifests) and must be run again after enrollment changes.

`scripts/run_mqtt_logger.py` is a thin wrapper around
`aiot.mqtt.audit_logger.main()`; its flags are listed under
`python scripts/run_mqtt_logger.py` above.

## Shared Conventions

### MQTT Flags

Six flags are identical across every MQTT-enabled CLI (`stream_server.py`,
`recognize_stream.py`, `scripts/run_edge_agent.py`, `scripts/run_dashboard.py`,
`scripts/run_mqtt_logger.py`):

| Flag | Meaning |
|---|---|
| `--mqtt-host` | Broker host. Required in `run_edge_agent.py`; elsewhere MQTT is disabled when it is absent. |
| `--mqtt-port` | Broker port (default 1883). Use `8883` for the LAN TLS profile. |
| `--mqtt-client-id` | Client ID; doubles as the device identity for status/control topics. The audit logger is the one exception and uses `--client-id` instead. |
| `--mqtt-username` | Broker user from `config/mosquitto/passwords.example` / the ACL. |
| `--mqtt-password-env` | Name of the environment variable holding the password; required whenever `--mqtt-username` is set. |
| `--mqtt-ca-cert` | CA certificate path for TLS connections to the 8883 profile. |

Passwords are never passed on the command line. Set the variable first, for
example `$env:AIOT_MQTT_PASSWORD='...'`, then pass
`--mqtt-password-env AIOT_MQTT_PASSWORD`. Same for the edge, recognition,
logger, and dashboard roles.

### Paths Are Repository-Relative

File and URL paths (`--source`, `--snapshot-dir`, `--audit-db`,
`--wanted-config`, `--mqtt-ca-cert`, `--record-video`) resolve from the
current working directory. Run commands from the repository root so that
relative paths line up across processes.

### The `--profile` Name Collision

`--profile` means two different things:

- In `stream_server.py` and `scripts/run_edge_agent.py` it selects the
  **camera deployment profile** (`dshow`, `v4l2`, `avfoundation`, `rpi-csi`).
- In `recognize_stream.py` it is a boolean that **prints profiling
  statistics**.

Never pass `--profile` to `recognize_stream.py` expecting a camera profile;
the camera choice for recognition comes from the `--source` RTSP URL.

### Edge Agent Forwarding Limits

`scripts/run_edge_agent.py` forwards capture, motion, and session options to
its `stream_server.py --no-mqtt` child: `--device`, `--profile`,
`--framerate`, `--video-size`, `--bitrate`, `--motion-triggered`,
`--motion-device`, all motion tuning flags, and both face-session timeouts.
The agent remains the sole MQTT client and relays motion/session events plus
cloud face-presence leases through an authenticated loopback channel.

## Cross-Process Invariants

| Invariant | Details |
|---|---|
| `--source-device-id` matches the edge device | `recognize_stream.py --source-device-id` must equal the edge's `--mqtt-client-id` so pipeline errors and face-presence leases are device-scoped. |
| `--snapshot-dir` matches between recognizer and dashboard | `recognize_stream.py --snapshot-dir` and `scripts/run_dashboard.py --snapshot-dir` must point at the same directory or the event drawer shows no snapshots. |
| `--no-mirror` aligns boxes with the dashboard video | Recognition mirrors frames before detection by default, so published boxes live in mirrored space. Run with `--no-mirror` (or mirror the video with CSS) or the dashboard overlay is horizontally flipped. |
| `--edge-triggered-session` needs the session plane | Requires `--mqtt-host` and `--source-device-id`; subscribes to `system/status/<device>` and publishes `stream/activity/<device>` face presence. |
| `--wanted-config` is shared | Both `recognize_stream.py` and the dashboard resolve `config/wanted.json` by default; edits require a dashboard restart. |
| `--audit-db` matches the logger | The dashboard reads `database/audit_log.sqlite3` by default, exactly where the audit logger writes. |

## Platform And Capability Matrix

| Capability | Windows AMD64 | macOS Apple Silicon | Linux ARM64 (Pi) |
|---|---|---|---|
| MediaPipe preview (`app.py`) | yes | yes | no |
| Recognition stream (`recognize_stream.py`) | yes (CUDA) | yes (CoreML, CPU fallback) | no |
| Recognition image (`recognize_image.py`) | yes (CUDA) | yes (CoreML, pending validation) | no |
| Publisher (`stream_server.py`) | dshow | avfoundation | v4l2 / rpi-csi |
| Edge agent (`scripts/run_edge_agent.py`) | yes | yes | yes |
| Dashboard / audit logger | yes | yes | yes |
| WebRTC browser output | yes | yes | yes |

## Keeping This Document Current

The generated tables come from the argparse definitions:

```powershell
python scripts/generate_cli_reference.py
```

`tests/test_cli_reference.py` fails when the committed reference is stale, so
run the generator after adding, renaming, or changing the default of any flag
and commit both files together. The curated sections (shared conventions,
cross-process invariants, platform matrix) are written by hand and reviewed
whenever CLI behavior changes.
