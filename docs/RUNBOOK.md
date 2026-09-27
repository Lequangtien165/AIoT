# AIoT End-to-End Operations Runbook

Single source of truth for deploying and operating the project across every role:
edge publishers (Windows/macOS/Linux/Pi), the cloud recognition laptop, the MQTT
broker, the controller, and the audit logger. Commands run from the repository
root unless stated otherwise. Expected outputs below were verified on
2026-08-08 with a Windows AMD64 cloud laptop and Docker Mosquitto. For the
complete flag reference of every command, see `docs/CLI_REFERENCE.md`.

## Role Matrix

| Role                      | Runs on                                                       | Software                                       |
| ------------------------- | ------------------------------------------------------------- | ---------------------------------------------- |
| Edge publisher            | Windows AMD64, macOS Apple Silicon, Linux ARM64, Raspberry Pi | `stream_server.py` + pinned tools              |
| Edge agent (MQTT)         | any edge host with a broker                                   | `scripts/run_edge_agent.py`                    |
| Broker                    | Docker host (localhost only, or LAN with TLS)                 | Mosquitto 2.0                                  |
| Controller                | any host with the repo                                        | `mosquitto_sub` or a small paho script         |
| Audit logger              | broker host or cloud                                          | `scripts/run_mqtt_logger.py`                   |
| Cloud consumer            | Windows AMD64 (CUDA) or macOS Apple Silicon (CoreML) | `app.py`, `recognize_stream.py`                |
| Dashboard (guard console) | broker host or cloud                                          | `scripts/run_dashboard.py` (FastAPI) + browser |

Profiles: `dshow` (Windows), `avfoundation` (macOS), `v4l2` (Linux, USB), and
`rpi-csi` (Raspberry Pi CSI, direct MediaMTX publishing without FFmpeg). The
profile is auto-detected except `rpi-csi`, which must be explicit.

## 1. Fresh Setup (any role)

```powershell
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1 ; macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/setup_tools.py          # pinned FFmpeg + MediaMTX (Windows), MediaMTX (macOS/Linux ARM64)
python -m pip install paho-mqtt        # MQTT control plane
```

- macOS: `brew install python@3.12 ffmpeg`; create the venv with `python3.12`;
  grant camera access in System Settings > Privacy.
- macOS cloud recognition additionally (macOS 14+ Apple Silicon, Python 3.12):
  - `pip install -r requirements-recognition-macos.txt`
  - `pip install --no-deps insightface==1.0.1`
  - `pip check` must report only InsightFace's `opencv-python` requirement as
    unsatisfied (expected with `--no-deps`, which protects
    `opencv-contrib-python`); no other conflicts, and
    `python -c "import onnxruntime as ort; print(ort.get_available_providers())"`
    must list `CoreMLExecutionProvider`.
- Linux ARM64: `sudo apt install -y ffmpeg v4l-utils`.
- Raspberry Pi: 64-bit Bookworm, `sudo apt install -y ffmpeg v4l-utils rpicam-apps`,
  `sudo usermod -aG video "$USER"`, enable the camera in `raspi-config`.
- Windows cloud recognition additionally: `requirements-recognition-windows.txt`
  - `pip install --no-deps insightface==1.0.1` (dependency set unchanged).

## 2. Broker (Role: Broker Host)

```powershell
docker compose up -d mosquitto
docker compose ps        # expect aiot-mosquitto Up, 127.0.0.1:1883->1883
```

Local plaintext broker binds `127.0.0.1:1883` only; LAN clients must use the TLS
profile on `8883` (see README "MQTT Over LAN With TLS"). The TLS profile
requires a separate ignored `config/mosquitto/passwords` file with unique
Mosquitto password hashes and binds to localhost unless `AIOT_MQTT_BIND_HOST`
is set to the broker's LAN IP.

## 2b. Full Pipeline Over the LAN With TLS

Run the complete pipeline across separate hosts (cloud laptop + edge) over a
trusted LAN using the TLS broker profile. Plaintext `1883` stays bound to
`127.0.0.1`; every LAN client connects with `--mqtt-port 8883` and
`--mqtt-ca-cert`.

### 2b.1 One-time certificates (cloud laptop, broker host)

Generate a self-signed CA + server certificate in Git Bash (MSYS) so the SAN is
passed through `MSYS_NO_PATHCONV` correctly. Replace `BROKER_HOSTNAME` and
`BROKER_LAN_IP` with the exact names/IPs the clients use to reach the broker:

