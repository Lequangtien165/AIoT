# AIoT Face Detection and Recognition

This project supports Windows AMD64 and macOS Apple Silicon for RTSP face detection. Windows AMD64 also supports local face recognition with InsightFace and FAISS, with NVIDIA CUDA used when the local ONNX Runtime GPU dependencies are available. Linux ARM64 supports RTSP publishing from V4L2 cameras for edge validation; it does not run the recognition pipeline.

```text
Module 1: Webcam -> FFmpeg -> MediaMTX -> rtsp://127.0.0.1:8554/camera
Module 2: RTSP -> OpenCV + MediaPipe -> local window with green face boxes
Module 3: RTSP -> InsightFace + FAISS -> named face boxes (Windows only)
```

The publisher does not analyze, mirror, resize, or annotate the webcam image. The detector does not republish its annotated video.

## Layout

Keep executable commands at the repository root. Reusable code is grouped under `aiot/`:

```text
aiot/
  detection/    MediaPipe face detection
  recognition/  InsightFace embeddings and FAISS search
  streaming/    RTSP reader, output, publisher configuration
  tracking/     IoU tracks and identity cache
```

## Requirements

- A supported platform with an available webcam: Windows AMD64 or macOS Apple Silicon
- Python 3.12 recommended. Windows has also been verified with Python 3.14.
- Internet access once to download MediaMTX

## Setup

Use a dedicated Python 3.14 virtual environment. The stream dependencies are cross-platform:

### Windows

Run these commands from Git Bash in this project directory. Windows recognition commands in this README require Windows AMD64; they are not supported on macOS or Linux.

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/setup_tools.py
```

`setup_tools.py` shows an install plan and staged download, checksum, extraction, and verification status for pinned FFmpeg and MediaMTX archives. Interactive terminals show a progress bar; redirected output reports download milestones. It verifies the installed executables in `tools/` and does not modify the system `PATH`.

### macOS Apple Silicon

Install native dependencies with Homebrew:

```bash
brew install python@3.12 ffmpeg
```

Create the Python environment and install the project-local MediaMTX binary:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/setup_tools.py
```

On macOS, FFmpeg is managed by Homebrew at `/opt/homebrew/bin/ffmpeg`; the setup script verifies its AVFoundation input and `h264_videotoolbox` encoder before downloading MediaMTX. MediaMTX remains project-local in `tools/`.

### Linux ARM64 Edge Publisher

Use Ubuntu ARM64 with a passed-through UVC/V4L2 camera for edge validation. This phase supports `/dev/videoN` cameras, not Raspberry Pi CSI cameras.

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg v4l-utils
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install certifi
python scripts/setup_tools.py
```

The edge publisher only needs `certifi` as a Python dependency. The setup script verifies the system FFmpeg V4L2 input and `libx264` encoder, then downloads and verifies the project-local MediaMTX ARM64 binary.

On either platform, reinstall verified project-local tools with:

```bash
python scripts/setup_tools.py --force
```

### Windows Recognition Setup

Install the Windows-only recognition backend after the common dependencies. Install InsightFace without its dependencies so it cannot install `opencv-python` alongside `opencv-contrib-python`.

```bash
python -m pip install -r requirements-recognition-windows.txt
python -m pip install --no-deps insightface==1.0.1
```

`onnxruntime-gpu==1.28.0` requires an NVIDIA driver that supports CUDA 13 and compatible CUDA/cuDNN runtime DLLs. On the tested Windows RTX 3050 Laptop setup, updating the NVIDIA driver to a CUDA 13-capable release made `CUDAExecutionProvider` active. If those dependencies are missing or the driver is too old, the app falls back to CPU and prints a warning that includes the failing ONNX Runtime provider load message. Use `--require-gpu` to fail fast instead of silently running on CPU.

Verify that ONNX Runtime can bind the InsightFace detector to CUDA:

```bash
python -c "import onnxruntime as ort; ort.preload_dlls(directory=''); print('available', ort.get_available_providers()); s=ort.InferenceSession(r'C:\Users\Qtienle\.insightface\models\buffalo_l\det_10g.onnx', providers=['CUDAExecutionProvider','CPUExecutionProvider']); print('active', s.get_providers())"
```

The expected result includes `CUDAExecutionProvider` in `active`. If `active` is only `CPUExecutionProvider`, run recognition with `--require-gpu` to confirm the failure before tuning performance.

Build the enrollment index before recognition. Enrollment images belong in `dataset/<person>/` and must have one face each.

```bash
python build_index.py
python recognize_image.py path/to/image.jpg
```

For the local IDOC demo dataset, raw data is intentionally not committed. Prepare it locally in this shape:

```text
dataset/
  IDOC_manifest.csv
  IDOC_000001/
    front.jpg
    side.jpg
