# Backlog

## Current Priority - Demo And Report Release Gates

The two gates below are the only implementation priorities before the report and live demo. All other unchecked work remains valuable but is post-demo work unless it is explicitly listed as a gate acceptance criterion. Completing both parent checkboxes makes the project demo-ready as an operable multi-platform prototype; it does not claim production-hardening is complete.

### Gate 1 - Automate Edge Deployment By Profile

- [ ] Deliver one managed publisher entry point for every supported deployment profile, with no manually managed MediaMTX terminal on Raspberry Pi.
- [ ] Define and document explicit profiles: `rpi-csi`, `v4l2`, `avfoundation`, and `dshow`; require an explicit profile where auto-detection is ambiguous.
- [ ] Refactor `stream_server.py` so MediaMTX is always supervised but FFmpeg is an optional publisher child, rather than a mandatory process.
- [ ] Add the `rpi-csi` profile: use a dedicated MediaMTX `rpiCamera` configuration, hardware H.264, and direct RTSP publishing without FFmpeg.
- [ ] Add profile-specific preflight checks; Pi CSI must validate Linux ARM64, `rpicam-*`, camera availability, MediaMTX, and the RTSP port without requiring V4L2 or `libx264`.
- [ ] Preserve and smoke-test the existing Windows DirectShow, macOS AVFoundation, and Linux V4L2 publisher profiles.
- [ ] Add a Pi systemd deployment unit that starts the managed `rpi-csi` entry point at boot and restarts it after a failure.
- [ ] Demonstrate Pi boot/service restart -> RTSP recovery -> cloud `app.py` and `recognize_stream.py` consumption.
- [ ] Update the README and operational runbook with profile selection and Pi deployment instructions.

Completing Gate 1 closes these existing backlog items:

- [ ] Update README and supported-platform claims for the validated Raspberry Pi CSI direct-publisher profile; retain the V4L2/FFmpeg profile for USB cameras.
- [ ] Add a dedicated Pi MediaMTX configuration and a `rpi-csi` publisher profile so `stream_server.py` launches and monitors direct MediaMTX publishing without a second terminal.
- [ ] Refactor `stream_server.py` around explicit capture/deployment profiles (`rpi-csi`, `v4l2`, `avfoundation`, `dshow`) rather than assuming every publisher has an FFmpeg child process.
- [ ] Add profile-specific preflight checks. The Pi CSI profile must check Linux ARM64, the `rpicam-*` stack, camera availability, MediaMTX, and the RTSP port; it must not require V4L2 or `libx264`.
- [ ] Add a systemd deployment unit for the Pi profile to start on boot and restart after failures.
- [ ] Add unit tests for profile lifecycle and supervisor command-state transitions.

### Gate 2 - Define And Complete MQTT Edge Control

- [ ] Define and document the edge state machine: `offline`, `starting`, `streaming`, `stopping`, `stopped`, and `error`, including valid transitions and failure recovery.
- [ ] Define the command MVP: `status`, `start`, `stop`, and `restart`; specify payloads, acknowledgements, errors, idempotency, timeouts, and behavior when a continuous or motion-triggered stream is active.
- [ ] Implement a persistent edge agent/supervisor that remains running while a publisher stops and starts; separate it from the stoppable publisher runtime.
- [ ] Make the agent control the deployment-profile runtime or service, and publish device-scoped status, heartbeat, and RTSP health events.
- [ ] Restrict MQTT control to validated commands and schema; never execute arbitrary command strings received from MQTT.
- [ ] Preserve TLS, per-device topics, authentication, and ACL boundaries already implemented for LAN operation.
- [ ] Demonstrate controller `stop` -> retained/status `stopped` -> controller `start` -> `streaming` -> cloud RTSP reconnect and recognition event publication.
- [ ] Add unit tests for command validation and the state machine, plus opt-in integration coverage for authorized control and reconnect behavior.

Completing Gate 2 closes these existing backlog items:

