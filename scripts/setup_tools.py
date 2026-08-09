"""Install pinned streaming tools for the current supported platform."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import certifi


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from aiot.streaming.stream_platform import get_platform_config, mediamtx_download_spec

TOOLS_DIR = PROJECT_ROOT / "tools"

MEDIA_MTX_VERSION = "1.19.3"
MEDIA_MTX_EXE_SHA256 = "1cda85249312cb9463f9f94c5a712b9f160c9af3fd9490f0d4723911d7880e05"

FFMPEG_VERSION = "8.1.2"
FFMPEG_URL = (
    "https://www.gyan.dev/ffmpeg/builds/packages/"
    f"ffmpeg-{FFMPEG_VERSION}-essentials_build.zip"
)
FFMPEG_SHA256 = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"
FFMPEG_EXE_SHA256 = "1326dde4c84ff1f96fe6b8916c5bed29e163e9b5dccf995f6f3db069d143ec5e"
FFMPEG_EXECUTABLE = "ffmpeg.exe"
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


def download_ssl_context() -> ssl.SSLContext:
    """Use certifi so Python's trust store works consistently on macOS."""
    context = ssl.create_default_context(cafile=certifi.where())
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def format_size(size: float) -> str:
    """Format a byte count for concise terminal status messages."""
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size:.0f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def download(url: str, destination: Path) -> None:
    """Download a file while providing useful progress in terminals and logs."""
    context = download_ssl_context()
    with urllib.request.urlopen(url, context=context) as response, destination.open("wb") as output:
        content_length = response.headers.get("Content-Length")
        try:
            total = int(content_length) if content_length else None
        except ValueError:
            total = None

        downloaded = 0
        last_reported_percent = -1
        last_reported_bytes = 0
        started = time.monotonic()
        interactive = sys.stdout.isatty()

        while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
            output.write(chunk)
            downloaded += len(chunk)
            elapsed = max(time.monotonic() - started, 0.001)
            speed = downloaded / elapsed

            if total:
                percent = min(int(downloaded * 100 / total), 100)
                if interactive:
                    filled = percent // 5
                    bar = "=" * filled + " " * (20 - filled)
                    eta = max(total - downloaded, 0) / speed
                    message = (
                        f"\r  [{bar}] {percent:3d}% {format_size(downloaded)}/"
                        f"{format_size(total)} {format_size(speed)}/s ETA {eta:.0f}s"
                    )
                    print(message, end="", flush=True)
                elif percent >= last_reported_percent + 10 or percent == 100:
                    print(f"  {percent:3d}% {format_size(downloaded)}/{format_size(total)}")
                    last_reported_percent = percent
            elif interactive:
                print(
                    f"\r  {format_size(downloaded)} downloaded {format_size(speed)}/s",
                    end="",
                    flush=True,
                )
            elif downloaded >= last_reported_bytes + 10 * 1024 * 1024:
                print(f"  {format_size(downloaded)} downloaded")
                last_reported_bytes = downloaded

        if interactive:
            print()
        elif not total or last_reported_percent != 100:
            print(f"  Downloaded {format_size(downloaded)}")


def verify_checksum(path: Path, expected: str) -> None:
    with path.open("rb") as file:
        actual = hashlib.file_digest(file, "sha256").hexdigest()
    if actual != expected:
        raise RuntimeError(f"Checksum mismatch for {path.name}: {actual}")


