# AIoT Face Detection and Recognition

This project supports Windows AMD64 and macOS Apple Silicon for RTSP face detection. Windows AMD64 also supports local face recognition with InsightFace and FAISS, with NVIDIA CUDA used when the local ONNX Runtime GPU dependencies are available.

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

From PowerShell in this project directory:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
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

On either platform, reinstall verified project-local tools with:

```bash
python scripts/setup_tools.py --force
```

### Windows Recognition Setup

Install the Windows-only recognition backend after the common dependencies. Install InsightFace without its dependencies so it cannot install `opencv-python` alongside `opencv-contrib-python`.

```powershell
python -m pip install -r requirements-recognition-windows.txt
python -m pip install --no-deps insightface==1.0.1
```

`onnxruntime-gpu==1.28.0` requires an NVIDIA driver that supports CUDA 13 and compatible CUDA/cuDNN runtime DLLs. On the tested Windows RTX 3050 Laptop setup, updating the NVIDIA driver to a CUDA 13-capable release made `CUDAExecutionProvider` active. If those dependencies are missing or the driver is too old, the app falls back to CPU and prints a warning that includes the failing ONNX Runtime provider load message. Use `--require-gpu` to fail fast instead of silently running on CPU.

Verify that ONNX Runtime can bind the InsightFace detector to CUDA:

```powershell
python -c "import onnxruntime as ort; ort.preload_dlls(directory=''); print('available', ort.get_available_providers()); s=ort.InferenceSession(r'C:\Users\Qtienle\.insightface\models\buffalo_l\det_10g.onnx', providers=['CUDAExecutionProvider','CPUExecutionProvider']); print('active', s.get_providers())"
```

The expected result includes `CUDAExecutionProvider` in `active`. If `active` is only `CPUExecutionProvider`, run recognition with `--require-gpu` to confirm the failure before tuning performance.

Build the enrollment index before recognition. Enrollment images belong in `dataset/<person>/` and must have one face each.

```powershell
python build_index.py
python recognize_image.py path/to/image.jpg
```

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

```powershell
python stream_server.py --device "Integrated Camera"
```

Do not include the menu number from `--list-devices`. For example, use `"Integrated Camera"`, not `"1. Integrated Camera"`.

On macOS use the AVFoundation video index shown by `--list-devices`:

```bash
python stream_server.py --device 0
```

The default capture mode is `1280x720` at `30 FPS`, avoiding AVFoundation's unsupported `29.97 FPS` fallback. Override it only when a camera does not support that mode:

```bash
python stream_server.py \
  --device "Integrated Camera" \
  --video-size 1280x720 \
  --framerate 30 \
  --bitrate 2M
```

The raw webcam stream is published at:

```text
rtsp://127.0.0.1:8554/camera
```

MediaMTX listens on the configured RTSP address in `config/mediamtx.yml`. Press `Ctrl+C` to stop FFmpeg, MediaMTX, and release the webcam. On macOS, the publisher uses the M1 hardware encoder (`h264_videotoolbox`).

On the first macOS capture attempt, grant camera access to the terminal application in **System Settings > Privacy & Security > Camera**.

## Module 2: Face Detector

In a separate Bash terminal, activate the virtual environment and run. Use the matching activation command for your platform:

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

After starting the RTSP publisher and building the index, open a second terminal:

```powershell
cd A:\face_reg
.\venv\Scripts\Activate.ps1
python recognize_stream.py --recognition-fps 2 --profile --require-gpu
```

The startup log should include:

```text
FaceEngine providers: CUDAExecutionProvider, CPUExecutionProvider
GPU active
```

The window labels every tracked face with a cached identity. The display loop stays responsive because frame capture, InsightFace inference, and rendering run as separate stages. Press `Q`, `Esc`, or `Ctrl+C` to stop. If `--recognition-fps 2` is stable, increase it gradually:

```powershell
python recognize_stream.py \
  --threshold 0.45 \
  --recognition-fps 4 \
  --profile \
  --require-gpu
```

Then try `--recognition-fps 6` if the GPU latency remains low. Use `--require-gpu` when the session must use CUDA and should exit immediately if ONNX Runtime falls back to CPU.

Watch GPU usage from a third terminal:

```powershell
nvidia-smi -l 1
```

The process list should show `python.exe`, and GPU memory or utilization should increase while recognition is running.

Video recording is optional. A snapshot is saved only when a track first becomes `MATCH` or its confirmed identity changes. `outputs/` is ignored by Git.

```powershell
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

MQTT is optional. Start a Mosquitto-compatible broker, then enable publisher status and control messages:

```powershell
python stream_server.py --device "Integrated Camera" --mqtt-host 127.0.0.1
```

The RTSP publisher emits `system/status` heartbeat messages and subscribes to `control/stream`. A stop command uses this JSON payload:

```json
{"schema_version":1,"action":"stop","requested_by":"cloud","parameters":{}}
```

Enable recognition result publishing:

```powershell
python recognize_stream.py --recognition-fps 4 --profile --mqtt-host 127.0.0.1
```

The recognition pipeline publishes `recognition/result`, `system/status`, and `error/pipeline`. Run the SQLite audit logger in a separate terminal:

```powershell
python scripts/run_mqtt_logger.py --mqtt-host 127.0.0.1 --db-path database/audit_log.sqlite3
```

The audit logger subscribes to `recognition/result`, `motion/detected`, and `error/#`. `motion/detected` is reserved for the Raspberry Pi PIR edge client; GPIO integration still needs validation on the Pi.

## Troubleshooting

- `Missing local tools`: run `python scripts/setup_tools.py`.
- `FFmpeg stopped unexpectedly`: use the exact camera name from `--list-devices`; close other apps using the webcam.
- `MediaMTX did not start`: port `8554` is likely already in use.
- `Could not open RTSP stream`: start module 1 first, then verify `rtsp://127.0.0.1:8554/camera`.
- `Could not find video device with name [1. Integrated Camera]`: pass the exact device name without the menu number, for example `--device "Integrated Camera"`.
- `GPU requested but unavailable, using CPU`: verify the NVIDIA driver, CUDA/cuDNN runtime DLLs, and the ONNX Runtime CUDA session test in the Windows recognition setup section.
- For RTSP URLs containing credentials, avoid placing the full command in shared shell history or screenshots. Application logs redact passwords.
