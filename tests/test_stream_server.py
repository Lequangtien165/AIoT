import argparse
import subprocess
from unittest.mock import Mock, patch
import unittest

from aiot.streaming.stream_platform import get_platform_config
from aiot.mqtt import payloads
from aiot.mqtt.topics import control_stream_topic, system_status_topic, error_rtsp_topic
from stream_server import (
    CameraDevice,
    RTSP_URL,
    build_ffmpeg_command,
    choose_device,
    get_video_devices,
    monitor_publisher,
    parse_args,
    parse_linux_devices,
    parse_macos_devices,
    publish_mqtt,
    validate_control_stream_action,
)


class FfmpegCommandTests(unittest.TestCase):
    @patch("sys.argv", ["stream_server.py", "--device", "Camera A"])
    def test_default_capture_mode_is_720p_at_30_fps(self):
        args = parse_args()

        self.assertEqual(args.video_size, "1280x720")
        self.assertEqual(args.framerate, 30)

    @patch(
        "sys.argv",
        [
            "stream_server.py",
            "--device",
            "Camera A",
            "--mqtt-host",
            "127.0.0.1",
            "--mqtt-port",
            "1884",
            "--mqtt-username",
            "edge",
            "--mqtt-password-env",
            "AIOT_MQTT_PASSWORD",
            "--heartbeat-interval",
            "2",
        ],
    )
    @patch.dict("os.environ", {"AIOT_MQTT_PASSWORD": "secret"})
    def test_parse_args_supports_mqtt_flags(self):
        args = parse_args()

        self.assertEqual(args.mqtt_host, "127.0.0.1")
        self.assertEqual(args.mqtt_port, 1884)
        self.assertEqual(args.mqtt_username, "edge")
        self.assertEqual(args.mqtt_password_env, "AIOT_MQTT_PASSWORD")
        self.assertEqual(args.heartbeat_interval, 2.0)

    @patch("sys.argv", ["stream_server.py", "--mqtt-username", "edge"])
    @patch.dict("os.environ", {}, clear=True)
    def test_mqtt_username_requires_password_env(self):
        with self.assertRaises(SystemExit):
            parse_args()

    def test_control_stream_accepts_supported_schema_v1_actions(self):
        self.assertEqual(
            validate_control_stream_action(
                {"schema_version": 1, "target_device_id": "edge-1", "action": "stop"},
                "edge-1",
            ),
            "stop",
        )

    def test_control_stream_rejects_malformed_or_unsupported_payloads(self):
        self.assertIsNone(validate_control_stream_action({"schema_version": 2, "action": "stop"}, "edge-1"))
        self.assertIsNone(
            validate_control_stream_action(
                {"schema_version": 1, "target_device_id": "edge-1", "action": "delete"},
                "edge-1",
            )
        )
        self.assertIsNone(validate_control_stream_action({"action": "stop"}, "edge-1"))

    def test_control_stream_rejects_command_for_another_device(self):
        message = payloads.stream_control(action="stop", target_device_id="edge-2")

        self.assertIsNone(validate_control_stream_action(message, "edge-1"))

    def test_per_device_topic_helpers_are_stable(self):
        self.assertEqual(control_stream_topic("edge-1"), "control/stream/edge-1")
        self.assertEqual(system_status_topic("edge-1"), "system/status/edge-1")
        self.assertEqual(error_rtsp_topic("edge-1"), "error/rtsp/edge-1")

    def test_publish_uses_per_device_status_retained_policy(self):
        client = Mock()

        publish_mqtt(client, system_status_topic("edge-1"), {"schema_version": 1})

        client.publish.assert_called_once_with(
            "system/status/edge-1", {"schema_version": 1}, qos=0, retain=True
        )

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

    def test_linux_uses_v4l2_and_cpu_h264_encoder(self):
        args = argparse.Namespace(device="/dev/video0", framerate=30, video_size="1280x720", bitrate="2M")

        command = build_ffmpeg_command(args, get_platform_config("Linux", "aarch64"))

        self.assertIn("v4l2", command)
        self.assertIn("/dev/video0", command)
        self.assertIn("libx264", command)
        self.assertIn("ultrafast", command)
        self.assertIn("zerolatency", command)
        self.assertNotIn("dshow", command)
        self.assertNotIn("h264_videotoolbox", command)
        self.assertNotIn("-realtime", command)
        self.assertNotIn("-prio_speed", command)


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

    def test_avfoundation_parser_accepts_log_prefix_and_tab_separator(self):
        output = "AVFoundation video devices:\n[AVFoundation indev @ 0x1] [2]\tExternal Camera  \n"

        devices = parse_macos_devices(output)

        self.assertEqual(devices, [CameraDevice("External Camera", "2")])

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


