"""Publish a local webcam to a MediaMTX RTSP stream."""

from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from aiot.mqtt import payloads
from aiot.mqtt.client import MqttClient, MqttUnavailable, password_from_env
from aiot.mqtt.topics import TOPIC_CONTROL_STREAM, TOPIC_ERROR_RTSP, TOPIC_POLICIES, TOPIC_SYSTEM_STATUS
from aiot.streaming.stream_platform import PlatformConfig, get_platform_config
from aiot.streaming.stream_settings import RTSP_HOST, RTSP_PORT, RTSP_URL

PROJECT_ROOT = Path(__file__).parent
MEDIA_MTX_CONFIG = PROJECT_ROOT / "config" / "mediamtx.yml"
CONTROL_STREAM_ACTIONS = {"stop", "start", "restart"}


@dataclass(frozen=True)
class CameraDevice:
    display_name: str
    input_spec: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish a webcam to an RTSP stream."
    )
    parser.add_argument(
        "--device",
        help="Camera name on Windows, AVFoundation index on macOS, or /dev/videoN on Linux.",
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="List available video devices and exit."
    )
    parser.add_argument(
        "--framerate", type=int, default=30, help="Requested camera frame rate (default: 30)."
    )
    parser.add_argument(
        "--video-size", default="1280x720", help="Requested size (default: 1280x720)."
    )
    parser.add_argument("--bitrate", default="2M", help="H.264 bitrate (default: 2M).")
    parser.add_argument("--mqtt-host", help="MQTT broker host for edge status and control.")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-client-id", default="aiot-edge-publisher")
    parser.add_argument("--mqtt-username", help="MQTT username. Password is read from --mqtt-password-env.")
    parser.add_argument("--mqtt-password-env", help="Environment variable containing the MQTT password.")
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    args = parser.parse_args()

    if args.framerate is not None and args.framerate <= 0:
        parser.error("--framerate must be positive.")
    if args.mqtt_port <= 0 or args.heartbeat_interval <= 0:
        parser.error("--mqtt-port and --heartbeat-interval must be positive.")
    if args.mqtt_username:
        try:
            password_from_env(args.mqtt_username, args.mqtt_password_env)
        except ValueError as error:
            parser.error(str(error))

    return args


def publish_mqtt(client: MqttClient | None, topic: str, message: dict) -> None:
    if client is None:
        return
    policy = TOPIC_POLICIES[topic]
    client.publish(topic, message, qos=policy.qos, retain=policy.retain)


def validate_control_stream_action(message: dict) -> str | None:
    if message.get("schema_version") != payloads.SCHEMA_VERSION:
        return None
    action = message.get("action")
    if action not in CONTROL_STREAM_ACTIONS:
        return None
    return str(action)


def require_tools(config: PlatformConfig) -> bool:
    missing = [path for path in (config.ffmpeg_path, config.mediamtx_path) if not path.is_file()]
    if not missing:
        return True

    print("Missing local tools:", file=sys.stderr)
    for path in missing:
        try:
            display_path = path.relative_to(PROJECT_ROOT)
        except ValueError:
            display_path = path
        print(f"  {display_path}", file=sys.stderr)
    if config.name == "macos-arm64" and not config.ffmpeg_path.is_file():
        print("Install FFmpeg with: brew install ffmpeg", file=sys.stderr)
    elif config.name == "linux-arm64" and not config.ffmpeg_path.is_file():
        print("Install FFmpeg and V4L2 tools with: sudo apt install -y ffmpeg v4l-utils", file=sys.stderr)
    print("Run: python scripts/setup_tools.py", file=sys.stderr)
    return False


def parse_windows_devices(output: str) -> list[CameraDevice]:
    return [CameraDevice(name, name) for name in re.findall(r'"(.+)" \(video\)', output)]


def parse_macos_devices(output: str) -> list[CameraDevice]:
    devices = []
    in_video_section = False
    for line in output.splitlines():
        if "AVFoundation video devices:" in line:
            in_video_section = True
            continue
        if "AVFoundation audio devices:" in line:
            break
        if in_video_section:
            match = re.search(r"\[(\d+)\][ \t]+(\S.*)\Z", line)
            if match:
                devices.append(CameraDevice(match.group(2).rstrip(), match.group(1)))
    return devices


def parse_linux_devices(output: str) -> list[CameraDevice]:
    devices = []
    display_name = "V4L2 camera"
    for line in output.splitlines():
        if line and not line[0].isspace() and line.rstrip().endswith(":"):
            display_name = line.strip().rstrip(":")
            continue
        device_path = line.strip()
        if device_path.startswith("/dev/video"):
            devices.append(CameraDevice(f"{display_name} ({device_path})", device_path))
    return devices


