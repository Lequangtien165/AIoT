import argparse
import signal
import subprocess
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import Mock, patch

import stream_server
from aiot.streaming.stream_platform import get_platform_config
from aiot.mqtt import payloads
from aiot.mqtt.topics import control_stream_topic, system_status_topic, error_rtsp_topic
from stream_server import (
    MEDIA_MTX_CONFIG,
    MEDIA_MTX_RPI_CONFIG,
    CameraDevice,
    RTSP_URL,
    build_ffmpeg_command,
    choose_device,
    get_video_devices,
    install_signal_handlers,
    main,
    monitor_publisher,
    parse_args,
    parse_linux_devices,
    parse_macos_devices,
    parse_windows_devices,
    publish_mqtt,
    request_stop,
    resolve_device,
    run_preflight,
    select_mediamtx_config,
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


class WindowsParserTests(unittest.TestCase):
    def test_new_format_accepts_video_and_none_tags(self):
        output = (
            '[in#0 @ 0x1] "OBS Virtual Camera" (none)\n'
            '[in#0 @ 0x2] "Integrated Camera" (video)\n'
        )

        devices = parse_windows_devices(output)

        self.assertEqual(
            devices,
            [
                CameraDevice("OBS Virtual Camera", "OBS Virtual Camera"),
                CameraDevice("Integrated Camera", "Integrated Camera"),
            ],
        )

    def test_new_format_excludes_audio_devices(self):
        output = (
            '[in#0 @ 0x1] "Integrated Camera" (video)\n'
            '[in#0 @ 0x2] "Microphone" (audio)\n'
        )

        devices = parse_windows_devices(output)

        self.assertEqual(devices, [CameraDevice("Integrated Camera", "Integrated Camera")])

    def test_new_format_ignores_alternative_names(self):
        output = (
            '[in#0 @ 0x1] "Integrated Camera" (video)\n'
            '[in#0 @ 0x1]   Alternative name "@device_sw_{860BB310}"\n'
        )

        devices = parse_windows_devices(output)

        self.assertEqual(devices, [CameraDevice("Integrated Camera", "Integrated Camera")])

    def test_legacy_format_uses_video_section_headers(self):
        output = """DirectShow video devices (some may be both video and audio devices)
 "Integrated Camera"
    Alternative name "@device_pnp_\\\\?\\usb#vid_0bda"
DirectShow audio devices
 "Microphone"
"""

        devices = parse_windows_devices(output)

        self.assertEqual(devices, [CameraDevice("Integrated Camera", "Integrated Camera")])

    @patch("stream_server.subprocess.run")
    def test_windows_listing_succeeds_when_devices_are_parsed(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout='[in#0 @ 0x1] "Integrated Camera" (video)\n',
        )

        devices, status, _ = get_video_devices(get_platform_config("Windows", "AMD64"))

        self.assertEqual(status, 0)
        self.assertEqual(devices, [CameraDevice("Integrated Camera", "Integrated Camera")])
        self.assertIn("-list_devices", run.call_args.args[0])


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


class MosquittoConfigTests(unittest.TestCase):
    def test_mosquitto_config_files_use_lf_line_endings(self):
        config_dir = stream_server.PROJECT_ROOT / "config" / "mosquitto"
        for name in ("mosquitto.conf", "mosquitto-tls.conf", "aclfile", "passwords.example"):
            path = config_dir / name
            self.assertTrue(path.is_file(), f"missing {name}")
            data = path.read_bytes()
            self.assertNotIn(
                b"\r\n",
                data,
                f"{name} must use LF line endings; CRLF breaks Mosquitto ACL pattern matching",
            )


class SignalHandlerTests(unittest.TestCase):
    def test_request_stop_raises_keyboard_interrupt_for_cleanup(self):
        with self.assertRaises(KeyboardInterrupt):
            request_stop(signal.SIGTERM, None)

    @patch("stream_server.signal.signal")
    def test_install_signal_handlers_registers_sigterm(self, signal_signal):
        install_signal_handlers()
        signal_signal.assert_called_once_with(signal.SIGTERM, request_stop)

    @patch("stream_server.signal.signal")
    def test_install_signal_handlers_is_safe_without_sigterm(self, signal_signal):
        with patch.object(stream_server.signal, "SIGTERM", None, create=True):
            install_signal_handlers()
        signal_signal.assert_not_called()


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


class ProfileWiringTests(unittest.TestCase):
    def test_select_mediamtx_config_uses_rpi_config_for_csi(self):
        self.assertEqual(select_mediamtx_config("rpi-csi"), MEDIA_MTX_RPI_CONFIG)
        self.assertEqual(select_mediamtx_config("v4l2"), MEDIA_MTX_CONFIG)
        self.assertEqual(select_mediamtx_config("dshow"), MEDIA_MTX_CONFIG)
        self.assertEqual(select_mediamtx_config("avfoundation"), MEDIA_MTX_CONFIG)

    @patch("sys.argv", ["stream_server.py", "--device", "Camera A", "--profile", "rpi-csi"])
    def test_parse_args_accepts_explicit_profile(self):
        args = parse_args()
        self.assertEqual(args.profile, "rpi-csi")

    @patch("sys.argv", ["stream_server.py", "--device", "Camera A", "--profile", "bogus"])
    def test_parse_args_rejects_unknown_profile(self):
        with self.assertRaises(SystemExit):
            parse_args()

    @patch("stream_server.preflight", return_value=[])
    def test_run_preflight_returns_zero_when_ready(self, preflight):
        config = get_platform_config("Windows", "AMD64")

        self.assertEqual(run_preflight("dshow", config, "Camera A"), 0)
        preflight.assert_called_once()
        self.assertEqual(preflight.call_args.kwargs["device"], "Camera A")

    @patch("stream_server.preflight", return_value=["FFmpeg was not found."])
    def test_run_preflight_prints_problems_and_fails(self, preflight):
        config = get_platform_config("Windows", "AMD64")
        stderr = StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(run_preflight("dshow", config, None), 1)
        self.assertIn("FFmpeg was not found", stderr.getvalue())


class PublisherMonitorNoFfmpegTests(unittest.TestCase):
    """The rpi-csi profile publishes directly through MediaMTX with no FFmpeg child."""

    def setUp(self):
        self.args = argparse.Namespace(heartbeat_interval=5.0, mqtt_client_id="edge-test")
        self.mediamtx = Mock(pid=101)
        self.stop_requested = Mock()
        self.client = Mock()

    @patch("stream_server.publish_mqtt")
    def test_mediamtx_exit_is_detected_without_ffmpeg_child(self, publish_mqtt):
        self.mediamtx.poll.return_value = 3

        result = monitor_publisher(
            self.args, self.mediamtx, None, self.stop_requested, self.client
        )

        self.assertEqual(result, 1)
        self.assertEqual(publish_mqtt.call_args.args[1], "error/rtsp/edge-test")

    @patch("stream_server.time.sleep")
    @patch("stream_server.time.monotonic", side_effect=[5.0])
    @patch("stream_server.publish_mqtt")
    def test_heartbeat_omits_ffmpeg_pid_without_ffmpeg_child(self, publish_mqtt, _monotonic, sleep):
        self.mediamtx.poll.return_value = None
        self.stop_requested.is_set.side_effect = [False, True]

        result = monitor_publisher(
            self.args, self.mediamtx, None, self.stop_requested, self.client
        )

        self.assertEqual(result, 0)
        metrics = publish_mqtt.call_args.args[2]["metrics"]
        self.assertEqual(metrics["mediamtx_pid"], 101)
        self.assertNotIn("ffmpeg_pid", metrics)


class RpiCsiDeviceTests(unittest.TestCase):
    @patch("stream_server.list_csi_cameras", return_value=0)
    def test_list_devices_uses_camera_tool(self, list_csi):
        args = argparse.Namespace(list_devices=True)

        self.assertEqual(
            resolve_device(args, get_platform_config("Linux", "aarch64"), "rpi-csi"), 0
        )
        list_csi.assert_called_once()

    def test_regular_run_skips_device_resolution(self):
        args = argparse.Namespace(list_devices=False)

        self.assertIsNone(
            resolve_device(args, get_platform_config("Linux", "aarch64"), "rpi-csi")
        )


class MainProfileGateTests(unittest.TestCase):
    @patch("stream_server.platform.machine", return_value="AMD64")
    @patch("stream_server.platform.system", return_value="Linux")
    @patch("sys.argv", ["stream_server.py", "--profile", "rpi-csi"])
    def test_main_rejects_rpi_csi_on_wrong_architecture(self, _system, _machine):
        self.assertEqual(main(), 1)

    @patch("stream_server.platform.machine", return_value="aarch64")
    @patch("stream_server.platform.system", return_value="Linux")
    @patch("stream_server.run_preflight", return_value=0)
    @patch("sys.argv", ["stream_server.py", "--profile", "rpi-csi", "--motion-triggered"])
    def test_main_rejects_motion_triggered_with_rpi_csi(self, _preflight, _system, _machine):
        self.assertEqual(main(), 1)

    @patch("stream_server.platform.machine", return_value="AMD64")
    @patch("stream_server.platform.system", return_value="Windows")
    @patch("stream_server.run_preflight", return_value=1)
    @patch("sys.argv", ["stream_server.py", "--device", "Camera A"])
    def test_main_exits_when_preflight_fails(self, _preflight, _system, _machine):
        self.assertEqual(main(), 1)


if __name__ == "__main__":
    unittest.main()
