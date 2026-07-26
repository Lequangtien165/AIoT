"""Install pinned streaming tools for the current supported platform."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from stream_platform import get_platform_config, mediamtx_download_spec

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


def download(url: str, destination: Path) -> None:
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


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


def install_archive(
    url: str,
    checksum: str,
    destination: Path,
    executable: str,
    executable_checksum: str | None,
    force: bool,
    archive_type: str,
) -> None:
    executable_path = (
        destination / "bin" / executable if executable == "ffmpeg.exe" else destination / executable
    )
    if executable_path.is_file() and not force:
        if executable_checksum:
            try:
                verify_checksum(executable_path, executable_checksum)
            except RuntimeError:
                print(f"{destination.name} is present but failed verification; reinstalling.")
            else:
                print(f"{destination.name} is already installed and verified.")
                return
        else:
            print(f"{destination.name} is already installed from a verified archive.")
            return

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive = temp_path / f"download.{archive_type}"
        extracted = temp_path / "extracted"
        download(url, archive)
        verify_checksum(archive, checksum)
        print("Checksum verified.")

        if archive_type == "zip":
            with zipfile.ZipFile(archive) as zip_file:
                safe_extract(zip_file, extracted)
        else:
            with tarfile.open(archive, "r:gz") as tar_file:
                safe_extract_tar(tar_file, extracted)

        source = next(extracted.rglob(executable), None)
        if source is None:
            raise RuntimeError(f"Archive does not contain {executable}.")

        destination.mkdir(parents=True, exist_ok=True)
        if executable == "ffmpeg.exe":
            source_root = source.parent.parent
            shutil.copytree(source_root, destination, dirs_exist_ok=True)
        else:
            for file_path in source.parent.iterdir():
                if file_path.is_file():
                    shutil.copy2(file_path, destination / file_path.name)

        if not executable_path.is_file():
            raise RuntimeError(f"Installation did not create {executable_path}.")
        if os.name != "nt":
            executable_path.chmod(executable_path.stat().st_mode | stat.S_IXUSR)
        if executable_checksum:
            verify_checksum(executable_path, executable_checksum)
        print("Installation verified." if executable_checksum else "Archive verified and installed.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install pinned local streaming tools.")
    parser.add_argument("--force", action="store_true", help="Reinstall tools even when verified.")
    return parser.parse_args()


def verify_macos_ffmpeg(ffmpeg_path: Path) -> None:
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


def main() -> int:
    args = parse_args()
    try:
        config = get_platform_config()
        media_asset, archive_type, media_checksum = mediamtx_download_spec(config)
        media_url = (
            "https://github.com/bluenviron/mediamtx/releases/download/"
            f"v{MEDIA_MTX_VERSION}/mediamtx_v{MEDIA_MTX_VERSION}_{media_asset}"
        )
        install_archive(
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
                FFMPEG_URL,
                FFMPEG_SHA256,
                TOOLS_DIR / "ffmpeg",
                "ffmpeg.exe",
                FFMPEG_EXE_SHA256,
                args.force,
                "zip",
            )
        else:
            verify_macos_ffmpeg(config.ffmpeg_path)
    except (OSError, RuntimeError, urllib.error.URLError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"Tool setup failed: {error}", file=sys.stderr)
        return 1

    print("Tool setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