```bash
MSYS_NO_PATHCONV=1 openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout config/mosquitto/certs/server.key \
  -out config/mosquitto/certs/server.crt \
  -days 365 -subj "/CN=BROKER_HOSTNAME" \
  -addext "subjectAltName=DNS:BROKER_HOSTNAME,IP:BROKER_LAN_IP"
cp config/mosquitto/certs/server.crt config/mosquitto/certs/ca.crt
```

The SAN must include every address a client uses: `IP:192.168.1.20` if the Pi
connects to that IP, `DNS:aiot-cloud.local` if it uses the hostname. Then start
the TLS broker and open inbound TCP `8883` on the Private-network firewall:

```powershell
docker compose --profile tls up -d mosquitto-tls
docker compose --profile tls ps   # aiot-mosquitto-tls Up, 127.0.0.1:8883->8883 by default
```

### 2b.2 Copy the CA to each edge client

Only the CA is public. Copy `config/mosquitto/certs/ca.crt` to the Pi, for
example:

```bash
scp <WINDOWS_USER>@<BROKER_LAN_IP>:<REPO>\config\mosquitto\certs\ca.crt ~/aiot-certs/ca.crt
```

Verify the Pi can open a TLS session before starting the pipeline:

```bash
mosquitto_sub -h <BROKER_LAN_IP> -p 8883 --cafile ~/aiot-certs/ca.crt \
  -u aiot-edge -P "$AIOT_EDGE_PASSWORD" -t 'control/stream/pi4-edge-01' -d
```

A successful TLS handshake plus `SUBACK` means the certificate SAN, firewall,
broker container (`docker compose --profile tls ps`), and credentials are all
correct; otherwise check each in that order.

### 2b.3 Edge publisher (Pi) with TLS

```bash
export AIOT_EDGE_PASSWORD='<edge-password>'
python stream_server.py \
  --device /dev/video0 \
  --mqtt-host <BROKER_LAN_IP> \
  --mqtt-port 8883 \
  --mqtt-ca-cert ~/aiot-certs/ca.crt \
  --mqtt-client-id pi4-edge-01 \
  --mqtt-username aiot-edge \
  --mqtt-password-env AIOT_EDGE_PASSWORD
```

Expected: `[MQTT] connected`, then the retained `system/status/pi4-edge-01`
reports `state=streaming`. Feed the RTSP relay to the recognizer too:

```
rtsp://<EDGE_LAN_IP>:8554/camera
```

For full dashboard control (start/stop/restart with acks, retained status,
heartbeat, crash respawn) run the persistent edge agent instead of the raw
publisher: the agent supervises `stream_server.py --no-mqtt` as a child, so a
dashboard `stop` actually kills and a later `restart` respawns the publisher —
the raw `stream_server.py` above can only stop itself and then exits for good.

```bash
export AIOT_EDGE_PASSWORD='<edge-password>'
python scripts/run_edge_agent.py \
  --device /dev/video0 \
  --mqtt-host <BROKER_LAN_IP> \
  --mqtt-port 8883 \
  --mqtt-ca-cert ~/aiot-certs/ca.crt \
  --mqtt-client-id pi4-edge-01 \
  --mqtt-username aiot-edge \
  --mqtt-password-env AIOT_EDGE_PASSWORD \
  --heartbeat-interval 5
```

Motion-triggered sessions are opt-in and work on any FFmpeg profile
(`v4l2`/`dshow`/`avfoundation`); they are rejected with `rpi-csi` because
MediaMTX owns the CSI camera through libcamera:

```bash
python scripts/run_edge_agent.py \
  --device /dev/video0 \
  --motion-triggered \
  --mqtt-host <BROKER_LAN_IP> \
  --mqtt-port 8883 \
  --mqtt-ca-cert ~/aiot-certs/ca.crt \
  --mqtt-client-id pi4-edge-01 \
  --mqtt-username aiot-edge \
  --mqtt-password-env AIOT_EDGE_PASSWORD \
  --face-discovery-timeout 30 \
  --face-keepalive-timeout 120 \
  --heartbeat-interval 5 \
  --motion-device 0
```

`--motion-device` defaults to `--device`; on Windows/macOS it must be an OpenCV
camera index. The agent only waits for the RTSP port in motion mode, because
the stream is off while idle and starts on the first detected motion.

