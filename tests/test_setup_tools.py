import hashlib
import io
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from aiot.streaming.stream_platform import PlatformConfig
from scripts.setup_tools import (
    certifi,
    download,
    download_ssl_context,
    install_archive,
    main,
    safe_extract,
    ssl,
    verify_linux_ffmpeg,
    verify_checksum,
)


class FakeResponse:
    def __init__(self, content: bytes, content_length: str | None = None):
        self.content = io.BytesIO(content)
        self.headers = {} if content_length is None else {"Content-Length": content_length}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int) -> bytes:
        return self.content.read(size)


class ChecksumTests(unittest.TestCase):
    @patch("scripts.setup_tools.ssl.create_default_context")
    @patch("scripts.setup_tools.certifi.where", return_value="/tmp/certifi.pem")
    def test_download_context_uses_certifi_bundle(self, certifi_where, create_context):
        download_ssl_context()

        certifi_where.assert_called_once_with()
        create_context.assert_called_once_with(cafile="/tmp/certifi.pem")

    def test_checksum_accepts_matching_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "tool.exe"
            file_path.write_bytes(b"verified")

            verify_checksum(file_path, hashlib.sha256(b"verified").hexdigest())

    def test_checksum_rejects_mismatched_file_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "tool.exe"
            file_path.write_bytes(b"unverified")

            with self.assertRaises(RuntimeError):
                verify_checksum(file_path, "0" * 64)
            self.assertTrue(file_path.exists())

    def test_safe_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("../escape.txt", "no")

            with zipfile.ZipFile(archive) as zip_file:
                with self.assertRaises(RuntimeError):
                    safe_extract(zip_file, root / "extract")


class DownloadTests(unittest.TestCase):
    @patch("scripts.setup_tools.urllib.request.urlopen")
    def test_download_writes_content_and_reports_non_tty_milestones(self, urlopen):
        content = b"a" * (2 * 1024 * 1024)
        urlopen.return_value = FakeResponse(content, str(len(content)))

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "tool.zip"
            output = io.StringIO()
            with redirect_stdout(output):
                download("https://example.com/tool.zip", destination)

            self.assertEqual(destination.read_bytes(), content)

        self.assertIn("  50%", output.getvalue())
        self.assertIn("100%", output.getvalue())

    @patch("scripts.setup_tools.urllib.request.urlopen")
    def test_download_handles_missing_content_length(self, urlopen):
        urlopen.return_value = FakeResponse(b"archive")

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "tool.zip"
            output = io.StringIO()
            with redirect_stdout(output):
                download("https://example.com/tool.zip", destination)

            self.assertEqual(destination.read_bytes(), b"archive")

        self.assertIn("Downloaded 7 B", output.getvalue())

    @patch("scripts.setup_tools.urllib.request.urlopen")
    def test_download_handles_invalid_content_length(self, urlopen):
        urlopen.return_value = FakeResponse(b"archive", "unknown")

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "tool.zip"
            with redirect_stdout(io.StringIO()):
                download("https://example.com/tool.zip", destination)

            self.assertEqual(destination.read_bytes(), b"archive")


class InstallArchiveTests(unittest.TestCase):
    def test_existing_verified_archive_is_reported_without_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "mediamtx"
            destination.mkdir()
            executable = destination / "mediamtx"
            executable.write_bytes(b"installed")
            output = io.StringIO()

            with redirect_stdout(output):
                install_archive(
                    "[1/1]",
                    "MediaMTX v1.19.3",
                    "https://example.com/mediamtx.tar.gz",
                    "unused",
                    destination,
                    "mediamtx",
                    None,
                    False,
                    "tar.gz",
                )

        self.assertIn("[1/1] MediaMTX v1.19.3", output.getvalue())
        self.assertIn("Already installed from a verified archive", output.getvalue())


class SetupOrderingTests(unittest.TestCase):
    @patch("scripts.setup_tools.install_archive")
    @patch("scripts.setup_tools.verify_macos_ffmpeg")
    @patch("scripts.setup_tools.mediamtx_download_spec", return_value=("darwin_arm64.tar.gz", "tar.gz", "a" * 64))
    @patch("scripts.setup_tools.get_platform_config")
    @patch("scripts.setup_tools.parse_args")
    def test_macos_verifies_ffmpeg_before_installing_mediamtx(
        self, parse_args, get_config, download_spec, verify_ffmpeg, install_archive
    ):
        parse_args.return_value = type("Args", (), {"force": False})()
        get_config.return_value = PlatformConfig(
            name="macos-arm64",
            capture_format="avfoundation",
            video_encoder="h264_videotoolbox",
            ffmpeg_path=Path("/opt/homebrew/bin/ffmpeg"),
            mediamtx_path=Path("tools/mediamtx/mediamtx"),
        )
        order = []
        verify_ffmpeg.side_effect = lambda _: order.append("ffmpeg")
        install_archive.side_effect = lambda *_: order.append("mediamtx")

        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)

        self.assertEqual(order, ["ffmpeg", "mediamtx"])
        install_archive.assert_called_once()

    @patch("scripts.setup_tools.install_archive")
    @patch("scripts.setup_tools.verify_linux_ffmpeg")
    @patch("scripts.setup_tools.mediamtx_download_spec", return_value=("linux_arm64.tar.gz", "tar.gz", "a" * 64))
    @patch("scripts.setup_tools.get_platform_config")
    @patch("scripts.setup_tools.parse_args")
    def test_linux_verifies_system_ffmpeg_before_installing_mediamtx(
        self, parse_args, get_config, download_spec, verify_ffmpeg, install_archive
    ):
        parse_args.return_value = type("Args", (), {"force": False})()
        get_config.return_value = PlatformConfig(
            name="linux-arm64",
            capture_format="v4l2",
            video_encoder="libx264",
            ffmpeg_path=Path("/usr/bin/ffmpeg"),
            mediamtx_path=Path("tools/mediamtx/mediamtx"),
        )
        order = []
        verify_ffmpeg.side_effect = lambda _: order.append("ffmpeg")
        install_archive.side_effect = lambda *_: order.append("mediamtx")

        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)

        self.assertEqual(order, ["ffmpeg", "mediamtx"])
        install_archive.assert_called_once()


class LinuxFfmpegVerificationTests(unittest.TestCase):
    @patch("scripts.setup_tools.subprocess.run")
    @patch.object(Path, "is_file", return_value=True)
    def test_linux_ffmpeg_requires_v4l2_and_libx264(self, _is_file, run):
        run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout=" D. v4l2 Video4Linux2 input"),
            subprocess.CompletedProcess(args=[], returncode=0, stdout=" V.... libx264 H.264"),
        ]

        verify_linux_ffmpeg(Path("/usr/bin/ffmpeg"))

        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
