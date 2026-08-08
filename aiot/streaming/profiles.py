"""Deployment profile definitions and preflight checks for the RTSP publisher."""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from aiot.streaming.stream_platform import PlatformConfig
from aiot.streaming.stream_settings import RTSP_HOST, RTSP_PORT

RPI_CSI = "rpi-csi"
V4L2 = "v4l2"
AVFOUNDATION = "avfoundation"
DSHOW = "dshow"

PROFILE_CHOICES = (RPI_CSI, V4L2, AVFOUNDATION, DSHOW)
FFMPEG_PROFILES = (V4L2, AVFOUNDATION, DSHOW)


class ProfileValidationError(ValueError):
    """Raised when an explicit profile is invalid for the current platform."""


@dataclass(frozen=True)
class ProfileSpec:
    name: str
    system: str
    machines: tuple[str, ...] | None
    uses_ffmpeg: bool
    description: str


PROFILE_SPECS = {
    DSHOW: ProfileSpec(
        name=DSHOW,
        system="Windows",
        machines=("amd64", "x86_64"),
        uses_ffmpeg=True,
        description="Windows DirectShow webcam captured by FFmpeg",
    ),
    AVFOUNDATION: ProfileSpec(
        name=AVFOUNDATION,
        system="Darwin",
        machines=("arm64", "aarch64"),
        uses_ffmpeg=True,
        description="macOS AVFoundation camera captured by FFmpeg",
    ),
    V4L2: ProfileSpec(
        name=V4L2,
        system="Linux",
        machines=None,
        uses_ffmpeg=True,
        description="Linux Video4Linux2 camera captured by FFmpeg",
    ),
    RPI_CSI: ProfileSpec(
        name=RPI_CSI,
        system="Linux",
        machines=("aarch64", "arm64"),
        uses_ffmpeg=False,
        description=(
            "Raspberry Pi CSI camera published directly by MediaMTX "
            "with hardware H.264, no FFmpeg"
        ),
    ),
}


def profile_uses_ffmpeg(profile: str) -> bool:
    return PROFILE_SPECS[profile].uses_ffmpeg


def auto_detect_profile(system: str) -> str:
    if system == "Windows":
        return DSHOW
    if system == "Darwin":
        return AVFOUNDATION
    if system == "Linux":
        return V4L2
    raise ProfileValidationError(f"No supported publisher profile for platform {system!r}.")


def resolve_profile(profile: str | None, system: str, machine: str) -> str:
    """Return the effective profile, requiring an explicit choice when ambiguous.

    RPI_CSI is never auto-detected: on a Raspberry Pi the camera can be either
    a CSI module (rpi-csi) or a USB/V4L2 device (v4l2), so deploying to CSI
    hardware requires an explicit ``--profile rpi-csi``.
    """
    if profile is None:
        return auto_detect_profile(system)
    spec = PROFILE_SPECS.get(profile)
    if spec is None:
        raise ProfileValidationError(f"Unknown publisher profile {profile!r}.")
    if spec.system != system:
        raise ProfileValidationError(
            f"Profile {profile!r} requires {spec.system}, got {system}."
        )
    if spec.machines is not None and machine.lower() not in spec.machines:
        raise ProfileValidationError(
            f"Profile {profile!r} requires machine architecture "
            f"{', '.join(spec.machines)}, got {machine}."
        )
    return profile


def rpi_camera_tool() -> str | None:
    """Return the first available libcamera-apps camera tool, if any."""
    return shutil.which("rpicam-hello") or shutil.which("rpicam-vid")


def port_in_use(host: str = RTSP_HOST, port: int = RTSP_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def _rpi_enumeration_problems(tool: str) -> list[str]:
    result = subprocess.run(
        [tool, "--list-cameras"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=15,
    )
    output = (result.stdout or "").strip()
    if result.returncode != 0:
        return [
            f"Raspberry Pi camera enumeration failed with code "
            f"{result.returncode}: {output}"
        ]
    if "no cameras available" in output.lower():
        return [
            "Raspberry Pi camera enumeration found no cameras. "
            "Check the CSI cable and camera config: sudo raspi-config"
        ]
    return []


def preflight(
    profile: str,
    config: PlatformConfig,
    *,
    device: str | None = None,
    mediamtx_config: Path | None = None,
) -> list[str]:
    """Return environment problems for a profile, or an empty list when ready.

    The rpi-csi preflight does not require V4L2, FFmpeg, or libx264; it checks
    Linux ARM64 (enforced by resolve_profile), libcamera-apps, camera
    availability, MediaMTX, its configuration file, and the RTSP port.
    """
    problems: list[str] = []
    spec = PROFILE_SPECS[profile]
    if not config.mediamtx_path.is_file():
        problems.append(
            f"MediaMTX was not found at {config.mediamtx_path}. "
            "Run: python scripts/setup_tools.py"
        )
    if mediamtx_config is not None and not mediamtx_config.is_file():
        problems.append(f"MediaMTX configuration was not found at {mediamtx_config}.")
    if spec.uses_ffmpeg and not config.ffmpeg_path.is_file():
        if config.name == "macos-arm64":
            hint = "Install FFmpeg with: brew install ffmpeg"
        elif config.name == "linux-arm64":
            hint = "Install FFmpeg and V4L2 tools with: sudo apt install -y ffmpeg v4l-utils"
        else:
            hint = "Run: python scripts/setup_tools.py"
        problems.append(f"FFmpeg was not found at {config.ffmpeg_path}. {hint}")
    if profile == RPI_CSI:
        tool = rpi_camera_tool()
        if tool is None:
            problems.append(
                "Raspberry Pi camera tools were not found. "
                "Install with: sudo apt install -y rpicam-apps"
            )
        else:
            problems.extend(_rpi_enumeration_problems(tool))
        if port_in_use():
            problems.append(
                f"RTSP port {RTSP_PORT} is already in use by another process."
            )
    if profile == V4L2 and device and device.startswith("/"):
        if not Path(device).exists():
            problems.append(f"V4L2 device {device!r} does not exist.")
    return problems


def list_csi_cameras() -> int:
    """Print the camera list using the libcamera-apps tool and return a status code."""
    tool = rpi_camera_tool()
    if tool is None:
        print(
            "Raspberry Pi camera tools were not found. "
            "Install with: sudo apt install -y rpicam-apps",
            file=sys.stderr,
        )
        return 1
    result = subprocess.run(
        [tool, "--list-cameras"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=15,
    )
    print(result.stdout or "", end="")
    if result.returncode == 0:
        return 0
    print(
        f"Camera enumeration failed with code {result.returncode}.",
        file=sys.stderr,
    )
    return 1