- [ ] Implement a persistent edge supervisor so MQTT `start` and `restart` commands can start or restart a stopped publisher; define and test their interaction with motion-triggered monitoring.
- [ ] Define the MQTT edge command state machine: states, allowed transitions, command acknowledgement/error payloads, idempotency, and behavior for continuous versus motion-triggered streams.
- [ ] Implement a persistent edge supervisor/agent, separate from the stoppable publisher runtime, so MQTT `start`, `stop`, `restart`, and `status` commands work consistently across profiles.
- [ ] Keep MQTT command handling restricted to a validated command whitelist; never execute arbitrary command strings received over MQTT.
- [ ] Add opt-in integration coverage for Pi boot/service restart, RTSP reconnect, cloud recognition consumption, MQTT status/heartbeat, and authorized MQTT control.

## 2026-08-07 Progress Notes

### In Progress - Persistent MQTT Edge Control

- [x] Added `aiot/streaming/edge_supervisor.py` with the documented `offline`, `starting`, `streaming`, `stopping`, `stopped`, and `error` states, allowed transitions, command whitelist, schema validation, and command-id idempotency.
- [x] Added `scripts/run_edge_agent.py` as a persistent MQTT agent that supervises a fixed `stream_server.py --no-mqtt` child and publishes retained status, heartbeat metrics, RTSP TCP health, and command acknowledgements.
- [x] Added `status`, `start`, `stop`, and `restart` command payloads and the device-scoped `control/ack/<device_id>` topic while preserving TLS, authentication, and per-device ACL boundaries.
- [x] Added unit coverage for command validation, lifecycle transitions, duplicate commands, runtime failure recovery, and broker acknowledgement permissions.
- [x] Ran the local Mosquitto plus Windows camera demo: authorized controller `stop` returned retained/status `stopped`, `start` returned `streaming` with RTSP health, and `ffprobe` reconnected to H.264 `1280x720` at `30 FPS`.
- [ ] Validate the complete controller stop -> retained stopped -> start -> streaming -> cloud RTSP reconnect and recognition publication flow on the target edge hardware.

### Gate 2 Local Demo Runbook

Run these commands from the repository root in PowerShell. Keep the Mosquitto container running while testing.

1. Start the local broker and verify it is healthy:

```powershell
docker compose up -d mosquitto
docker compose ps
```

Expected broker port: `127.0.0.1:1883`.

2. Set the demo credentials and start the persistent edge agent. Use the exact camera name discovered by `stream_server.py --list-devices`; on the validated Windows machine it was `Integrated Camera`.

```powershell
$env:AIOT_EDGE_PASSWORD = 'edge-secret'
venv\Scripts\python.exe scripts\run_edge_agent.py `
  --device 'Integrated Camera' `
  --mqtt-host 127.0.0.1 `
  --mqtt-port 1883 `
  --mqtt-client-id pi4-edge-01 `
  --mqtt-username aiot-edge `
  --mqtt-password-env AIOT_EDGE_PASSWORD `
  --heartbeat-interval 1
```

The agent starts a fixed `stream_server.py --no-mqtt` child, MediaMTX, and FFmpeg. Leave this terminal running.

3. In a second PowerShell terminal, listen for device-scoped acknowledgements:

```powershell
docker compose exec mosquitto mosquitto_sub `
  -h 127.0.0.1 -p 1883 `
  -u aiot-controller -P controller-secret `
  -t control/ack/pi4-edge-01 -v
```

Keep that listener running. In a third terminal, send authorized `stop` and `start` commands:

```powershell
@'
import json
import time
from aiot.mqtt import payloads
from aiot.mqtt.client import MqttClient
from aiot.mqtt.topics import control_ack_topic, control_stream_topic

device = "pi4-edge-01"
client = MqttClient(
    host="127.0.0.1",
    port=1883,
    client_id="demo-controller",
    username="aiot-controller",
    password="controller-secret",
)
client.connect(timeout=5)
for action, command_id in (("stop", "demo-stop-001"), ("start", "demo-start-001")):
    client.publish(
        control_stream_topic(device),
        payloads.stream_control(
            action=action,
            target_device_id=device,
            command_id=command_id,
        ),
        qos=1,
    )
    print(action, "sent", command_id)
    time.sleep(2)
client.close()
'@ | venv\Scripts\python.exe -
```