class LinuxDeviceTests(unittest.TestCase):
    def test_v4l2_parser_returns_video_nodes(self):
        output = """Parallels Virtual Camera (usb-0000:00:04.0-1):
	/dev/video0
	/dev/video1
	/dev/media0
"""

        devices = parse_linux_devices(output)

        self.assertEqual(
            devices,
            [
                CameraDevice("Parallels Virtual Camera (usb-0000:00:04.0-1) (/dev/video0)", "/dev/video0"),
                CameraDevice("Parallels Virtual Camera (usb-0000:00:04.0-1) (/dev/video1)", "/dev/video1"),
            ],
        )

    @patch("stream_server.subprocess.run")
    def test_v4l2_listing_succeeds_when_devices_are_parsed(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="Camera:\n\t/dev/video0\n",
        )

        devices, status, _ = get_video_devices(get_platform_config("Linux", "arm64"))

        self.assertEqual(status, 0)
        self.assertEqual(devices, [CameraDevice("Camera (/dev/video0)", "/dev/video0")])
        self.assertEqual(run.call_args.args[0], ["v4l2-ctl", "--list-devices"])


class PublisherMonitorTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(heartbeat_interval=5.0, mqtt_client_id="edge-test")
        self.mediamtx = Mock(pid=101)
        self.ffmpeg = Mock(pid=202)
        self.stop_requested = Mock()
        self.client = Mock()

    @patch("stream_server.publish_mqtt")
    def test_mediamtx_exit_publishes_rtsp_error(self, publish_mqtt):
        self.mediamtx.poll.return_value = 1

        result = monitor_publisher(
            self.args, self.mediamtx, self.ffmpeg, self.stop_requested, self.client
        )

        self.assertEqual(result, 1)
        self.ffmpeg.poll.assert_not_called()
        self.assertEqual(publish_mqtt.call_args.args[1], "error/rtsp/edge-test")

    @patch("stream_server.publish_mqtt")
    def test_ffmpeg_exit_returns_process_code_and_publishes_details(self, publish_mqtt):
        self.mediamtx.poll.return_value = None
        self.ffmpeg.poll.return_value = 7
        self.ffmpeg.returncode = 7

        result = monitor_publisher(
            self.args, self.mediamtx, self.ffmpeg, self.stop_requested, self.client
        )

        self.assertEqual(result, 7)
        self.assertEqual(publish_mqtt.call_args.args[1], "error/rtsp/edge-test")
        self.assertEqual(publish_mqtt.call_args.args[2]["details"], {"returncode": 7})

    @patch("stream_server.publish_mqtt")
    def test_stop_request_exits_without_error(self, publish_mqtt):
        self.mediamtx.poll.return_value = None
        self.ffmpeg.poll.return_value = None
        self.stop_requested.is_set.return_value = True

        result = monitor_publisher(
            self.args, self.mediamtx, self.ffmpeg, self.stop_requested, self.client
        )

        self.assertEqual(result, 0)
        publish_mqtt.assert_not_called()

    @patch("stream_server.time.sleep")
    @patch("stream_server.time.monotonic", side_effect=[5.0])
    @patch("stream_server.publish_mqtt")
    def test_heartbeat_includes_process_ids(self, publish_mqtt, _monotonic, sleep):
        self.mediamtx.poll.return_value = None
        self.ffmpeg.poll.return_value = None
        self.stop_requested.is_set.side_effect = [False, True]

        result = monitor_publisher(
            self.args, self.mediamtx, self.ffmpeg, self.stop_requested, self.client
        )

        self.assertEqual(result, 0)
        self.assertEqual(publish_mqtt.call_args.args[1], "system/status/edge-test")
        self.assertEqual(
            publish_mqtt.call_args.args[2]["metrics"],
            {"rtsp_url": RTSP_URL, "mediamtx_pid": 101, "ffmpeg_pid": 202},
        )
        sleep.assert_called_once_with(0.25)


if __name__ == "__main__":
    unittest.main()
