"""Publish a local webcam as a local-only RTSP stream."""

from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from stream_platform import PlatformConfig, get_platform_config
from stream_settings import RTSP_HOST, RTSP_PORT, RTSP_URL

PROJECT_ROOT = Path(__file__).parent
MEDIA_MTX_CONFIG = PROJECT_ROOT / "config" / "mediamtx.yml"


@dataclass(frozen=True)
class CameraDevice:
    display_name: str
    input_spec: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish a webcam to a local RTSP stream."
    )
    parser.add_argument("--device", help="Camera name on Windows or AVFoundation index on macOS.")
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
    args = parser.parse_args()

    if args.framerate is not None and args.framerate <= 0:
        parser.error("--framerate must be positive.")

    return args


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
            match = re.search(r"\[(\d+)\]\s+(.+)$", line)
            if match:
                devices.append(CameraDevice(match.group(2), match.group(1)))
    return devices


def get_video_devices(config: PlatformConfig) -> tuple[list[CameraDevice], int, str]:
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
    if config.name == "windows":
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


def main() -> int:
    args = parse_args()
    try:
        config = get_platform_config()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    if not require_tools(config):
        return 1
    if args.list_devices:
        return list_devices(config)
    if not args.device:
        devices, status, output = get_video_devices(config)
        if status:
            print("Could not query video devices.", file=sys.stderr)
            print_device_query_diagnostic(output)
            return status
        if not devices:
            print("No video devices found.", file=sys.stderr)
            return 1
        args.device = choose_device(devices)
        if args.device is None:
            return 1

    mediamtx = subprocess.Popen([str(config.mediamtx_path), str(MEDIA_MTX_CONFIG)])
    ffmpeg: subprocess.Popen[bytes] | None = None

    try:
        if not wait_for_rtsp_server(mediamtx):
            print("MediaMTX did not start on 127.0.0.1:8554.", file=sys.stderr)
            return 1

        ffmpeg = subprocess.Popen(build_ffmpeg_command(args, config))
        print(f"Publishing webcam at {RTSP_URL}")
        print("Press Ctrl+C to stop.")

        while True:
            if mediamtx.poll() is not None:
                print("MediaMTX stopped unexpectedly.", file=sys.stderr)
                return 1
            if ffmpeg.poll() is not None:
                print(
                    "FFmpeg stopped unexpectedly. Check the FFmpeg error above for an "
                    "invalid device name, busy camera, unsupported frame rate/size, encoder "
                    "failure, or RTSP publish error.",
                    file=sys.stderr,
                )
                return ffmpeg.returncode or 1
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("Stopping RTSP server.")
        return 0
    finally:
        stop_process(ffmpeg)
        stop_process(mediamtx)


if __name__ == "__main__":
    raise SystemExit(main())