Successful responses must contain the same `command_id`, `result: "succeeded"`, and the resulting state. The `stop` response should report `stopped`; the `start` response should report `streaming` with `rtsp_healthy: true`.

4. From a fourth terminal, verify that the restarted RTSP stream is consumable:

```powershell
& 'tools\ffmpeg\bin\ffprobe.exe' `
  -v error `
  -rtsp_transport tcp `
  -show_entries stream=codec_name,width,height,r_frame_rate `
  -of json `
  'rtsp://127.0.0.1:8554/camera'
```

Expected output includes H.264, `1280` x `720`, and `30/1` FPS.

5. Stop the agent with `Ctrl+C`. If it was launched in the background, stop only the agent and its child `ffmpeg.exe`/`mediamtx.exe` processes so the camera and port `8554` are released. Mosquitto can be stopped separately with:

```powershell
docker compose down
```

Verified on 2026-08-07: broker authentication, scoped controller delivery, edge acknowledgement ACLs, retained status behavior, local camera publishing, controller `stop` -> `stopped` -> `start` -> `streaming`, and RTSP reconnect. Not yet verified: cloud `recognize_stream.py` recognition-event publication during the same sequence.

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
- [x] Validate RTSP input from Raspberry Pi 4 and Pi Camera.
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
- [x] Validate the separate Raspberry Pi 4 and Pi Camera hardware path.

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

### Completed - MQTT Review Follow-up

- [x] Added Docker Compose Mosquitto demo config with password auth, generated ignored password file, and minimal ACLs for edge, recognition, and audit logger users.
- [x] Changed status/control/error RTSP topics to per-device routes, for example `system/status/pi4-edge-01`, `control/stream/pi4-edge-01`, and `error/rtsp/pi4-edge-01`.
- [x] Required control payloads to include `target_device_id`; commands for other devices are ignored.
- [x] Kept the control MVP scoped to `stop`; `start` and `restart` are documented as unsupported supervisor actions.
- [x] Added MQTT connect fail-fast behavior for broker CONNACK reject/timeout, disconnect logging, reconnect resubscribe, retained status republish, and QoS publish error checks.
- [x] Added RTSP credential redaction before MQTT publish and before SQLite audit persistence.
- [x] Added audit validation, payload-size checks, and retention by days or max records.
- [x] Added unit tests for IDOC label mapping, UTF-8 BOM labels, missing manifest/labels fallback, and `collect_images()` labels.
- [x] Added a skipped-by-default Mosquitto integration test that can be enabled with `AIOT_RUN_MQTT_INTEGRATION=1`.
- [x] Validated the Docker Mosquitto broker with the real integration test: `AIOT_RUN_MQTT_INTEGRATION=1 venv\Scripts\python.exe -m unittest tests.test_mqtt_mosquitto_integration -v` passed 3 tests.
- [x] Confirmed correct broker auth behavior: demo users with the documented passwords connect successfully, while an incorrect password is rejected with `Not authorized`.
- [x] Recreated the Mosquitto container after fixing runtime config permissions; broker logs no longer show password/ACL permission warnings.
- [x] Validated broker restart/reconnect behavior with Docker restart: clients reconnected, audit subscriptions recovered, a post-restart `error/pipeline` event was persisted, and RTSP credential markers were not stored.

### Completed - MQTT Security and LAN TLS Foundation

- [x] Added the `aiot-controller` broker principal and ACL write access for device-scoped `control/stream/+` commands; validated controller-to-edge command delivery with Docker Mosquitto.
- [x] Made the local plaintext broker host-only (`127.0.0.1:1883`); it is not exposed to the LAN.
- [x] Added an optional Mosquitto TLS profile on port `8883`, CA certificate CLI support for MQTT clients, and LAN setup documentation.
- [x] Added initial-CONNACK/SUBACK failure handling, QoS publish completion checks, reconnect subscription restoration, and safe retained-status republish handling.
- [x] Scoped recognition pipeline errors to `error/pipeline/<device_id>`.
- [x] Strengthened audit payload type validation and changed age retention to use the logger's local receipt time.
- [x] Validated Docker Mosquitto authentication, audit persistence/redaction, and controller-to-edge scoped command delivery with `tests.test_mqtt_mosquitto_integration`.

### Still Open

- [x] Rebuild `database/faces.index` and `database/metadata.json` after the IDOC relabeling change before running the live recognition demo.
- [x] Keep raw mugshot images, generated embeddings, metadata, and audit databases out of Git history unless the publication policy explicitly allows them.
- [x] Generate LAN TLS certificates and validate a real TLS MQTT connection from the Raspberry Pi to the cloud broker on port `8883`.
- [ ] Add automated Docker integration coverage for broker restart/reconnect, retained-status replay, and unauthorized controller publishes.
- [ ] Implement a persistent edge supervisor so MQTT `start` and `restart` commands can start or restart a stopped publisher; define and test their interaction with motion-triggered monitoring.
- [x] Implement the generic motion-triggered edge session controller: MOG2 monitoring, FFmpeg camera handoff, `stream/activity/<device_id>`, 30-second first-face timeout, and 120-second face-presence lease.
- [ ] Validate motion-triggered handoff and threshold tuning with real Windows/macOS/Linux cameras, then design and validate a separate Raspberry Pi Camera CSI motion adapter if that mode is required.

## 2026-08-05 Progress Notes

### Completed - Raspberry Pi CSI Direct RTSP Validation

- [x] Validated Raspberry Pi 4 CSI camera publishing directly through MediaMTX v1.19.3 using `source: rpiCamera`, `hardwareH264`, `1280x720`, and `30 FPS`.
- [x] Confirmed that the direct CSI profile does not need FFmpeg or the V4L2 publisher path: MediaMTX owns camera capture, hardware H.264 encoding, and RTSP publishing.
- [x] Confirmed that `mediamtx_v1.19.3_linux_arm64.tar.gz` is the correct ARM64 release asset already selected by `scripts/setup_tools.py`.
- [x] Verified that a cloud client can consume `rtsp://<PI_IP>:8554/camera` through `app.py --source` without application-code changes.