archive/labels_utf8.csv
```

`dataset/IDOC_manifest.csv` maps `folder` to the source `ID`; `archive/labels_utf8.csv` supplies the `ID,Sex` columns and may include a UTF-8 BOM. `build_index.py` labels IDOC folders as `ID - Sex`, then writes `database/faces.index` and `database/metadata.json`. Those generated database files and the raw IDOC dataset remain local-only and must be rebuilt after clone.

Download the official MediaPipe short-range BlazeFace model:

```bash
mkdir -p models
curl -L --fail \
  --output models/blaze_face_short_range.tflite \
  https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite
```

## Module 1: RTSP Publisher

List available cameras:

```bash
python stream_server.py --list-devices
```

Start the publisher and choose a camera from the numbered menu:

```bash
python stream_server.py
```

For scripts or automation, provide the device explicitly. On Windows use the exact DirectShow device name:

```bash
python stream_server.py --device "Integrated Camera"
```

Do not include the menu number from `--list-devices`. For example, use `"Integrated Camera"`, not `"1. Integrated Camera"`.

On macOS use the AVFoundation video index shown by `--list-devices`:

```bash
python stream_server.py --device 0
```

On Linux ARM64, use the V4L2 path shown by `--list-devices`:

```bash
python stream_server.py --device /dev/video0
```

The default capture mode is `1280x720` at `30 FPS`, avoiding AVFoundation's unsupported `29.97 FPS` fallback. Override it only when a camera does not support that mode:

```bash
python stream_server.py \
  --device "Integrated Camera" \
  --video-size 1280x720 \
  --framerate 30 \
  --bitrate 2M
```

FFmpeg publishes the raw webcam stream locally at:

```text
rtsp://127.0.0.1:8554/camera
```

MediaMTX listens on the configured RTSP address in `config/mediamtx.yml`, allowing trusted LAN clients to read `rtsp://<PUBLISHER_IP>:8554/camera`. Press `Ctrl+C` to stop FFmpeg, MediaMTX, and release the webcam. On macOS, the publisher uses the M1 hardware encoder (`h264_videotoolbox`).

On the first macOS capture attempt, grant camera access to the terminal application in **System Settings > Privacy & Security > Camera**.

## Module 2: Face Detector

In a separate Bash terminal, activate the virtual environment and run. On Windows, use Git Bash:

```bash
source .venv/Scripts/activate
# macOS: source .venv/bin/activate
python app.py
```

The default source is `rtsp://127.0.0.1:8554/camera`. To use another local RTSP source:

```bash
python app.py --source "rtsp://127.0.0.1:8554/another-stream"
```

When the publisher is stopped or the stream temporarily fails, the detector keeps running and retries automatically. Press `Q`, `Esc`, or `Ctrl+C` to close the detector. The publisher continues running after the detector exits.

## Detector Options

```text
--source URL          RTSP URL, default: rtsp://127.0.0.1:8554/camera
--confidence VALUE    Detection confidence from 0 to 1, default: 0.5
--reconnect-delay S   Seconds between RTSP retries, default: 2
```

## Realtime Recognition (Windows Only)

After starting the RTSP publisher and building the index, open a second Git Bash terminal on Windows:

```bash
source .venv/Scripts/activate
python recognize_stream.py --recognition-fps 2 --profile --require-gpu
```

The startup log should include:

```text
SCRFD providers: CUDAExecutionProvider, CPUExecutionProvider
ArcFace providers: CUDAExecutionProvider, CPUExecutionProvider
GPU active
```

The production recognition path uses the InsightFace `buffalo_l` bundle only. SCRFD detects every face for tracking, then ArcFace creates an embedding only for scheduler-selected tracks. The default budget is one embedding per detection cycle, so a crowded frame does not trigger ArcFace work for every face at once. The display loop stays responsive because frame capture, inference, and rendering run as separate stages. Press `Q`, `Esc`, or `Ctrl+C` to stop. If `--recognition-fps 2` is stable, increase it gradually:

```bash
python recognize_stream.py \
  --threshold 0.45 \
  --recognition-fps 4 \
  --max-embeddings-per-cycle 1 \
  --profile \
  --require-gpu
```

