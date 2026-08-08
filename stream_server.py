"""Publish a local webcam to a MediaMTX RTSP stream."""

from __future__ import annotations

import argparse
import platform
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from aiot.mqtt import payloads
from aiot.mqtt.client import (
    MqttClient,
    MqttConnectionError,
    MqttPublishError,
    MqttSubscriptionError,
    MqttUnavailable,
    password_from_env,
)
from aiot.mqtt.topics import (
    TOPIC_CONTROL_STREAM,
    TOPIC_MOTION_DETECTED,
    control_stream_topic,
    error_rtsp_topic,
    system_status_topic,
    topic_policy,
    stream_activity_topic,
)
from aiot.streaming.edge_session import EdgeSessionController, EdgeSessionState
from aiot.streaming.motion_detector import MotionDetector
from aiot.streaming.profiles import (
    PROFILE_CHOICES,
    RPI_CSI,
    ProfileValidationError,
    list_csi_cameras,
    preflight,
    profile_uses_ffmpeg,
    resolve_profile,
)
from aiot.streaming.stream_platform import PlatformConfig, get_platform_config
from aiot.streaming.stream_settings import RTSP_HOST, RTSP_PORT, RTSP_URL

PROJECT_ROOT = Path(__file__).parent
MEDIA_MTX_CONFIG = PROJECT_ROOT / "config" / "mediamtx.yml"
MEDIA_MTX_RPI_CONFIG = PROJECT_ROOT / "config" / "mediamtx-rpi.yml"
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
        "--profile",
        choices=PROFILE_CHOICES,
        help=(
            "Explicit capture/deployment profile. Auto-detected by default: "
            "dshow on Windows, avfoundation on macOS, v4l2 on Linux. "
            "rpi-csi (Raspberry Pi CSI camera, direct MediaMTX publishing) is never "
            "auto-detected because a Raspberry Pi camera can be CSI or USB/V4L2."
        ),
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
    parser.add_argument("--mqtt-ca-cert", help="CA certificate path for TLS MQTT connections.")
    parser.add_argument(
        "--no-mqtt",
        action="store_true",
        help="Disable the publisher MQTT client when controlled by run_edge_agent.py.",
    )
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--motion-triggered", action="store_true", help="Start RTSP sessions only after significant motion.")
    parser.add_argument("--motion-device", help="OpenCV camera index/path used while monitoring; defaults to --device.")
    parser.add_argument("--motion-width", type=int, default=320)
    parser.add_argument("--motion-height", type=int, default=240)
    parser.add_argument("--motion-fps", type=float, default=5.0)
    parser.add_argument("--motion-area-threshold", type=float, default=0.02)
    parser.add_argument("--motion-window-size", type=int, default=5)
    parser.add_argument("--motion-trigger-frames", type=int, default=3)
    parser.add_argument("--motion-warmup", type=float, default=2.0)
    parser.add_argument("--face-discovery-timeout", type=float, default=30.0)
    parser.add_argument("--face-keepalive-timeout", type=float, default=120.0)
    args = parser.parse_args()

    if args.framerate is not None and args.framerate <= 0:
        parser.error("--framerate must be positive.")
    if args.mqtt_port <= 0 or args.heartbeat_interval <= 0:
        parser.error("--mqtt-port and --heartbeat-interval must be positive.")
    if args.motion_width <= 0 or args.motion_height <= 0 or args.motion_fps <= 0:
        parser.error("motion width, height, and fps must be positive.")
    if not 0 < args.motion_area_threshold <= 1 or args.motion_window_size <= 0:
        parser.error("motion area threshold must be in (0, 1] and window size must be positive.")
    if not 0 < args.motion_trigger_frames <= args.motion_window_size:
        parser.error("motion trigger frames must be within the motion window.")
    if args.motion_warmup < 0 or args.face_discovery_timeout <= 0 or args.face_keepalive_timeout <= 0:
        parser.error("motion warmup must be non-negative and session timeouts must be positive.")
    if args.mqtt_username:
        try:
            password_from_env(args.mqtt_username, args.mqtt_password_env)
        except ValueError as error:
            parser.error(str(error))

    return args


def publish_mqtt(client: MqttClient | None, topic: str, message: dict) -> None:
    if client is None:
        return
    policy = topic_policy(topic)
    try:
        client.publish(topic, message, qos=policy.qos, retain=policy.retain)
    except MqttPublishError as error:
        print(f"[MQTT] {error}", file=sys.stderr)


