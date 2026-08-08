# AIoT End-to-End Operations Runbook

Single source of truth for deploying and operating the project across every role:
edge publishers (Windows/macOS/Linux/Pi), the cloud recognition laptop, the MQTT
broker, the controller, and the audit logger. Commands run from the repository
root unless stated otherwise. Expected outputs below were verified on
2026-08-08 with a Windows AMD64 cloud laptop and Docker Mosquitto.

## Role Matrix

| Role | Runs on | Software |
|---|---|---|
| Edge publisher | Windows AMD64, macOS Apple Silicon, Linux ARM64, Raspberry Pi | `stream_server.py` + pinned tools |
| Edge agent (MQTT) | any edge host with a broker | `scripts/run_edge_agent.py` |
| Broker | Docker host (localhost only, or LAN with TLS) | Mosquitto 2.0 |
| Controller | any host with the repo | `mosquitto_sub` or a small paho script |
| Audit logger | broker host or cloud | `scripts/run_mqtt_logger.py` |
| Cloud consumer | Windows AMD64 with GPU | `app.py`, `recognize_stream.py` |
| Dashboard (guard console) | broker host or cloud | `scripts/run_dashboard.py` (FastAPI) + browser |

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

- macOS: `brew install ffmpeg`; grant camera access in System Settings > Privacy.
- Linux ARM64: `sudo apt install -y ffmpeg v4l-utils`.
- Raspberry Pi: 64-bit Bookworm, `sudo apt install -y ffmpeg v4l-utils rpicam-apps`,
  `sudo usermod -aG video "$USER"`, enable the camera in `raspi-config`.
- Windows cloud recognition additionally: `requirements-recognition-windows.txt`
  + `pip install --no-deps insightface==1.0.1`.

## 2. Broker (Role: Broker Host)

```powershell
docker compose up -d mosquitto
docker compose ps        # expect aiot-mosquitto Up, 127.0.0.1:1883->1883
```

Local plaintext broker binds `127.0.0.1:1883` only; LAN clients must use the TLS
profile on `8883` (see README "MQTT Over LAN With TLS"). Demo credentials are
generated from `config/mosquitto/passwords.example` by compose.

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
`rpi-csi`. `--motion-triggered` is rejected with `rpi-csi`.

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
`recognition/result` (section 7 below). MediaMTX must run with a WebRTC-enabled
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
- The dashboard binds `127.0.0.1` by default; on the LAN use
  `--host 0.0.0.0` together with the TLS broker profile and trusted-network
  controls only.

## 8. Cloud Consumer (Role: Cloud Consumer)

```powershell
python app.py --source "rtsp://<EDGE_IP>:8554/camera"          # MediaPipe preview
python build_index.py                                          # rebuild after dataset changes
python recognize_stream.py --source "rtsp://<EDGE_IP>:8554/camera" --require-gpu
```

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

| Symptom | Likely cause | Fix |
|---|---|---|
| Preflight: "FFmpeg was not found" | tools missing on this profile | `python scripts/setup_tools.py` (or brew/apt, see section 1) |
| Preflight: "camera enumeration failed" / "no cameras" (Pi) | CSI cable or raspi-config camera off | `sudo raspi-config` > Interface Options > Camera |
| Preflight: "RTSP port already in use" | another publisher/player holds 8554 | stop it, or check `tasklist`/`pgrep` for mediamtx |
| Controller sees no acks | ACL mismatch or wrong device_id | check `config/mosquitto/aclfile` (LF line endings), same `--mqtt-client-id` |
| `recognize_stream.py` not recognized on GPU | missing `--require-gpu` env | see README "Windows Recognition Setup" |
| Agent publish rejected "No matching subscribers" | controller not subscribed to `control/ack/+` | subscribe first, then send commands |
| Mosquitto ACL silently matching nothing | CRLF line endings in `config/mosquitto/*` | keep LF (`.gitattributes` enforces) |
| Dashboard video stuck on "Video unavailable" | MediaMTX WebRTC not reachable | verify `webrtc: true` in the config MediaMTX actually uses; check `--video-url` (Pi: `http://<PI_IP>:8889`); open UDP `8189`; on multi-NIC hosts set `webrtcLocalIP: <LAN_IP>` in the MediaMTX config |
| Dashboard control returns "MQTT broker is not connected" | broker down or bad dashboard credentials | check `docker compose ps`; verify `aiot-dashboard` exists in `passwords.example`/ACL and the password env var is set |
| Timeline shows no recognition events | recognition pipeline not publishing | run `recognize_stream.py` with `--mqtt-host`; check `mosquitto_sub -u aiot-logger ... -t recognition/result -v` |