Then try `--recognition-fps 6` if the GPU latency remains low. `--recognition-fps` controls SCRFD detection/tracking cycles; `--max-embeddings-per-cycle` controls the ArcFace budget and defaults to `1`. Use `--require-gpu` when the session must use CUDA and should exit immediately if either SCRFD or ArcFace falls back to CPU.

Watch GPU usage from a third terminal:

```bash
nvidia-smi -l 1
```

The process list should show `python.exe`, and GPU memory or utilization should increase while recognition is running.

Video recording is optional. A snapshot is saved only when a track first becomes `MATCH` or its confirmed identity changes. `outputs/` is ignored by Git.

```bash
python recognize_stream.py \
  --threshold 0.45 \
  --recognition-fps 6 \
  --profile \
  --require-gpu \
  --record-video outputs/session.mp4 \
  --snapshot-dir outputs/snapshots
```

On macOS, use `python app.py` for detection. `recognize_stream.py` exits with a clear Windows-only message.

## MQTT Control Plane and Audit Logging

### Environment Configuration

Copy `.env.example` to `.env` on both machines and edit the LAN addresses, local CA path, camera values, and role passwords. The file is ignored by Git.

```bash
cp .env.example .env
```

Load it into the current Bash session before running a role command. The example `.env` uses shell-compatible `KEY=value` entries:

```bash
set -a
source .env
set +a
```

Use role-specific password environment variables with the existing CLI flag, for example `--mqtt-password-env AIOT_EDGE_MQTT_PASSWORD`. This keeps the broker address, certificate path, and secrets out of command history.

MQTT is optional. A local Mosquitto demo broker is provided with password auth and minimal ACLs. Docker publishes its plaintext listener only on host `127.0.0.1`, so it is for local development only:

```bash
docker compose up -d mosquitto
```

The compose file copies and hashes `config/mosquitto/passwords.example` inside the broker container. Demo users are:

```text
aiot-edge / edge-secret
aiot-recognition / recognition-secret
aiot-controller / controller-secret
aiot-logger / logger-secret
```

The demo ACL allows the edge publisher to write `system/status/pi4-edge-01`, `error/rtsp/pi4-edge-01`, and `motion/detected`, and subscribe to `control/stream/pi4-edge-01`. Recognition can publish `recognition/result`, `error/pipeline/<device_id>`, and `system/status/aiot-recognition`. The controller can publish scoped stream commands. The logger can only subscribe to audit topics.

### MQTT Over LAN With TLS

For a Raspberry Pi or another LAN client, use the TLS broker profile. Do not expose the plaintext `1883` listener to the LAN.

Choose a stable LAN IP or hostname for the cloud laptop. A DHCP reservation is recommended so the broker address does not change. On the cloud laptop, create local development certificates; replace `BROKER_HOSTNAME` and `BROKER_LAN_IP` with the exact hostname and IP that the Pi will use to reach the broker:

```bash
MSYS_NO_PATHCONV=1 openssl req -x509 -newkey rsa:2048 -nodes -keyout config/mosquitto/certs/server.key -out config/mosquitto/certs/server.crt -days 365 -subj "/CN=BROKER_HOSTNAME" -addext "subjectAltName=DNS:BROKER_HOSTNAME,IP:BROKER_LAN_IP"
cp config/mosquitto/certs/server.crt config/mosquitto/certs/ca.crt
docker compose --profile tls up -d mosquitto-tls
```

The certificate SAN must match the address used by the client. For example, if the Pi connects to `192.168.1.20`, include `IP:192.168.1.20`; if it connects to `aiot-cloud.local`, include `DNS:aiot-cloud.local`.

Open inbound TCP port `8883` on the cloud laptop's Private network firewall. Do not use the published demo passwords on LAN. Certificate and private-key files are ignored by Git.

Copy only `config/mosquitto/certs/ca.crt` to the Pi, for example:

```bash
scp <WINDOWS_USER>@<BROKER_LAN_IP>:"C:/Users/<WINDOWS_USER>/AIoT/config/mosquitto/certs/ca.crt" ~/aiot-certs/ca.crt
```

On the Edge device, start the publisher with the TLS broker address and copied CA file:

