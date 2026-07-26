import argparse
import subprocess
from unittest.mock import patch
import unittest

from stream_platform import get_platform_config
from stream_server import (
    CameraDevice,
    RTSP_URL,
    build_ffmpeg_command,
    choose_device,
    get_video_devices,
    parse_macos_devices,
)


class FfmpegCommandTests(unittest.TestCase):
    def test_command_preserves_capture_rate_without_frame_duplication(self):
        args = argparse.Namespace(
            device="Rapoo camera", framerate=25, video_size="1280x720", bitrate="2M"
        )

        command = build_ffmpeg_command(args, get_platform_config("Windows", "AMD64"))

        self.assertIn("-use_video_device_timestamps", command)
        self.assertIn("-fps_mode", command)
        self.assertEqual(command[command.index("-fps_mode") + 1], "passthrough")
        self.assertEqual(command[command.index("-g") + 1], "25")
        self.assertEqual(command[command.index("-framerate") + 1], "25")
        self.assertEqual(command[command.index("-video_size") + 1], "1280x720")
        self.assertEqual(command[-1], RTSP_URL)

    def test_command_uses_default_gop_when_capture_rate_is_unspecified(self):
        args = argparse.Namespace(device="Rapoo camera", framerate=None, video_size=None, bitrate="2M")

        command = build_ffmpeg_command(args, get_platform_config("Windows", "AMD64"))

        self.assertEqual(command[command.index("-g") + 1], "30")
        self.assertNotIn("-framerate", command)


class DeviceSelectionTests(unittest.TestCase):
    @patch("stream_server.sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="2")
    def test_choose_device_returns_selected_camera(self, _input, _isatty):
        devices = [CameraDevice("Camera A", "a"), CameraDevice("Camera B", "b")]
        self.assertEqual(choose_device(devices), "b")

    @patch("stream_server.sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="q")
    def test_choose_device_can_cancel(self, _input, _isatty):
        self.assertIsNone(choose_device([CameraDevice("Camera A", "a")]))


class MacOSCommandTests(unittest.TestCase):
    def test_avfoundation_parser_excludes_audio_devices(self):
        output = """AVFoundation video devices:
[0] FaceTime HD Camera
[1] OBS Virtual Camera
AVFoundation audio devices:
[0] MacBook Air Microphone
"""

        devices = parse_macos_devices(output)

        self.assertEqual(
            devices,
            [CameraDevice("FaceTime HD Camera", "0"), CameraDevice("OBS Virtual Camera", "1")],
        )

    def test_macos_uses_avfoundation_and_hardware_encoder(self):
        args = argparse.Namespace(device="0", framerate=30, video_size="1280x720", bitrate="2M")

        command = build_ffmpeg_command(args, get_platform_config("Darwin", "arm64"))

        self.assertIn("avfoundation", command)
        self.assertIn("h264_videotoolbox", command)
        self.assertIn("0:none", command)
        self.assertIn("-realtime", command)
        self.assertIn("-prio_speed", command)
        self.assertIn("-bf", command)
        self.assertNotIn("dshow", command)
        self.assertNotIn("libx264", command)

    @patch("stream_server.subprocess.run")
    def test_macos_device_list_succeeds_when_ffmpeg_returns_nonzero_after_listing(
        self, run
    ):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=187,
            stdout="AVFoundation video devices:\n[0] FaceTime HD Camera\n",
        )

        devices, status, _ = get_video_devices(get_platform_config("Darwin", "arm64"))

        self.assertEqual(status, 0)
        self.assertEqual(devices, [CameraDevice("FaceTime HD Camera", "0")])


if __name__ == "__main__":
    unittest.main()
