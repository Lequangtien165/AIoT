"""Platform-specific settings for the local webcam RTSP publisher."""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent


@dataclass(frozen=True)
class PlatformConfig:
    name: str
    capture_format: str
    video_encoder: str
    ffmpeg_path: Path
    mediamtx_path: Path

    def camera_input(self, device: str) -> str:
        if self.name == "windows":
            return f"video={device}"
        return device if ":" in device else f"{device}:none"


def get_platform_config(
    system: str | None = None, machine: str | None = None
) -> PlatformConfig:
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()

    if system == "Windows" and machine in {"amd64", "x86_64"}:
        return PlatformConfig(
            name="windows",
            capture_format="dshow",
            video_encoder="libx264",
            ffmpeg_path=PROJECT_ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
            mediamtx_path=PROJECT_ROOT / "tools" / "mediamtx" / "mediamtx.exe",
        )

    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        homebrew_ffmpeg = Path("/opt/homebrew/bin/ffmpeg")
        ffmpeg_path = homebrew_ffmpeg if homebrew_ffmpeg.is_file() else Path(
            shutil.which("ffmpeg") or "ffmpeg"
        )
        return PlatformConfig(
            name="macos-arm64",
            capture_format="avfoundation",
            video_encoder="h264_videotoolbox",
            ffmpeg_path=ffmpeg_path,
            mediamtx_path=PROJECT_ROOT / "tools" / "mediamtx" / "mediamtx",
        )

    raise RuntimeError(
        "Unsupported platform. This project supports Windows AMD64 and macOS Apple Silicon (arm64)."
    )


def mediamtx_download_spec(config: PlatformConfig) -> tuple[str, str, str]:
    """Return the pinned MediaMTX asset suffix, archive type, and archive hash."""
    if config.name == "windows":
        return (
            "windows_amd64.zip",
            "zip",
            "5d82148d1032a6a190d9909a2997d9989457aaadf49af87dd02cd4512d31bebe",
        )
    if config.name == "macos-arm64":
        return (
            "darwin_arm64.tar.gz",
            "tar.gz",
            "b57e9e2f2fe418b37048ab613ae05fb744ac260dbc3f2ba63a64f9f6cf00156e",
        )
    raise RuntimeError(f"Unsupported MediaMTX platform: {config.name}")