```bash
export AIOT_MQTT_PASSWORD='<edge-password>'
python stream_server.py \
  --device /dev/video0 \
  --mqtt-host <BROKER_LAN_IP> \
  --mqtt-port 8883 \
  --mqtt-ca-cert ~/aiot-certs/ca.crt \
  --mqtt-client-id pi4-edge-01 \
  --mqtt-username aiot-edge \
  --mqtt-password-env AIOT_MQTT_PASSWORD
```

On the **Windows AMD64 cloud laptop**, run this from Git Bash to recognize the edge RTSP stream:

```bash
export AIOT_MQTT_PASSWORD='<recognition-password>'
python recognize_stream.py --source "rtsp://<EDGE_LAN_IP>:8554/camera" --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 --mqtt-ca-cert config/mosquitto/certs/ca.crt --mqtt-client-id aiot-recognition --source-device-id pi4-edge-01 --mqtt-username aiot-recognition --mqtt-password-env AIOT_MQTT_PASSWORD
```

Run the audit logger on the cloud laptop in another terminal:

```bash
export AIOT_MQTT_PASSWORD='<logger-password>'
python scripts/run_mqtt_logger.py --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 --mqtt-ca-cert config/mosquitto/certs/ca.crt --mqtt-username aiot-logger --mqtt-password-env AIOT_MQTT_PASSWORD
```

Before starting the full pipeline, verify the Pi can establish a TLS MQTT connection. With `mosquitto-clients` installed on the Edge device:

```bash
mosquitto_sub -h <BROKER_LAN_IP> -p 8883 --cafile ~/aiot-certs/ca.crt -u aiot-edge -P "$AIOT_MQTT_PASSWORD" -t 'control/stream/pi4-edge-01' -d
```

The expected result is a successful TLS connection followed by a subscription. If it fails, verify the certificate SAN, firewall rule, broker container status (`docker compose --profile tls ps`), LAN routing, and credentials.

Enable publisher status and control messages:

```bash
export AIOT_MQTT_PASSWORD='edge-secret'
python stream_server.py --device "Integrated Camera" --mqtt-host 127.0.0.1 --mqtt-client-id pi4-edge-01 --mqtt-username aiot-edge --mqtt-password-env AIOT_MQTT_PASSWORD
```

For a broker that requires credentials, keep the password out of shell history by reading it from an environment variable:

Set `AIOT_MQTT_PASSWORD` in the terminal environment first, then run:

```bash
python stream_server.py --device "Integrated Camera" --mqtt-host 127.0.0.1 --mqtt-client-id pi4-edge-01 --mqtt-username aiot-edge --mqtt-password-env AIOT_MQTT_PASSWORD
```

The persistent edge agent emits retained `system/status/<device_id>` heartbeat messages, publishes command results to `control/ack/<device_id>`, and subscribes only to `control/stream/<device_id>`. Commands use this JSON shape:

```json
{
  "schema_version": 1,
  "command_id": "demo-stop-001",
  "target_device_id": "pi4-edge-01",
  "action": "stop",
  "requested_by": "cloud",
  "parameters": {}
}
```

Publish that command to `control/stream/pi4-edge-01`. The agent validates schema version, command ID, topic, target device, action, and parameter types. The only accepted actions are `status`, `start`, `stop`, and `restart`; MQTT never supplies an executable command string. Reusing a `command_id` returns the original acknowledgement without running the action again.

With the demo broker, publish the command with its authorized controller account:

```bash
docker compose exec mosquitto mosquitto_pub -h 127.0.0.1 -p 1883 -u aiot-controller -P controller-secret -t control/stream/pi4-edge-01 -m '{"schema_version":1,"command_id":"demo-stop-001","target_device_id":"pi4-edge-01","action":"stop","requested_by":"cloud","parameters":{}}'
```

Run the persistent agent instead of `stream_server.py` when remote start/stop/restart is required:

```bash
python scripts/run_edge_agent.py --device /dev/video0 --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 --mqtt-ca-cert ~/aiot-certs/ca.crt --mqtt-client-id pi4-edge-01 --mqtt-username aiot-edge --mqtt-password-env AIOT_MQTT_PASSWORD
```

The agent owns the MQTT connection and keeps running while the fixed publisher child is stopped. Its state machine is `offline -> starting -> streaming -> stopping -> stopped`, with `error` entered when the child exits unexpectedly; `start` and `restart` recover from `stopped` or `error`. In `--motion-triggered` mode, the supervised child remains alive as the motion monitor while the camera publisher is started and stopped by the existing session policy. Status payloads include `mode`, child liveness, and RTSP TCP health.