The agent is the sole MQTT client for its publisher child: it relays
`motion/detected` active/clear events and validates then forwards cloud
`face_presence` leases. Do not add `--no-mqtt` or run a second publisher beside
the agent.

### 2b.4 Cloud recognition, logger, dashboard (cloud laptop)

Run each in its own terminal. Every component uses the same
`--mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 --mqtt-ca-cert ...` and unique
credentials from the ACL (`aiot-recognition`, `aiot-logger`, `aiot-dashboard`).

```powershell
# Recognition pipeline (GPU)
$env:AIOT_MQTT_PASSWORD='<recognition-password>'
python recognize_stream.py `
  --source "rtsp://<EDGE_LAN_IP>:8554/camera" `
  --require-gpu `
  --no-mirror `
  --snapshot-dir .\snapshots `
  --edge-triggered-session --face-presence-interval 15 `
  --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 `
  --mqtt-ca-cert config\mosquitto\certs\ca.crt `
  --mqtt-client-id aiot-recognition --source-device-id pi4-edge-01 `
  --mqtt-username aiot-recognition --mqtt-password-env AIOT_MQTT_PASSWORD
```

`--no-mirror` keeps the published bounding boxes in the same (unmirrored) space
as the dashboard video; `--snapshot-dir .\snapshots` must match the dashboard's
`--snapshot-dir` so event-drawer snapshots resolve.

On a macOS Apple Silicon cloud laptop (macOS 14+), the same pipeline runs from
Bash with the CoreML accelerator:

```bash
# Recognition pipeline (CoreML)
export AIOT_MQTT_PASSWORD='<recognition-password>'
python recognize_stream.py \
  --source "rtsp://<EDGE_LAN_IP>:8554/camera" \
  --require-gpu \
  --no-mirror \
  --snapshot-dir ./snapshots \
  --edge-triggered-session --face-presence-interval 15 \
  --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 \
  --mqtt-ca-cert config/mosquitto/certs/ca.crt \
  --mqtt-client-id aiot-recognition --source-device-id pi4-edge-01 \
  --mqtt-username aiot-recognition --mqtt-password-env AIOT_MQTT_PASSWORD
```

Expected provider logs on macOS:

```text
SCRFD providers: CoreMLExecutionProvider, CPUExecutionProvider
ArcFace providers: CoreMLExecutionProvider, CPUExecutionProvider
CoreMLExecutionProvider active
```

`--require-gpu` succeeds only when both sessions bind CoreML. That binding does
not mean every operator runs on the GPU: `MLComputeUnits=ALL` lets CoreML
schedule each operator on the GPU, Neural Engine, or CPU. Distinguish a missing
provider from a model fallback: if `ort.get_available_providers()` lacks
`CoreMLExecutionProvider`, startup prints `CPU only` and the environment is
broken (see README "macOS Recognition Setup"); if it is listed but a session
reports only CPU, startup prints
`CoreMLExecutionProvider requested but unavailable, using CPU` and the model
fell back — rerun with `--require-gpu` and read the fail-fast diagnostic.

```powershell
# Audit logger
$env:AIOT_MQTT_PASSWORD='<logger-password>'
python scripts\run_mqtt_logger.py `
  --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 `
  --mqtt-ca-cert config\mosquitto\certs\ca.crt `
  --mqtt-username aiot-logger --mqtt-password-env AIOT_MQTT_PASSWORD
```

```powershell
# Dashboard stays on loopback; use an SSH tunnel for remote access.
$env:AIOT_MQTT_PASSWORD='<dashboard-password>'
python scripts\run_dashboard.py `
  --host 127.0.0.1 --port 8080 `
  --video-url http://<MEDIAMTX_HOST>:8889 `
  --video-device-id pi4-edge-01 `
  --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 `
  --mqtt-ca-cert config\mosquitto\certs\ca.crt `
  --mqtt-client-id aiot-dashboard `
  --mqtt-username aiot-dashboard --mqtt-password-env AIOT_MQTT_PASSWORD `
  --snapshot-dir .\snapshots
```

The dashboard has no application authentication; keep it bound to loopback.
From a remote client, use `ssh -L 8080:127.0.0.1:8080 <USER>@<LAPTOP_LAN_IP>`
and open `http://127.0.0.1:8080`. Pass `--video-url` the
MediaMTX WHEP endpoint that hosts the live stream (`http://<PI_IP>:8889` at the
edge, or `<INTERNAL_MTX_HOST>:8889` if MediaMTX runs on the cloud).

