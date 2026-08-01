# Raspberry Pi 4 Test Plan

## Goal

Validate that a Raspberry Pi 4 can publish Pi Camera video through RTSP to the Windows laptop that runs the detection and recognition pipeline. The edge is responsible only for streaming and the MQTT control plane; AI runs on the cloud/laptop tier.

## Required Platform

- Use Raspberry Pi OS Bookworm and the `rpicam-*`/libcamera stack.
- Do not use `libcamera-vid` or the legacy camera stack.
- Prefer H.264 hardware encoding and RTSP over TCP.

## Option 1: MediaMTX Reads the Pi Camera Directly

Test this option first because it requires the least edge code.

```yaml
paths:
  camera:
    source: rpiCamera
    rpiCameraWidth: 1280
    rpiCameraHeight: 720
    rpiCameraFPS: 30
    rpiCameraCodec: hardwareH264
```

The Windows laptop reads the stream:

```text
rtsp://<PI_IP>:8554/camera
```

References:

- https://github.com/bluenviron/mediamtx
- https://mediamtx.org/docs/publish/raspberry-pi-cameras

## Option 2: `rpicam-vid` -> FFmpeg -> MediaMTX

Use this option when the Python process must manage the publisher, similarly to `stream_server.py`.

```bash
rpicam-vid -t 0 --codec h264 --inline \
  --width 1280 --height 720 --framerate 30 -o - |
ffmpeg -f h264 -i - -c:v copy -f rtsp -rtsp_transport tcp \
  rtsp://127.0.0.1:8554/camera
```

- `rpicam-vid` reads the camera and hardware-encodes H.264.
- FFmpeg only remuxes/copies the video and does not re-encode it, reducing Pi 4 CPU load.
- `--inline` places SPS/PPS in keyframes so RTSP clients that join later can still decode the stream.
- Python must manage the lifecycle, restart behavior, stdout/stderr, and graceful shutdown of both processes.

References:

- https://github.com/raspberrypi/rpicam-apps
- https://www.raspberrypi.com/documentation/computers/camera_software.html
- https://mediamtx.org/docs/publish/ffmpeg

## Option 3: Picamera2 for MQTT Camera Control

Use this option only when the edge needs detailed camera control through MQTT `control/*`: exposure, autofocus, resolution, snapshots, or sensor mode.

```text
Picamera2 -> H264Encoder -> FfmpegOutput -> MediaMTX RTSP
```

- Install with `apt install python3-picamera2 --no-install-recommends`; do not prefer `pip`.
- It is better suited to Python camera controls, but is more complex than the first two options.

Reference: https://github.com/raspberrypi/picamera2

## Test Sequence

1. Install Raspberry Pi OS Bookworm, update the system, connect the Pi Camera, and confirm that `rpicam-hello` works.
2. Run Option 1 at `1280x720@30`; open the stream on the Windows laptop with `app.py --source "rtsp://<PI_IP>:8554/camera"`.
3. Run `recognize_stream.py --source "rtsp://<PI_IP>:8554/camera"` on Windows and validate detection, recognition, tracking, and reconnect behavior.
4. Measure FPS, bitrate, CPU use, temperature, recognition latency, and Wi-Fi/LAN stability during a sustained session.
5. If the publisher must be Python-managed, move to Option 2 while retaining H.264 passthrough.
6. Move to Option 3 only when MQTT requires detailed camera control.

## Success Criteria

- The Pi Camera publishes a stable RTSP stream through the LAN to the Windows laptop.
- The laptop reconnects after the Pi stream stops and restarts.
- The detection/recognition pipeline processes the Pi stream without changing cloud logic.
- The Pi 4 maintains the target FPS and bitrate without overheating or CPU saturation.
- Camera device, resolution, FPS, and bitrate are configurable parameters, not Pi-specific hard-coded values.