Enable recognition result publishing from **Windows AMD64 Git Bash**:

```bash
export AIOT_MQTT_PASSWORD='recognition-secret'
python recognize_stream.py --recognition-fps 4 --profile --mqtt-host 127.0.0.1 --mqtt-username aiot-recognition --mqtt-password-env AIOT_MQTT_PASSWORD --source-device-id pi4-edge-01
```

The recognition pipeline publishes `recognition/result`, retained `system/status/aiot-recognition`, and `error/pipeline/<source-device-id>`. Run the SQLite audit logger in a separate terminal:

```bash
export AIOT_MQTT_PASSWORD='logger-secret'
python scripts/run_mqtt_logger.py --mqtt-host 127.0.0.1 --mqtt-username aiot-logger --mqtt-password-env AIOT_MQTT_PASSWORD
```

The audit logger subscribes to and persists only `recognition/result`, `motion/detected`, and `error/#`; `system/status/<device_id>` and `control/stream/<device_id>` are not stored. It validates the topic schema, required field types, and payload size; redacts RTSP credentials before SQLite insert; and applies default retention of 30 days or 100,000 records. Age retention uses the logger's local receipt time. The SQLite DB can still contain recognition events and track metadata, so treat `database/*.sqlite3` as sensitive local runtime data.

Run repeatable unit tests normally:

```bash
python -m unittest discover -s tests -v
```

With the Docker Mosquitto broker running, enable the real broker integration test:

```bash
AIOT_RUN_MQTT_INTEGRATION=1 python -m unittest tests.test_mqtt_mosquitto_integration -v
```

`motion/detected` is reserved for the edge motion producer. Real Pi GPIO/software-motion integration and the web UI described in the architecture report remain outside this MQTT/audit MVP. Broker restart behavior still requires repeatable integration coverage before it can be claimed as automated validation.

## Motion-Triggered Edge Sessions

`stream_server.py` keeps its existing always-stream behavior by default. Enable `--motion-triggered` to run a low-rate OpenCV MOG2 monitor while idle, then start FFmpeg only after significant motion. The cloud recognition client renews the stream lease when it detects a face: the first face must arrive within 30 seconds, and later face-presence messages renew a 120-second lease every 15 seconds.

```bash
python stream_server.py --device /dev/video0 --motion-triggered --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 --mqtt-ca-cert ~/aiot-certs/ca.crt --mqtt-client-id pi4-edge-01 --mqtt-username aiot-edge --mqtt-password-env AIOT_MQTT_PASSWORD
```

```bash
# Windows AMD64 cloud laptop only; run from Git Bash.
python recognize_stream.py --source "rtsp://<EDGE_LAN_IP>:8554/camera" --edge-triggered-session --source-device-id pi4-edge-01 --mqtt-host <BROKER_LAN_IP> --mqtt-port 8883 --mqtt-ca-cert config/mosquitto/certs/ca.crt --mqtt-username aiot-recognition --mqtt-password-env AIOT_MQTT_PASSWORD
```

The motion baseline is `320x240` at `5 FPS`, MOG2, a 2% changed-area threshold, and a 3-of-5-frame trigger. Adjust it with the `--motion-*` flags after camera testing. On Windows and macOS, pass an OpenCV camera index through `--motion-device`; Linux V4L2 can reuse `/dev/videoN`.

The first implementation supports webcam/V4L2 capture. Raspberry Pi Camera CSI remains a separately unvalidated adapter; do not claim Pi Camera support until it has been tested with the `rpicam-*` stack.

## Troubleshooting

- `Missing local tools`: run `python scripts/setup_tools.py`.
- `FFmpeg stopped unexpectedly`: use the exact camera name from `--list-devices`; close other apps using the webcam.
- `MediaMTX did not start`: port `8554` is likely already in use.
- `Could not open RTSP stream`: start module 1 first, then verify `rtsp://127.0.0.1:8554/camera`.
- `Could not find video device with name [1. Integrated Camera]`: pass the exact device name without the menu number, for example `--device "Integrated Camera"`.
- `GPU requested but unavailable, using CPU`: verify the NVIDIA driver, CUDA/cuDNN runtime DLLs, and the ONNX Runtime CUDA session test in the Windows recognition setup section.
- For RTSP URLs or MQTT credentials, avoid placing secrets in shared shell history or screenshots. Application logs redact RTSP passwords, and MQTT passwords should be passed through `--mqtt-password-env`.