## 3. Edge Publisher (Role: Edge Publisher)

List cameras, then publish. `--profile` is optional except for `rpi-csi`.

```powershell
python stream_server.py --list-devices
python stream_server.py --device "Integrated Camera"      # Windows (dshow)
```

```bash
python stream_server.py --profile rpi-csi                 # Pi CSI (no --device)
```

Expected: `Publishing webcam at rtsp://127.0.0.1:8554/camera (profile: dshow)`.
Preflight runs first and prints any missing tool, camera, or port problem with
the install command to fix it; exit code 1 on failure.

## 4. Edge Agent (Role: Edge Publisher, MQTT control)

Supervises `stream_server.py --no-mqtt` as a child and owns the publisher
process tree. `--device` is required for FFmpeg profiles and ignored by
`rpi-csi`. `--motion-triggered` is rejected with `rpi-csi`. The example below
uses the local plaintext broker; see [2b.3](#2b3-edge-publisher-pi-with-tls)
for the same agent over the LAN TLS profile on `8883`.

```powershell
$env:AIOT_EDGE_PASSWORD='edge-secret'
python scripts\run_edge_agent.py `
  --device "Rapoo camera" `
  --profile dshow `
  --mqtt-host 127.0.0.1 --mqtt-port 1883 `
  --mqtt-client-id pi4-edge-01 `
  --mqtt-username aiot-edge --mqtt-password-env AIOT_EDGE_PASSWORD `
  --heartbeat-interval 1
```

Expected: `[MQTT] connected`, then the child starts MediaMTX, FFmpeg publishes,
and the agent reports `state=streaming` with `rtsp_stream_active: true` in the
retained status. Verify from any host:

```powershell
& 'tools\ffmpeg\bin\ffprobe.exe' -v error -rtsp_transport tcp `
  -show_entries stream=codec_name,width,height,r_frame_rate -of json `
  rtsp://<EDGE_IP>:8554/camera
# expect H.264, 1280, 720, 30/1
```

## 5. Controller (Role: Controller)

The controller may publish `status`, `stop`, `start`, and `restart` to
`control/stream/<device_id>` and reads acks on `control/ack/<device_id>` and the
retained status on `system/status/<device_id>`. Acks carry `result`,
`state` (current edge state), and `command_id` echo; duplicate `command_id`s are
answered idempotently.

```powershell
docker compose exec mosquitto mosquitto_sub -h 127.0.0.1 -p 1883 `
  -u aiot-controller -P controller-secret -t control/ack/pi4-edge-01 -v
```

Send `stop` then `start` with a paho script (or `mosquitto_pub` with the schema
below). Verified ack sequence:

```
ACK status: result=succeeded state=streaming
ACK stop:   result=succeeded state=stopped
ACK start:  result=succeeded state=streaming
```

The retained `system/status/pi4-edge-01` reports `state` plus metrics
(`runtime_alive`, `rtsp_healthy`, `rtsp_stream_active`, `mode`). After `stop`,
`tasklist | findstr mediamtx` / `pgrep -a mediamtx` must show no leftover
publisher processes.

## 6. Audit Logger (Role: Audit Logger)

Persists `recognition/result`, `motion/detected`, `error/#`, and `control/ack/+`
to `database/audit_log.sqlite3`, validating schemas, redacting sensitive values,
and rejecting everything else. Run it on the broker host or the cloud:

```powershell
$env:AIOT_LOGGER_PASSWORD='logger-secret'
python scripts\run_mqtt_logger.py `
  --mqtt-host 127.0.0.1 --mqtt-port 1883 `
  --client-id audit-logger-01 `
  --mqtt-username aiot-logger --mqtt-password-env AIOT_LOGGER_PASSWORD
```

Verify after events arrive:

```powershell
python -c "import sqlite3; db=sqlite3.connect('database/audit_log.sqlite3'); print(db.execute('SELECT topic, COUNT(*) FROM mqtt_audit_events GROUP BY topic').fetchall())"
```

`system/status/*` and `control/stream/*` must never appear (they are not audit
topics). Command acknowledgements on `control/ack/+` are persisted, so the
timeline records who issued which command and the resulting state.

## 7. Web Dashboard (Role: Dashboard / Guard Console)

A browser console combining live WebRTC video with a recognition box overlay,
a realtime + historical event timeline, wanted-person alarms, and edge control
buttons. Prerequisites: broker (section 2), a publisher (section 3 or 4), the
audit logger (section 6), and the recognition pipeline publishing
`recognition/result` (section 8 below). MediaMTX must run with a WebRTC-enabled
config (both `config/mediamtx.yml` and `config/mediamtx-rpi.yml` enable
`webrtc: true` on `:8889`, UDP mux `8189`).

```powershell
python -m pip install -r requirements-dashboard.txt
$env:AIOT_DASHBOARD_PASSWORD='dashboard-secret'
python scripts\run_dashboard.py `
  --mqtt-host 127.0.0.1 --mqtt-port 1883 `
  --mqtt-client-id aiot-dashboard `
  --mqtt-username aiot-dashboard --mqtt-password-env AIOT_DASHBOARD_PASSWORD
```

Open `http://127.0.0.1:8080`. Expected: live video in the left panel, edge
status chips, timeline entries as events arrive, and working control buttons
after typing the device id (e.g. `pi4-edge-01`) — `Stop` then `Start` must
produce command entries with `result=succeeded` and the resulting state.

- Wanted alarms: a matched label matching `config/wanted.json` (default: IDOC
  `A#####` labels) turns the box red, beeps, and flashes the banner for 8 s
  with a 30 s per-person cooldown. To demo without a wanted person, temporarily
  add the enrolled name to `config/wanted.json` and restart the dashboard.
- Remote publisher: pass `--video-url http://<MEDIAMTX_HOST>:8889` when
  MediaMTX runs elsewhere (e.g. the Pi).
- Snapshot images in the event drawer require `--snapshot-dir` pointing at the
  directory `recognize_stream.py --snapshot-dir` writes to.
- The dashboard has no application authentication; keep it bound to
  `127.0.0.1`. For remote access, use an SSH tunnel:
  `ssh -L 8080:127.0.0.1:8080 <USER>@<LAPTOP_LAN_IP>`.

## 8. Cloud Consumer (Role: Cloud Consumer)

```powershell
python app.py --source "rtsp://<EDGE_IP>:8554/camera"          # MediaPipe preview
python build_index.py                                          # rebuild after dataset changes
$env:AIOT_MQTT_PASSWORD='<recognition-password>'
python recognize_stream.py `
  --source "rtsp://<EDGE_IP>:8554/camera" `
  --require-gpu `
  --no-mirror `
  --snapshot-dir .\snapshots `
  --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 `
  --mqtt-ca-cert config\mosquitto\certs\ca.crt `
  --mqtt-client-id aiot-recognition --source-device-id pi4-edge-01 `
  --mqtt-username aiot-recognition --mqtt-password-env AIOT_MQTT_PASSWORD
```

`--no-mirror` publishes boxes in the same unmirrored space as the dashboard
video; drop it only if the dashboard mirrors the video instead (CSS flip).

On macOS Apple Silicon, the same flow uses Bash; `--require-gpu` then demands
CoreML on both models:

```bash
python app.py --source "rtsp://<EDGE_IP>:8554/camera"          # MediaPipe preview
python build_index.py                                          # rebuild after dataset changes
export AIOT_MQTT_PASSWORD='<recognition-password>'
python recognize_stream.py \
  --source "rtsp://<EDGE_IP>:8554/camera" \
  --require-gpu \
  --no-mirror \
  --snapshot-dir ./snapshots \
  --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 \
  --mqtt-ca-cert config/mosquitto/certs/ca.crt \
  --mqtt-client-id aiot-recognition --source-device-id pi4-edge-01 \
  --mqtt-username aiot-recognition --mqtt-password-env AIOT_MQTT_PASSWORD
```

Expected startup logs show `CoreMLExecutionProvider` for both SCRFD and ArcFace
before `CPUExecutionProvider`, and `CoreMLExecutionProvider active`. A
CoreML-bound session may still run individual operators on CPU through
`MLComputeUnits=ALL`; that is by design and is not a fallback. If CoreML is
listed in `ort.get_available_providers()` but the models report CPU only, the
session fell back — check `FaceEngine.provider_status.warning` and rerun with
`--require-gpu` for the fail-fast exit.

`recognize_stream.py` publishes `recognition/result` (schema: `frame_id`,
`result_id`, `tracks`, `events`, `source` redacted) that the audit logger
persists. Consumers reconnect automatically after publisher restarts.

## 9. Raspberry Pi Boot Deployment (Role: Edge Publisher, Pi)

`deploy/systemd/aiot-rpi-csi.service` starts `stream_server.py --profile rpi-csi
--no-mqtt` at boot with `Restart=always`:

```bash
sudo cp deploy/systemd/aiot-rpi-csi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aiot-rpi-csi
journalctl -u aiot-rpi-csi -f
```

The unit runs as `pi:video`; the project must live at `/opt/aiot` (edit the unit
otherwise). Do not run the systemd unit and `run_edge_agent.py` at the same time

- each supervises its own publisher. Recovery check: reboot, then ffprobe
  `rtsp://<PI_IP>:8554/camera`; the stream must return without manual action.

## 10. Demo Sequence (verified 2026-08-08)

1. Broker up (section 2).
2. Agent up with a real camera (section 4) -> retained status `streaming`.
3. `ffprobe` confirms H.264 1280x720 @ 30 FPS.
4. Audit logger up (section 6).
5. Controller: `status` -> `stop` -> `start` -> `status`; acks carry states
   `streaming` / `stopped` / `streaming`; no leftover `mediamtx`/`ffmpeg` after
   `stop`; `ffprobe` reconnects after `start`.
6. Publish a conformant `recognition/result` (or run `recognize_stream.py`) and
   verify the audit DB row; invalid payloads are rejected with a log line.
7. Dashboard up (section 7): browser shows WebRTC video, box overlay, and
   command entries in the timeline after a `Stop`/`Start` from the UI; a
   wanted-label match triggers the alarm banner + beep.
8. Shut down: controller `stop`, then `Ctrl+C` on the agent (terminates the
   process tree), `docker compose down`.

## 11. Troubleshooting

| Symptom                                                    | Likely cause                                 | Fix                                                                                                                                                                                                             |
| ---------------------------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Preflight: "FFmpeg was not found"                          | tools missing on this profile                | `python scripts/setup_tools.py` (or brew/apt, see section 1)                                                                                                                                                    |
| Preflight: "camera enumeration failed" / "no cameras" (Pi) | CSI cable or raspi-config camera off         | `sudo raspi-config` > Interface Options > Camera                                                                                                                                                                |
| Preflight: "RTSP port already in use"                      | another publisher/player holds 8554          | stop it, or check `tasklist`/`pgrep` for mediamtx                                                                                                                                                               |
| Controller sees no acks                                    | ACL mismatch or wrong device_id              | check `config/mosquitto/aclfile` (LF line endings), same `--mqtt-client-id`                                                                                                                                     |
| `recognize_stream.py` not recognized on GPU                | missing `--require-gpu` flag                 | see README "Windows Recognition Setup" / "macOS Recognition Setup"                                                                                                                                              |
| Recognition reports CPU only on macOS                       | CoreML EP missing or model fallback          | verify `ort.get_available_providers()` lists `CoreMLExecutionProvider` (README "macOS Recognition Setup"); each process recompiles models for CoreML at session creation (no persistent cache), so startup is slower; `--require-gpu` fails fast with the provider name |
| Agent publish rejected "No matching subscribers"           | controller not subscribed to `control/ack/+` | subscribe first, then send commands                                                                                                                                                                             |
| Mosquitto ACL silently matching nothing                    | CRLF line endings in `config/mosquitto/*`    | keep LF (`.gitattributes` enforces)                                                                                                                                                                             |
| Dashboard video stuck on "Video unavailable"               | MediaMTX WebRTC not reachable                | verify `webrtc: true` in the config MediaMTX actually uses; check `--video-url` (Pi: `http://<PI_IP>:8889`); open UDP `8189`; on multi-NIC hosts set `webrtcAdditionalHosts: [<LAN_IP>]` in the MediaMTX config |
| Dashboard control returns "MQTT broker is not connected"   | broker down or bad dashboard credentials     | check `docker compose ps`; verify `aiot-dashboard` exists in `passwords.example`/ACL and the password env var is set                                                                                            |
| Timeline shows no recognition events                       | recognition pipeline not publishing          | run `recognize_stream.py` with `--mqtt-host`; check `mosquitto_sub -u aiot-logger ... -t recognition/result -v`                                                                                                 |
