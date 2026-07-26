# MediaPipe Face Detection over RTSP

This project supports Windows AMD64 and macOS Apple Silicon. It contains two independent modules:

```text
Module 1: Webcam -> FFmpeg -> MediaMTX -> rtsp://127.0.0.1:8554/camera
Module 2: RTSP -> OpenCV + MediaPipe -> local window with green face boxes
```

The publisher does not analyze, mirror, resize, or annotate the webcam image. The detector does not republish its annotated video.

## Requirements

- A supported platform with an available webcam: Windows AMD64 or macOS Apple Silicon
- Python 3.12 recommended. Windows has also been verified with Python 3.14.
- Internet access once to download MediaMTX

## Setup

### Windows

From Bash in this project directory:

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/setup_tools.py
```

`setup_tools.py` downloads pinned FFmpeg and MediaMTX archives, verifies their checksums, and verifies the installed executables in `tools/`. It does not modify the system `PATH`.

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

On macOS, FFmpeg is managed by Homebrew at `/opt/homebrew/bin/ffmpeg`; the setup script verifies its AVFoundation input and `h264_videotoolbox` encoder. MediaMTX remains project-local in `tools/`.

On either platform, reinstall verified project-local tools with:

```bash
python scripts/setup_tools.py --force
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

```bash
python stream_server.py --device "Integrated Camera"
```

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

The raw webcam stream is available only on this machine:

```text
rtsp://127.0.0.1:8554/camera
```

MediaMTX is bound to `127.0.0.1`, so it does not accept LAN clients and no firewall rule is required. Press `Ctrl+C` to stop FFmpeg, MediaMTX, and release the webcam. On macOS, the publisher uses the M1 hardware encoder (`h264_videotoolbox`).

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

## Troubleshooting

- `Missing local tools`: run `python scripts/setup_tools.py`.
- `FFmpeg stopped unexpectedly`: use the exact camera name from `--list-devices`; close other apps using the webcam.
- `MediaMTX did not start`: port `8554` is likely already in use.
- `Could not open RTSP stream`: start module 1 first, then verify `rtsp://127.0.0.1:8554/camera`.
- For RTSP URLs containing credentials, avoid placing the full command in shared shell history or screenshots. Application logs redact passwords.
