import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from aiot.streaming.profiles import (
    AVFOUNDATION,
    DSHOW,
    RPI_CSI,
    V4L2,
    ProfileValidationError,
    auto_detect_profile,
    list_csi_cameras,
    port_in_use,
    preflight,
    profile_uses_ffmpeg,
    resolve_profile,
)
from aiot.streaming.stream_platform import PlatformConfig


class AutoDetectTests(unittest.TestCase):
    def test_auto_detect_maps_each_supported_platform(self):
        self.assertEqual(auto_detect_profile("Windows"), DSHOW)
        self.assertEqual(auto_detect_profile("Darwin"), AVFOUNDATION)
        self.assertEqual(auto_detect_profile("Linux"), V4L2)

    def test_auto_detect_never_returns_rpi_csi(self):
        self.assertNotIn(auto_detect_profile("Linux"), (RPI_CSI,))

    def test_auto_detect_raises_for_unsupported_system(self):
        with self.assertRaises(ProfileValidationError):
            auto_detect_profile("FreeBSD")


class ResolveProfileTests(unittest.TestCase):
    def test_none_profile_uses_auto_detect(self):
        self.assertEqual(resolve_profile(None, "Windows", "AMD64"), DSHOW)

    def test_explicit_profile_matches_platform(self):
        self.assertEqual(resolve_profile(V4L2, "Linux", "x86_64"), V4L2)
        self.assertEqual(resolve_profile(RPI_CSI, "Linux", "aarch64"), RPI_CSI)

    def test_machine_check_is_case_insensitive(self):
        self.assertEqual(resolve_profile(RPI_CSI, "Linux", "ARM64"), RPI_CSI)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ProfileValidationError):
            resolve_profile("bogus", "Linux", "aarch64")

    def test_profile_for_another_system_is_rejected(self):
        with self.assertRaisesRegex(ProfileValidationError, "requires Windows"):
            resolve_profile(DSHOW, "Linux", "aarch64")

    def test_rpi_csi_rejects_unsupported_architecture(self):
        with self.assertRaisesRegex(ProfileValidationError, "aarch64"):
            resolve_profile(RPI_CSI, "Linux", "armv7l")


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mediamtx = self.root / "mediamtx"
        self.ffmpeg = self.root / "ffmpeg"
        self.mediamtx.touch()
        self.ffmpeg.touch()

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, name="linux-arm64", mediamtx=True, ffmpeg=True) -> PlatformConfig:
        return PlatformConfig(
            name=name,
            capture_format="v4l2",
            video_encoder="libx264",
            ffmpeg_path=self.ffmpeg if ffmpeg else self.root / "missing-ffmpeg",
            mediamtx_path=self.mediamtx if mediamtx else self.root / "missing-mediamtx",
        )

    def test_every_profile_requires_mediamtx(self):
        problems = preflight(V4L2, self.config(mediamtx=False))

        self.assertTrue(any("MediaMTX was not found" in p for p in problems))

    def test_ffmpeg_profiles_require_ffmpeg(self):
        for profile, name in ((V4L2, "linux-arm64"), (AVFOUNDATION, "macos-arm64"), (DSHOW, "windows")):
            problems = preflight(profile, self.config(name=name, ffmpeg=False))
            self.assertTrue(
                any("FFmpeg was not found" in p for p in problems),
                f"{profile} must require FFmpeg",
            )

    def test_missing_ffmpeg_hint_is_platform_specific(self):
        linux = preflight(V4L2, self.config(name="linux-arm64", ffmpeg=False))
        macos = preflight(AVFOUNDATION, self.config(name="macos-arm64", ffmpeg=False))
        windows = preflight(DSHOW, self.config(name="windows", ffmpeg=False))

        self.assertTrue(any("apt install" in p for p in linux))
        self.assertTrue(any("brew install" in p for p in macos))
        self.assertTrue(any("setup_tools" in p for p in windows))

    def test_rpi_csi_does_not_require_ffmpeg(self):
        problems = preflight(RPI_CSI, self.config(ffmpeg=False))

        self.assertFalse(any("FFmpeg" in p for p in problems))
        self.assertFalse(any("libx264" in p for p in problems))

    def test_rpi_csi_requires_camera_tool(self):
        with patch("aiot.streaming.profiles.shutil.which", return_value=None):
            problems = preflight(RPI_CSI, self.config())

        self.assertTrue(any("rpicam-apps" in p for p in problems))

    def test_rpi_csi_reports_enumeration_failure(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="libcamera error: no device\n"
        )
        with patch("aiot.streaming.profiles.shutil.which", return_value="/usr/bin/rpicam-hello"):
            with patch("aiot.streaming.profiles.subprocess.run", return_value=result) as run:
                problems = preflight(RPI_CSI, self.config())

        self.assertTrue(any("enumeration failed" in p for p in problems))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/usr/bin/rpicam-hello", "--list-cameras"])

    def test_rpi_csi_reports_no_cameras_available(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="No cameras available!\n"
        )
        with patch("aiot.streaming.profiles.shutil.which", return_value="/usr/bin/rpicam-hello"):
            with patch("aiot.streaming.profiles.subprocess.run", return_value=result):
                problems = preflight(RPI_CSI, self.config())

        self.assertTrue(any("no cameras" in p.lower() for p in problems))

    def test_rpi_csi_reports_rtsp_port_in_use(self):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="Available cameras:\n")
        with patch("aiot.streaming.profiles.shutil.which", return_value="/usr/bin/rpicam-hello"):
            with patch("aiot.streaming.profiles.subprocess.run", return_value=result):
                with patch("aiot.streaming.profiles.port_in_use", return_value=True):
                    problems = preflight(RPI_CSI, self.config())

        self.assertTrue(any("already in use" in p for p in problems))

    @patch("aiot.streaming.profiles.port_in_use", return_value=False)
    @patch("aiot.streaming.profiles.subprocess.run")
    @patch("aiot.streaming.profiles.shutil.which", return_value="/usr/bin/rpicam-hello")
    def test_rpi_csi_preflight_passes_when_ready(self, which, run, port):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Available cameras:\n0 : imx219 [3280x2464]\n"
        )

        self.assertEqual(preflight(RPI_CSI, self.config()), [])

    def test_mediamtx_config_file_is_validated(self):
        with patch("aiot.streaming.profiles.shutil.which", return_value="/usr/bin/rpicam-hello"):
            with patch("aiot.streaming.profiles.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="")):
                with patch("aiot.streaming.profiles.port_in_use", return_value=False):
                    problems = preflight(
                        RPI_CSI, self.config(), mediamtx_config=self.root / "missing.yml"
                    )

        self.assertTrue(any("configuration was not found" in p for p in problems))

    def test_v4l2_device_path_must_exist(self):
        problems = preflight(V4L2, self.config(), device="/dev/video0")

        self.assertTrue(any("does not exist" in p for p in problems))

    def test_v4l2_device_name_is_not_path_checked(self):
        problems = preflight(V4L2, self.config(), device="Rapoo camera")

        self.assertFalse(any("does not exist" in p for p in problems))

    def test_v4l2_existing_device_path_passes(self):
        device = self.root / "video0"
        device.touch()

        problems = preflight(V4L2, self.config(), device=str(device))

        self.assertFalse(any("does not exist" in p for p in problems))


class PortInUseTests(unittest.TestCase):
    @patch("aiot.streaming.profiles.socket.create_connection", return_value=MagicMock())
    def test_true_when_connection_succeeds(self, connect):
        self.assertTrue(port_in_use())

    @patch(
        "aiot.streaming.profiles.socket.create_connection",
        side_effect=OSError("refused"),
    )
    def test_false_when_connection_refused(self, connect):
        self.assertFalse(port_in_use())


class ListCsiCamerasTests(unittest.TestCase):
    @patch("aiot.streaming.profiles.shutil.which", return_value=None)
    def test_returns_error_without_tool(self, which):
        stderr = StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(list_csi_cameras(), 1)
        self.assertIn("rpicam-apps", stderr.getvalue())

    @patch("aiot.streaming.profiles.subprocess.run")
    @patch("aiot.streaming.profiles.shutil.which", return_value="/usr/bin/rpicam-hello")
    def test_prints_camera_list_on_success(self, which, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Available cameras:\n0 : imx219 [3280x2464 10-bit RGGB]\n",
        )
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(list_csi_cameras(), 0)
        self.assertIn("imx219", stdout.getvalue())

    @patch("aiot.streaming.profiles.subprocess.run")
    @patch("aiot.streaming.profiles.shutil.which", return_value="/usr/bin/rpicam-vid")
    def test_returns_error_when_enumeration_fails(self, which, run):
        run.return_value = subprocess.CompletedProcess(args=[], returncode=2, stdout="")
        self.assertEqual(list_csi_cameras(), 1)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/rpicam-vid", "--list-cameras"])


if __name__ == "__main__":
    unittest.main()
