import argparse
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from scripts.run_edge_agent import (
    STREAM_SERVER,
    EdgeAgent,
    InvalidCommand,
    parse_args,
)
from aiot.mqtt.client import MqttPublishError
from aiot.mqtt.topics import TOPIC_MOTION_DETECTED, control_ack_topic, control_stream_topic, stream_activity_topic


def make_args(**overrides):
    defaults = dict(
        profile="dshow",
        device="Camera A",
        motion_triggered=False,
        motion_device=None,
        framerate=30,
        video_size="1280x720",
        bitrate="2M",
        mqtt_host="127.0.0.1",
        mqtt_port=1883,
        mqtt_client_id="pi4-edge-01",
        mqtt_username="aiot-edge",
        mqtt_password_env="AIOT_EDGE_PASSWORD",
        mqtt_ca_cert=None,
        heartbeat_interval=5.0,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class PublisherCommandTests(unittest.TestCase):
    def setUp(self):
        self.agent = EdgeAgent(make_args())

    def test_continuous_command_uses_no_mqtt_and_device_flags(self):
        command = self.agent.publisher_command()
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1], str(STREAM_SERVER))
        self.assertIn("--no-mqtt", command)
        self.assertEqual(command[command.index("--mqtt-client-id") + 1], "pi4-edge-01")
        self.assertEqual(command[command.index("--profile") + 1], "dshow")
        self.assertEqual(command[command.index("--device") + 1], "Camera A")
        self.assertEqual(command[command.index("--framerate") + 1], "30")
        self.assertEqual(command[command.index("--video-size") + 1], "1280x720")
        self.assertEqual(command[command.index("--bitrate") + 1], "2M")

    def test_motion_command_includes_motion_flags(self):
        agent = EdgeAgent(make_args(motion_triggered=True, motion_device="1"))
        command = agent.publisher_command()
        self.assertIn("--motion-triggered", command)
        self.assertEqual(command[command.index("--motion-device") + 1], "1")
        self.assertEqual(command[command.index("--face-keepalive-timeout") + 1], "120.0")


class MotionRelayTests(unittest.TestCase):
    def setUp(self):
        self.agent = EdgeAgent(make_args(motion_triggered=True))
        self.agent.publish = Mock()
        self.agent.publish_status = Mock()

    def tearDown(self):
        self.agent.channel.close()

    def test_child_motion_event_is_published(self):
        self.agent.on_child_event({"type": "motion", "active": True})

        self.assertTrue(self.agent.motion_active)
        self.assertEqual(self.agent.publish.call_args.args[0], TOPIC_MOTION_DETECTED)
        self.assertTrue(self.agent.publish.call_args.args[1]["active"])

    def test_session_event_updates_status_with_session_id(self):
        self.agent.on_child_event({"type": "session", "state": "streaming", "stream_session_id": "session-1"})

        self.assertEqual(self.agent.session_id, "session-1")
        self.agent.publish_status.assert_called_once()

    def test_face_presence_is_forwarded_to_child(self):
        self.agent.channel.send = Mock(return_value=True)
        self.agent.on_message(
            stream_activity_topic("pi4-edge-01"),
            {"schema_version": 1, "device_id": "pi4-edge-01", "action": "face_presence", "stream_session_id": "session-1", "face_count": 1},
        )

        self.assertEqual(self.agent.channel.send.call_args.args[0]["type"], "face_presence")

    def test_rpi_csi_command_forwards_profile_and_omits_device(self):
        agent = EdgeAgent(make_args(profile="rpi-csi", device=None))
        command = agent.publisher_command()
        self.assertEqual(command[command.index("--profile") + 1], "rpi-csi")
        self.assertNotIn("--device", command)


class ParseArgsTests(unittest.TestCase):
    BASE = ["run_edge_agent.py", "--mqtt-host", "127.0.0.1", "--mqtt-client-id", "pi4-edge-01"]

    @patch("scripts.run_edge_agent.platform.machine", return_value="aarch64")
    @patch("scripts.run_edge_agent.platform.system", return_value="Linux")
    @patch("sys.argv", BASE + ["--profile", "rpi-csi"])
    def test_rpi_csi_requires_no_device(self, _system, _machine):
        args = parse_args()

        self.assertEqual(args.profile, "rpi-csi")
        self.assertIsNone(args.device)

    @patch("scripts.run_edge_agent.platform.machine", return_value="AMD64")
    @patch("scripts.run_edge_agent.platform.system", return_value="Windows")
    @patch("sys.argv", BASE)
    def test_ffmpeg_profile_requires_device(self, _system, _machine):
        with self.assertRaises(SystemExit):
            parse_args()

    @patch("scripts.run_edge_agent.platform.machine", return_value="aarch64")
    @patch("scripts.run_edge_agent.platform.system", return_value="Linux")
    @patch("sys.argv", BASE + ["--profile", "rpi-csi", "--motion-triggered"])
    def test_rpi_csi_rejects_motion_triggered(self, _system, _machine):
        with self.assertRaises(SystemExit):
            parse_args()

    @patch("scripts.run_edge_agent.platform.machine", return_value="AMD64")
    @patch("scripts.run_edge_agent.platform.system", return_value="Windows")
    @patch("sys.argv", BASE + ["--device", "Camera A", "--profile", "bogus"])
    def test_unknown_profile_is_rejected(self, _system, _machine):
        with self.assertRaises(SystemExit):
            parse_args()


class StartRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.agent = EdgeAgent(make_args())
        self.process = Mock(pid=1234)
        self.process.poll.return_value = None
        self.process.returncode = None

    @patch("scripts.run_edge_agent.subprocess.Popen")
    def test_skips_when_runtime_already_alive(self, popen):
        self.agent.process = self.process
        self.agent.start_runtime()
        popen.assert_not_called()

    @patch("scripts.run_edge_agent.subprocess.Popen", return_value=None)
    def test_raises_when_child_exits_during_startup(self, popen):
        popen.return_value = self.process
        self.process.poll.return_value = 3
        self.process.returncode = 3
        with self.assertRaisesRegex(RuntimeError, "exited during startup"):
            self.agent.start_runtime()

    @patch("scripts.run_edge_agent.time.sleep")
    @patch("scripts.run_edge_agent.subprocess.Popen", return_value=None)
    def test_waits_for_stream_health_in_continuous_mode(self, popen, sleep):
        popen.return_value = self.process
        with patch.object(
            self.agent, "rtsp_stream_active", side_effect=[False, True]
        ) as stream_active:
            self.agent.start_runtime()
        self.assertEqual(stream_active.call_count, 2)
        self.assertIs(self.agent.process, self.process)

    @patch("scripts.run_edge_agent.time.sleep")
    @patch("scripts.run_edge_agent.subprocess.Popen", return_value=None)
    def test_uses_port_check_in_motion_mode(self, popen, sleep):
        agent = EdgeAgent(make_args(motion_triggered=True))
        popen.return_value = self.process
        with patch.object(agent, "rtsp_port_open", side_effect=[False, True]) as port_open:
            agent.start_runtime()
        port_open.assert_called()

    @patch("scripts.run_edge_agent.time.sleep")
    @patch("scripts.run_edge_agent.subprocess.Popen", return_value=None)
    def test_times_out_when_stream_never_becomes_healthy(self, popen, sleep):
        popen.return_value = self.process
        monotonic = iter([0.0, 0.1, 10.5])
        with patch("scripts.run_edge_agent.time.monotonic", side_effect=monotonic):
            with patch.object(self.agent, "rtsp_stream_active", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "did not become reachable"):
                    self.agent.start_runtime()
        sleep.assert_called()


class StopRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.agent = EdgeAgent(make_args())
        self.process = Mock(pid=1234)
        self.process.poll.return_value = None

    def test_noop_when_process_already_exited(self):
        self.agent.process = self.process
        self.process.poll.return_value = 0
        with patch("scripts.run_edge_agent.subprocess.run") as run:
            self.agent.stop_runtime()
        run.assert_not_called()

    @patch.object(sys, "platform", "linux")
    def test_posix_uses_terminate_then_kill_on_timeout(self):
        self.agent.process = self.process
        self.process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]
        self.agent.stop_runtime()
        self.process.terminate.assert_called_once()
        self.process.kill.assert_called_once()

    @patch.object(sys, "platform", "win32")
    @patch("scripts.run_edge_agent.subprocess.run")
    def test_windows_terminates_process_tree(self, run):
        self.agent.process = self.process
        run.return_value = Mock(returncode=0)
        self.agent.stop_runtime()
        run.assert_called_once_with(
            ["taskkill", "/PID", "1234", "/T", "/F"],
            capture_output=True,
            timeout=10,
        )
        self.process.terminate.assert_not_called()
        self.process.wait.assert_called_once()

    @patch.object(sys, "platform", "win32")
    @patch("scripts.run_edge_agent.subprocess.run")
    def test_windows_falls_back_to_terminate_when_taskkill_fails(self, run):
        self.agent.process = self.process
        run.return_value = Mock(returncode=1)
        self.agent.stop_runtime()
        self.process.terminate.assert_called_once()