def validate_control_stream_action(message: dict, device_id: str) -> str | None:
    if message.get("schema_version") != payloads.SCHEMA_VERSION:
        return None
    if message.get("target_device_id") != device_id:
        return None
    action = message.get("action")
    if action not in CONTROL_STREAM_ACTIONS:
        return None
    return str(action)


def select_mediamtx_config(profile: str) -> Path:
    """Return the MediaMTX configuration file for a deployment profile."""
    return MEDIA_MTX_RPI_CONFIG if profile == RPI_CSI else MEDIA_MTX_CONFIG


def run_preflight(profile: str, config: PlatformConfig, device: str | None) -> int:
    """Run profile preflight checks, printing any problems. Returns 0 when ready."""
    problems = preflight(
        profile,
        config,
        device=device,
        mediamtx_config=select_mediamtx_config(profile),
    )
    if not problems:
        return 0
    print("Preflight checks failed:", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    return 1


def parse_windows_devices(output: str) -> list[CameraDevice]:
    devices: list[CameraDevice] = []
    in_video_section = False
    for line in output.splitlines():
        if "Alternative name" in line or "alternative name" in line:
            continue
        # New FFmpeg format tags each device, e.g. "OBS Virtual Camera" (none)
        # or "Integrated Camera" (video); audio devices are tagged (audio).
        match = re.search(r'"(.+)" \((?:video|none)\)', line)
        if match:
            devices.append(CameraDevice(match.group(1), match.group(1)))
            continue
        if "video devices" in line:
            in_video_section = True
            continue
        if "audio devices" in line or "(audio)" in line:
            in_video_section = False
            continue
        # Legacy format prints bare quoted names between the video and audio
        # section headers, e.g. "Integrated Camera" on its own line.
        if in_video_section:
            match = re.search(r'"(.+)"', line)
            if match:
                devices.append(CameraDevice(match.group(1), match.group(1)))
    return devices


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


def request_stop(signum, frame) -> None:
    """Convert SIGTERM into KeyboardInterrupt so publisher cleanup always runs.

    The motion-triggered loop clears the stop flag after a session, so a
    flag-only handler would not terminate the process. Raising
    KeyboardInterrupt propagates through both the continuous and the
    motion-triggered loops into the existing handler in main().
    """
    raise KeyboardInterrupt


def install_signal_handlers() -> None:
    sigterm = getattr(signal, "SIGTERM", None)
    if sigterm is not None:
        signal.signal(sigterm, request_stop)


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


def resolve_device(args: argparse.Namespace, config: PlatformConfig, profile: str) -> int | None:
    if profile == RPI_CSI:
        if args.list_devices:
            return list_csi_cameras()
        return None
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


def handle_control_message(stop_requested: threading.Event, device_id: str, topic: str, message: dict) -> None:
    if topic != control_stream_topic(device_id):
        return
    action = validate_control_stream_action(message, device_id)
    if action is None:
        print("Ignoring invalid MQTT stream control payload.", file=sys.stderr)
    elif action == "stop":
        print("Received MQTT stop command.")
        stop_requested.set()
    elif action in {"start", "restart"}:
        print(f"Received MQTT {action} command, but this process is already running.")
    else:
        print(f"Ignoring unsupported MQTT stream action: {action}", file=sys.stderr)


def connect_mqtt(args: argparse.Namespace, stop_requested: threading.Event, session=None) -> MqttClient | None:
    if not args.mqtt_host:
        return None
    client = MqttClient(
        host=args.mqtt_host,
        port=args.mqtt_port,
        client_id=args.mqtt_client_id,
        username=args.mqtt_username,
        password=password_from_env(args.mqtt_username, args.mqtt_password_env),
        ca_cert=args.mqtt_ca_cert,
        on_message=lambda topic, message: handle_control_message(stop_requested, args.mqtt_client_id, topic, message),
        on_message_metadata=lambda topic, message, retained: handle_session_activity(
            session, args.mqtt_client_id, topic, message, retained
        ),
    )
    client.subscribe(control_stream_topic(args.mqtt_client_id), qos=topic_policy(TOPIC_CONTROL_STREAM).qos)
    if session is not None:
        client.subscribe(stream_activity_topic(args.mqtt_client_id), qos=1)
    client.connect()
    publish_mqtt(
        client,
        system_status_topic(args.mqtt_client_id),
        payloads.system_status(
            device_id=args.mqtt_client_id,
            component="rtsp-publisher",
            state="starting",
            message="RTSP publisher is starting.",
            metrics={"rtsp_url": RTSP_URL},
        ),
    )
    return client


def handle_session_activity(session, device_id: str, topic: str, message: dict, retained: bool) -> None:
    if session is None or retained or topic != stream_activity_topic(device_id):
        return
    if message.get("schema_version") != payloads.SCHEMA_VERSION or message.get("device_id") != device_id:
        return
    if message.get("action") != "face_presence":
        return
    if session.face_presence(message.get("stream_session_id", ""), message.get("face_count")):
        print(
            f"[MQTT] face_presence accepted session={message['stream_session_id']} "
            f"faces={message['face_count']} lease={session.keepalive_timeout:.0f}s"
        )


def run_motion_triggered(args, config, mediamtx, stop_requested, mqtt_client, session) -> int:
    detector_device = args.motion_device or args.device
    if config.name in {"windows", "macos-arm64"} and not str(detector_device).isdigit():
        print("--motion-device must be an OpenCV camera index on Windows/macOS.", file=sys.stderr)
        return 1
    if str(detector_device).isdigit():
        detector_device = int(detector_device)
    while not stop_requested.is_set():
        detector = MotionDetector(detector_device, width=args.motion_width, height=args.motion_height, fps=args.motion_fps,
                                  area_threshold=args.motion_area_threshold, window_size=args.motion_window_size,
                                  trigger_frames=args.motion_trigger_frames, warmup_seconds=args.motion_warmup)
        print(
            f"[MOTION] monitoring device={detector_device} size={args.motion_width}x{args.motion_height} "
            f"fps={args.motion_fps:g} threshold={args.motion_area_threshold:.3f} "
            f"trigger={args.motion_trigger_frames}/{args.motion_window_size}"
        )
        try:
            if not detector.wait_for_motion(stop_requested):
                break
        except RuntimeError as error:
            print(f"Motion detector failed: {error}", file=sys.stderr)
            return 1
        session_id = session.begin()
        print(f"[MOTION] triggered; starting session={session_id}")
        publish_mqtt(mqtt_client, TOPIC_MOTION_DETECTED, payloads.motion_detected(device_id=args.mqtt_client_id, sensor_id="software-motion", active=True))
        publish_mqtt(mqtt_client, system_status_topic(args.mqtt_client_id), payloads.system_status(device_id=args.mqtt_client_id, component="rtsp-publisher", state="starting", stream_session_id=session_id))
        ffmpeg = subprocess.Popen(build_ffmpeg_command(args, config))
        print(f"[RTSP] publisher starting pid={ffmpeg.pid} session={session_id}")
        time.sleep(1.0)
        if ffmpeg.poll() is not None:
            print(f"[RTSP] publisher failed during startup session={session_id}", file=sys.stderr)
            publish_mqtt(mqtt_client, error_rtsp_topic(args.mqtt_client_id), payloads.error_event(component="rtsp-publisher", device_id=args.mqtt_client_id, message="FFmpeg did not start."))
            session.complete_stop()
            continue
        session.publisher_ready()
        print(
            f"[SESSION] state=streaming device={args.mqtt_client_id} session={session_id} "
            f"discovery_timeout={session.discovery_timeout:.0f}s"
        )
        publish_mqtt(mqtt_client, system_status_topic(args.mqtt_client_id), payloads.system_status(device_id=args.mqtt_client_id, component="rtsp-publisher", state="streaming", stream_session_id=session_id, metrics={"rtsp_url": RTSP_URL}))
        while ffmpeg.poll() is None and mediamtx.poll() is None and not stop_requested.is_set() and not session.expired():
            time.sleep(0.25)
        if session.expired():
            print(f"[SESSION] lease expired session={session_id}; stopping publisher")
        elif stop_requested.is_set():
            print(f"[SESSION] stop command received; ending session={session_id}")
        else:
            print(f"[RTSP] publisher or MediaMTX exited for session={session_id}", file=sys.stderr)
        stop_process(ffmpeg)
        session.complete_stop()
        publish_mqtt(mqtt_client, TOPIC_MOTION_DETECTED, payloads.motion_detected(device_id=args.mqtt_client_id, sensor_id="software-motion", active=False))
        publish_mqtt(mqtt_client, system_status_topic(args.mqtt_client_id), payloads.system_status(device_id=args.mqtt_client_id, component="rtsp-publisher", state="monitoring"))
        print(f"[SESSION] state=monitoring device={args.mqtt_client_id}")
        if stop_requested.is_set():
            stop_requested.clear()
    return 0


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
                error_rtsp_topic(args.mqtt_client_id),
                payloads.error_event(
                    component="rtsp-publisher",
                    source=RTSP_URL,
                    message="MediaMTX stopped unexpectedly.",
                ),
            )
            return 1
        if ffmpeg is not None and ffmpeg.poll() is not None:
            print(
                "FFmpeg stopped unexpectedly. Check the FFmpeg error above for an "
                "invalid device name, busy camera, unsupported frame rate/size, encoder "
                "failure, or RTSP publish error.",
                file=sys.stderr,
            )
            publish_mqtt(
                mqtt_client,
                error_rtsp_topic(args.mqtt_client_id),
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
            metrics: dict[str, object] = {
                "rtsp_url": RTSP_URL,
                "mediamtx_pid": mediamtx.pid,
            }
            if ffmpeg is not None:
                metrics["ffmpeg_pid"] = ffmpeg.pid
            publish_mqtt(
                mqtt_client,
                system_status_topic(args.mqtt_client_id),
                payloads.system_status(
                    device_id=args.mqtt_client_id,
                    component="rtsp-publisher",
                    state="running",
                    metrics=metrics,
                ),
            )
        time.sleep(0.25)


def main() -> int:
    args = parse_args()
    install_signal_handlers()
    try:
        config = get_platform_config()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    try:
        profile = resolve_profile(args.profile, platform.system(), platform.machine())
    except ProfileValidationError as error:
        print(error, file=sys.stderr)
        return 1
    if args.motion_triggered and profile == RPI_CSI:
        print(
            "--motion-triggered is not supported with the rpi-csi profile: "
            "MediaMTX owns the camera through libcamera while motion detection "
            "needs an OpenCV/V4L2 device. Use the v4l2 profile with a USB camera.",
            file=sys.stderr,
        )
        return 1
    if run_preflight(profile, config, args.device) != 0:
        return 1
    device_status = resolve_device(args, config, profile)
    if device_status is not None:
        return device_status

    stop_requested = threading.Event()
    session = EdgeSessionController(args.face_discovery_timeout, args.face_keepalive_timeout) if args.motion_triggered else None
    try:
        mqtt_client = None if args.no_mqtt else connect_mqtt(args, stop_requested, session)
    except (MqttUnavailable, MqttConnectionError, MqttSubscriptionError) as error:
        print(f"[MQTT] {error}", file=sys.stderr)
        return 1

    mediamtx: subprocess.Popen[bytes] | None = None
    ffmpeg: subprocess.Popen[bytes] | None = None

    try:
        mediamtx_config = select_mediamtx_config(profile)
        mediamtx = subprocess.Popen([str(config.mediamtx_path), str(mediamtx_config)])
        if not wait_for_rtsp_server(mediamtx):
            print("MediaMTX did not start on 127.0.0.1:8554.", file=sys.stderr)
            publish_mqtt(
                mqtt_client,
                error_rtsp_topic(args.mqtt_client_id),
                payloads.error_event(
                    component="rtsp-publisher",
                    source=RTSP_URL,
                    message="MediaMTX did not start.",
                ),
            )
            return 1

        if args.motion_triggered:
            return run_motion_triggered(args, config, mediamtx, stop_requested, mqtt_client, session)
        if profile_uses_ffmpeg(profile):
            ffmpeg = subprocess.Popen(build_ffmpeg_command(args, config))
        print(f"Publishing webcam at {RTSP_URL} (profile: {profile})")
        print("Press Ctrl+C to stop.")
        publish_mqtt(
            mqtt_client,
            system_status_topic(args.mqtt_client_id),
            payloads.system_status(
                device_id=args.mqtt_client_id,
                component="rtsp-publisher",
                state="running",
                metrics={
                    "rtsp_url": RTSP_URL,
                    "profile": profile,
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
            system_status_topic(args.mqtt_client_id),
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