def safe_extract(zip_file: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in zip_file.infolist():
        target = (destination / member.filename).resolve()
        if not target.is_relative_to(root):
            raise RuntimeError(f"Archive contains unsafe path: {member.filename}")
    zip_file.extractall(destination)


def safe_extract_tar(tar_file: tarfile.TarFile, destination: Path) -> None:
    root = destination.resolve()
    for member in tar_file.getmembers():
        target = (destination / member.name).resolve()
        if not target.is_relative_to(root):
            raise RuntimeError(f"Archive contains unsafe path: {member.name}")
    tar_file.extractall(destination, filter="data")


def executable_path(destination: Path, executable: str) -> Path:
    if executable == FFMPEG_EXECUTABLE:
        return destination / "bin" / executable
    return destination / executable


def existing_install_is_valid(path: Path, checksum: str | None) -> bool:
    if not path.is_file():
        return False
    print("  Checking existing installation...")
    if checksum is None:
        print(f"  Already installed from a verified archive: {path}")
        return True
    try:
        verify_checksum(path, checksum)
    except RuntimeError:
        print("  Existing installation failed verification; reinstalling.")
        return False
    print(f"  Already installed and verified: {path}")
    return True


def extract_archive(archive: Path, extracted: Path, archive_type: str) -> None:
    if archive_type == "zip":
        with zipfile.ZipFile(archive) as zip_file:
            safe_extract(zip_file, extracted)
        return
    with tarfile.open(archive, "r:gz") as tar_file:
        safe_extract_tar(tar_file, extracted)


def install_extracted_files(source: Path, destination: Path, executable: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if executable == FFMPEG_EXECUTABLE:
        shutil.copytree(source.parent.parent, destination, dirs_exist_ok=True)
        return
    for file_path in source.parent.iterdir():
        if file_path.is_file():
            shutil.copy2(file_path, destination / file_path.name)


def verify_installed_executable(path: Path, checksum: str | None) -> None:
    if not path.is_file():
        raise RuntimeError(f"Installation did not create {path}.")
    if os.name != "nt":
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    if checksum:
        print("  Verifying installation...")
        verify_checksum(path, checksum)


def install_archive(
    stage: str,
    tool_name: str,
    url: str,
    checksum: str,
    destination: Path,
    executable: str,
    executable_checksum: str | None,
    force: bool,
    archive_type: str,
) -> None:
    print(f"{stage} {tool_name}")
    installed_executable = executable_path(destination, executable)
    if not force and existing_install_is_valid(installed_executable, executable_checksum):
        return

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive = temp_path / f"download.{archive_type}"
        extracted = temp_path / "extracted"
        print("  Downloading...")
        download(url, archive)
        print("  Verifying archive checksum...")
        verify_checksum(archive, checksum)
        print("  Extracting archive...")
        extract_archive(archive, extracted, archive_type)
        source = next(extracted.rglob(executable), None)
        if source is None:
            raise RuntimeError(f"Archive does not contain {executable}.")
        print(f"  Installing to {destination.relative_to(PROJECT_ROOT)}...")
        install_extracted_files(source, destination, executable)
        verify_installed_executable(installed_executable, executable_checksum)
        print(f"  Installed successfully: {installed_executable}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install pinned local streaming tools.")
    parser.add_argument("--force", action="store_true", help="Reinstall tools even when verified.")
    return parser


def parse_args() -> argparse.Namespace:
    return build_parser().parse_args()


def verify_macos_ffmpeg(ffmpeg_path: Path) -> None:
    print("[1/2] Homebrew FFmpeg")
    print("  Checking AVFoundation and h264_videotoolbox support...")
    if not ffmpeg_path.is_file():
        raise RuntimeError("FFmpeg is missing. Install it with: brew install ffmpeg")

    devices = subprocess.run(
        [str(ffmpeg_path), "-hide_banner", "-devices"],
        capture_output=True,
        check=False,
        text=True,
    )
    encoders = subprocess.run(
        [str(ffmpeg_path), "-hide_banner", "-encoders"],
        capture_output=True,
        check=False,
        text=True,
    )
    if devices.returncode or "avfoundation" not in devices.stdout.lower():
        raise RuntimeError("Homebrew FFmpeg does not provide the AVFoundation input device.")
    if encoders.returncode or "h264_videotoolbox" not in encoders.stdout.lower():
        raise RuntimeError("Homebrew FFmpeg does not provide the h264_videotoolbox encoder.")
    print(f"Homebrew FFmpeg verified: {ffmpeg_path}")


def verify_linux_ffmpeg(ffmpeg_path: Path) -> None:
    print("[1/2] System FFmpeg")
    print("  Checking V4L2 input and libx264 encoder support...")
    if not ffmpeg_path.is_file():
        raise RuntimeError("FFmpeg is missing. Install it with: sudo apt install -y ffmpeg")

    devices = subprocess.run(
        [str(ffmpeg_path), "-hide_banner", "-devices"],
        capture_output=True,
        check=False,
        text=True,
    )
    encoders = subprocess.run(
        [str(ffmpeg_path), "-hide_banner", "-encoders"],
        capture_output=True,
        check=False,
        text=True,
    )
    if devices.returncode or "v4l2" not in devices.stdout.lower():
        raise RuntimeError("System FFmpeg does not provide the V4L2 input device.")
    if encoders.returncode or "libx264" not in encoders.stdout.lower():
        raise RuntimeError("System FFmpeg does not provide the libx264 encoder.")
    print(f"System FFmpeg verified: {ffmpeg_path}")


def main() -> int:
    args = parse_args()
    try:
        config = get_platform_config()
        media_asset, archive_type, media_checksum = mediamtx_download_spec(config)
        media_url = (
            "https://github.com/bluenviron/mediamtx/releases/download/"
            f"v{MEDIA_MTX_VERSION}/mediamtx_v{MEDIA_MTX_VERSION}_{media_asset}"
        )
        platform_name = {
            "windows": "Windows AMD64",
            "macos-arm64": "macOS Apple Silicon",
            "linux-arm64": "Linux ARM64",
        }[config.name]
        print(f"Platform: {platform_name}")
        print("Install plan:")
        if config.name == "windows":
            print(f"  [1/2] MediaMTX v{MEDIA_MTX_VERSION} -> {TOOLS_DIR / 'mediamtx'}")
            print(f"  [2/2] FFmpeg v{FFMPEG_VERSION} -> {TOOLS_DIR / 'ffmpeg'}")
        elif config.name == "macos-arm64":
            print(f"  [1/2] Verify Homebrew FFmpeg -> {config.ffmpeg_path}")
            print(f"  [2/2] MediaMTX v{MEDIA_MTX_VERSION} -> {TOOLS_DIR / 'mediamtx'}")
        else:
            print(f"  [1/2] Verify system FFmpeg -> {config.ffmpeg_path}")
            print(f"  [2/2] MediaMTX v{MEDIA_MTX_VERSION} -> {TOOLS_DIR / 'mediamtx'}")

        if config.name == "macos-arm64":
            verify_macos_ffmpeg(config.ffmpeg_path)
        elif config.name == "linux-arm64":
            verify_linux_ffmpeg(config.ffmpeg_path)
        install_archive(
            "[1/2]" if config.name == "windows" else "[2/2]",
            f"MediaMTX v{MEDIA_MTX_VERSION}",
            media_url,
            media_checksum,
            TOOLS_DIR / "mediamtx",
            config.mediamtx_path.name,
            MEDIA_MTX_EXE_SHA256 if config.name == "windows" else None,
            args.force,
            archive_type,
        )
        if config.name == "windows":
            install_archive(
                "[2/2]",
                f"FFmpeg v{FFMPEG_VERSION}",
                FFMPEG_URL,
                FFMPEG_SHA256,
                TOOLS_DIR / "ffmpeg",
                FFMPEG_EXECUTABLE,
                FFMPEG_EXE_SHA256,
                args.force,
                "zip",
            )
    except (OSError, RuntimeError, urllib.error.URLError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"Tool setup failed: {error}", file=sys.stderr)
        return 1

    print("Tool setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