def get_video_devices(config: PlatformConfig) -> tuple[list[CameraDevice], int, str]:
    if config.name == "linux-arm64":
        try:
            result = subprocess.run(
                ["v4l2-ctl", "--list-devices"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError:
            return [], 1, "v4l2-ctl was not found. Install it with: sudo apt install -y v4l-utils"
        output = result.stdout or ""
        devices = parse_linux_devices(output)
        if devices:
            return devices, 0, output
        return [], result.returncode or 1, output

    command = [str(config.ffmpeg_path), "-hide_banner", "-f", config.capture_format]
    if config.name == "windows":
        command.extend(["-list_devices", "true", "-i", "dummy"])
    else:
        command.extend(["-list_devices", "true", "-i", ""])
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = result.stdout or ""
    devices = (
        parse_windows_devices(output)
        if config.name == "windows"
        else parse_macos_devices(output)
    )
    # FFmpeg can return a platform-specific non-zero status after successfully
    # listing capture devices. Parsed devices are the authoritative result.
    if devices:
        return devices, 0, output
    return [], result.returncode or 1, output


def print_device_query_diagnostic(output: str) -> None:
    if output.strip():
        print("FFmpeg device query output:", file=sys.stderr)
        print(output.rstrip(), file=sys.stderr)


def list_devices(config: PlatformConfig) -> int:
    devices, status, output = get_video_devices(config)
    if status:
        print_device_query_diagnostic(output)
        return status
    if not devices:
        print("No video devices found.", file=sys.stderr)
        return 1

    for index, device in enumerate(devices, start=1):
        print(f"{index}. {device.display_name}")
    return 0


def choose_device(devices: list[CameraDevice]) -> str | None:
    """Prompt for a camera and return its platform-specific FFmpeg input spec."""
    if not sys.stdin.isatty():
        print("Use --device when standard input is not interactive.", file=sys.stderr)
        return None

    print("Available cameras:")
    for index, device in enumerate(devices, start=1):
        print(f"  {index}. {device.display_name}")

    while True:
        try:
            choice = input("Select a camera number (or q to cancel): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if choice in {"q", "quit"}:
            return None
        try:
            device = devices[int(choice) - 1]
        except (ValueError, IndexError):
            print(f"Enter a number from 1 to {len(devices)}, or q to cancel.")
            continue
        return device.input_spec


def build_ffmpeg_command(args: argparse.Namespace, config: PlatformConfig) -> list[str]:
    """Build an RTSP publisher command without forcing duplicated output frames."""
    command = [
        str(config.ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "warning",
    ]
    if config.name == "windows":
        command.extend(["-rtbufsize", "100M", "-use_video_device_timestamps", "false"])
    command.extend(["-f", config.capture_format])
    if args.framerate:
        command.extend(["-framerate", str(args.framerate)])
    if args.video_size:
        command.extend(["-video_size", args.video_size])
    command.extend(
        [
            "-i",
            config.camera_input(args.device),
            "-an",
            "-c:v",
            config.video_encoder,
        ]
    )
    if config.name in {"windows", "linux-arm64"}:
        command.extend(["-preset", "ultrafast", "-tune", "zerolatency"])
    else:
        command.extend(["-realtime", "true", "-prio_speed", "true", "-bf", "0"])
    command.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(args.framerate or 30),
            "-b:v",
            args.bitrate,
            "-fps_mode",
            "passthrough",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            RTSP_URL,
        ]
    )
    return command


def wait_for_rtsp_server(process: subprocess.Popen[bytes]) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection((RTSP_HOST, RTSP_PORT), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def resolve_device(args: argparse.Namespace, config: PlatformConfig) -> int | None:
    if args.list_devices:
        return list_devices(config)
    if args.device:
        return None
    devices, status, output = get_video_devices(config)
    if status:
        print("Could not query video devices.", file=sys.stderr)
        print_device_query_diagnostic(output)
        return status
    if not devices:
        print("No video devices found.", file=sys.stderr)
        return 1
    args.device = choose_device(devices)
    return None if args.device is not None else 1


def handle_control_message(stop_requested: threading.Event, topic: str, message: dict) -> None:
    if topic != TOPIC_CONTROL_STREAM:
        return
    action = validate_control_stream_action(message)
    if action is None:
        print("Ignoring invalid MQTT stream control payload.", file=sys.stderr)
    elif action == "stop":
        print("Received MQTT stop command.")
        stop_requested.set()
    elif action in {"start", "restart"}:
        print(f"Received MQTT {action} command, but this process is already running.")
    else:
        print(f"Ignoring unsupported MQTT stream action: {action}", file=sys.stderr)


def connect_mqtt(args: argparse.Namespace, stop_requested: threading.Event) -> MqttClient | None:
    if not args.mqtt_host:
        return None
    client = MqttClient(
        host=args.mqtt_host,
        port=args.mqtt_port,
        client_id=args.mqtt_client_id,
        username=args.mqtt_username,
        password=password_from_env(args.mqtt_username, args.mqtt_password_env),
        on_message=lambda topic, message: handle_control_message(stop_requested, topic, message),
    )
    client.subscribe(TOPIC_CONTROL_STREAM, qos=TOPIC_POLICIES[TOPIC_CONTROL_STREAM].qos)
    client.connect()
    publish_mqtt(
        client,
        TOPIC_SYSTEM_STATUS,
        payloads.system_status(
            device_id=args.mqtt_client_id,
            component="rtsp-publisher",
            state="starting",
            message="RTSP publisher is starting.",
            metrics={"rtsp_url": RTSP_URL},
        ),
    )
    return client


def monitor_publisher(
    args: argparse.Namespace,
    mediamtx: subprocess.Popen[bytes],
    ffmpeg: subprocess.Popen[bytes],
    stop_requested: threading.Event,
    mqtt_client: MqttClient | None,
) -> int:
    last_heartbeat = 0.0
    while True:
        if mediamtx.poll() is not None:
            print("MediaMTX stopped unexpectedly.", file=sys.stderr)
            publish_mqtt(
                mqtt_client,
                TOPIC_ERROR_RTSP,
                payloads.error_event(
                    component="rtsp-publisher",
                    source=RTSP_URL,
                    message="MediaMTX stopped unexpectedly.",
                ),
            )
            return 1
        if ffmpeg.poll() is not None:
            print(
                "FFmpeg stopped unexpectedly. Check the FFmpeg error above for an "
                "invalid device name, busy camera, unsupported frame rate/size, encoder "
                "failure, or RTSP publish error.",
                file=sys.stderr,
            )
            publish_mqtt(
                mqtt_client,
                TOPIC_ERROR_RTSP,
                payloads.error_event(
                    component="rtsp-publisher",
                    source=RTSP_URL,
                    message="FFmpeg stopped unexpectedly.",
                    details={"returncode": ffmpeg.returncode},
                ),
            )
            return ffmpeg.returncode or 1
        if stop_requested.is_set():
            print("Stopping RTSP server from MQTT control command.")
            return 0
        now = time.monotonic()
        if now - last_heartbeat >= args.heartbeat_interval:
            last_heartbeat = now
            publish_mqtt(
                mqtt_client,
                TOPIC_SYSTEM_STATUS,
                payloads.system_status(
                    device_id=args.mqtt_client_id,
                    component="rtsp-publisher",
                    state="running",
                    metrics={
                        "rtsp_url": RTSP_URL,
                        "mediamtx_pid": mediamtx.pid,
                        "ffmpeg_pid": ffmpeg.pid,
                    },
                ),
            )
        time.sleep(0.25)


def main() -> int:
    args = parse_args()
    try:
        config = get_platform_config()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    if not require_tools(config):
        return 1
    device_status = resolve_device(args, config)
    if device_status is not None:
        return device_status

    stop_requested = threading.Event()
    try:
        mqtt_client = connect_mqtt(args, stop_requested)
    except MqttUnavailable as error:
        print(f"[MQTT] {error}", file=sys.stderr)
        return 1

    mediamtx: subprocess.Popen[bytes] | None = None
    ffmpeg: subprocess.Popen[bytes] | None = None

    try:
        mediamtx = subprocess.Popen([str(config.mediamtx_path), str(MEDIA_MTX_CONFIG)])
        if not wait_for_rtsp_server(mediamtx):
            print("MediaMTX did not start on 127.0.0.1:8554.", file=sys.stderr)
            publish_mqtt(
                mqtt_client,
                TOPIC_ERROR_RTSP,
                payloads.error_event(
                    component="rtsp-publisher",
                    source=RTSP_URL,
                    message="MediaMTX did not start.",
                ),
            )
            return 1

        ffmpeg = subprocess.Popen(build_ffmpeg_command(args, config))
        print(f"Publishing webcam at {RTSP_URL}")
        print("Press Ctrl+C to stop.")
        publish_mqtt(
            mqtt_client,
            TOPIC_SYSTEM_STATUS,
            payloads.system_status(
                device_id=args.mqtt_client_id,
                component="rtsp-publisher",
                state="running",
                metrics={
                    "rtsp_url": RTSP_URL,
                    "video_size": args.video_size,
                    "framerate": args.framerate,
                    "bitrate": args.bitrate,
                },
            ),
        )
        return monitor_publisher(args, mediamtx, ffmpeg, stop_requested, mqtt_client)
    except KeyboardInterrupt:
        print("Stopping RTSP server.")
        return 0
    finally:
        publish_mqtt(
            mqtt_client,
            TOPIC_SYSTEM_STATUS,
            payloads.system_status(
                device_id=args.mqtt_client_id,
                component="rtsp-publisher",
                state="stopping",
                message="RTSP publisher is stopping.",
            ),
        )
        stop_process(ffmpeg)
        stop_process(mediamtx)
        if mqtt_client is not None:
            mqtt_client.close()


if __name__ == "__main__":
    raise SystemExit(main())