class HealthProbeTests(unittest.TestCase):
    def setUp(self):
        self.agent = EdgeAgent(make_args())
        self.process = Mock(pid=1234)
        self.process.poll.return_value = None
        self.agent.process = self.process

    def test_port_open_false_when_runtime_dead(self):
        self.process.poll.return_value = 0
        with patch("scripts.run_edge_agent.socket.create_connection") as connect:
            self.assertFalse(self.agent.rtsp_port_open())
        connect.assert_not_called()

    @patch("scripts.run_edge_agent.socket.create_connection")
    def test_port_open_uses_tcp_connection(self, connect):
        connect.return_value.__enter__.return_value = Mock()
        self.assertTrue(self.agent.rtsp_port_open())

    @patch("scripts.run_edge_agent.socket.create_connection", side_effect=OSError("refused"))
    def test_port_open_false_on_connection_error(self, connect):
        self.assertFalse(self.agent.rtsp_port_open())

    @patch("scripts.run_edge_agent.probe_rtsp_stream", return_value=True)
    def test_stream_active_true_when_publisher_serves_path(self, probe):
        self.assertTrue(self.agent.rtsp_stream_active())

    def test_stream_active_false_when_runtime_dead(self):
        self.process.poll.return_value = 0
        with patch("scripts.run_edge_agent.probe_rtsp_stream") as probe:
            self.assertFalse(self.agent.rtsp_stream_active())
        probe.assert_not_called()


class MessageHandlingTests(unittest.TestCase):
    def setUp(self):
        self.agent = EdgeAgent(make_args())
        self.agent.client = Mock()

    def test_ignores_other_topics(self):
        self.agent.on_message("system/status/pi4-edge-01", {})
        self.assertTrue(self.agent.commands.empty())

    def test_invalid_payload_is_enqueued_not_published(self):
        self.agent.on_message(
            control_stream_topic("pi4-edge-01"),
            {"schema_version": 1, "target_device_id": "pi4-edge-01", "action": "exec"},
        )
        item = self.agent.commands.get_nowait()
        self.assertIsInstance(item, InvalidCommand)
        self.assertEqual(item.action, "exec")
        self.agent.client.publish.assert_not_called()

    def test_valid_command_is_enqueued(self):
        self.agent.on_message(
            control_stream_topic("pi4-edge-01"),
            {
                "schema_version": 1,
                "target_device_id": "pi4-edge-01",
                "command_id": "cmd-1",
                "action": "start",
            },
        )
        item = self.agent.commands.get_nowait()
        self.assertEqual(item.command_id, "cmd-1")
        self.assertEqual(item.action, "start")


class StartPublisherTests(unittest.TestCase):
    def setUp(self):
        self.agent = EdgeAgent(make_args())
        self.agent.client = Mock()

    @patch.object(EdgeAgent, "start_runtime")
    def test_startup_moves_to_streaming_without_error_publish(self, start_runtime):
        self.agent.start_publisher()
        self.assertEqual(self.agent.supervisor.state.value, "streaming")
        self.agent.client.publish.assert_not_called()

    @patch.object(EdgeAgent, "start_runtime", side_effect=RuntimeError("camera busy"))
    def test_startup_failure_moves_to_error_and_publishes_event(self, start_runtime):
        self.agent.start_publisher()
        self.assertEqual(self.agent.supervisor.state.value, "error")
        topic = self.agent.client.publish.call_args.args[0]
        self.assertEqual(topic, "error/rtsp/pi4-edge-01")
        self.assertIn("camera busy", self.agent.client.publish.call_args.args[1]["message"])


class CommandProcessingTests(unittest.TestCase):
    def setUp(self):
        self.agent = EdgeAgent(make_args())
        self.agent.client = Mock()

    def test_invalid_command_publishes_failed_ack(self):
        self.agent.process_command(InvalidCommand("bad-1", "stop", "action is not supported"))
        self.agent.client.publish.assert_called_once()
        topic, payload = self.agent.client.publish.call_args.args[:2]
        self.assertEqual(topic, control_ack_topic("pi4-edge-01"))
        self.assertEqual(payload["result"], "failed")
        self.assertEqual(payload["command_id"], "bad-1")

    def test_publish_swallows_mqtt_publish_errors(self):
        self.agent.client.publish.side_effect = MqttPublishError("denied")
        self.agent.publish(control_ack_topic("pi4-edge-01"), {})  # must not raise

    def test_reconnect_republishes_status_after_first_connect(self):
        with patch.object(self.agent, "publish_status") as publish_status:
            self.agent.on_connection_state("connected")
            self.agent.on_connection_state("disconnected")
            self.agent.on_connection_state("connected")
        publish_status.assert_called_once()


if __name__ == "__main__":
    unittest.main()