### Still Open - Edge Profiles And MQTT Supervision

- [ ] Update README and supported-platform claims for the validated Raspberry Pi CSI direct-publisher profile; retain the V4L2/FFmpeg profile for USB cameras.
- [ ] Add a dedicated Pi MediaMTX configuration and a `rpi-csi` publisher profile so `stream_server.py` launches and monitors direct MediaMTX publishing without a second terminal.
- [ ] Refactor `stream_server.py` around explicit capture/deployment profiles (`rpi-csi`, `v4l2`, `avfoundation`, `dshow`) rather than assuming every publisher has an FFmpeg child process.
- [ ] Add profile-specific preflight checks. The Pi CSI profile must check Linux ARM64, the `rpicam-*` stack, camera availability, MediaMTX, and the RTSP port; it must not require V4L2 or `libx264`.
- [ ] Add a systemd deployment unit for the Pi profile to start on boot and restart after failures.
- [ ] Define the MQTT edge command state machine: states, allowed transitions, command acknowledgement/error payloads, idempotency, and behavior for continuous versus motion-triggered streams.
- [ ] Implement a persistent edge supervisor/agent, separate from the stoppable publisher runtime, so MQTT `start`, `stop`, `restart`, and `status` commands work consistently across profiles.
- [ ] Keep MQTT command handling restricted to a validated command whitelist; never execute arbitrary command strings received over MQTT.
- [ ] Add unit tests for profile lifecycle and supervisor command-state transitions.
- [ ] Add opt-in integration coverage for Pi boot/service restart, RTSP reconnect, cloud recognition consumption, MQTT status/heartbeat, and authorized MQTT control.
