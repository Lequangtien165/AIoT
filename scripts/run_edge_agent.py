"""Run the persistent MQTT edge agent for a fixed local publisher runtime."""

from __future__ import annotations

import argparse
import os
import platform
import queue
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aiot.mqtt import payloads
from aiot.mqtt.client import MqttClient, MqttPublishError, password_from_env
from aiot.mqtt.topics import (
    TOPIC_CONTROL_STREAM,
    TOPIC_MOTION_DETECTED,
    control_ack_topic,
    control_stream_topic,
    error_rtsp_topic,
    system_status_topic,
    stream_activity_topic,
    topic_policy,
)
from aiot.streaming.edge_supervisor import (
    EdgeCommand,
    EdgeState,
    EdgeSupervisor,
    CommandValidationError,
    validate_command,
)
from aiot.streaming.agent_channel import AgentChannelServer
from aiot.streaming.profiles import (
    PROFILE_CHOICES,
    RPI_CSI,
    ProfileValidationError,
    profile_uses_ffmpeg,
    resolve_profile,
)
from aiot.streaming.rtsp_probe import probe_rtsp_stream
from aiot.streaming.stream_settings import RTSP_HOST, RTSP_PORT


STREAM_SERVER = PROJECT_ROOT / "stream_server.py"


@dataclass(frozen=True)
class InvalidCommand:
    command_id: str
    action: str
    error: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistently supervise the edge RTSP publisher.")
    parser.add_argument("--device", help="Camera input; required for FFmpeg-based profiles, ignored by rpi-csi.")
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        help=(
            "Explicit capture/deployment profile; auto-detected by default "
            "(dshow on Windows, avfoundation on macOS, v4l2 on Linux). "
            "rpi-csi is never auto-detected and requires no --device."
        ),
    )
    parser.add_argument("--motion-triggered", action="store_true", help="Start RTSP sessions only after significant motion.")
    parser.add_argument("--motion-device", help="OpenCV camera index/path used while monitoring; defaults to --device.")
    parser.add_argument("--motion-width", type=int, default=320, help="Motion monitor width (default: 320).")
    parser.add_argument("--motion-height", type=int, default=240, help="Motion monitor height (default: 240).")
    parser.add_argument("--motion-fps", type=float, default=5.0, help="Motion monitor frame rate (default: 5.0).")
    parser.add_argument("--motion-area-threshold", type=float, default=0.02, help="Changed-pixel fraction that counts as motion (default: 0.02).")
    parser.add_argument("--motion-window-size", type=int, default=5, help="Motion decision window in frames (default: 5).")
    parser.add_argument("--motion-trigger-frames", type=int, default=3, help="Motion frames required within the window (default: 3).")
    parser.add_argument("--motion-warmup", type=float, default=2.0, help="Seconds of background calibration before monitoring (default: 2.0).")
    parser.add_argument("--face-discovery-timeout", type=float, default=30.0, help="Seconds to wait for the first face presence (default: 30.0).")
    parser.add_argument("--face-keepalive-timeout", type=float, default=120.0, help="Face-presence session lease in seconds (default: 120.0).")
    parser.add_argument("--framerate", type=int, default=30, help="Requested camera frame rate (default: 30).")
    parser.add_argument("--video-size", default="1280x720", help="Requested size (default: 1280x720).")
    parser.add_argument("--bitrate", default="2M", help="H.264 bitrate (default: 2M).")
    parser.add_argument("--mqtt-host", required=True, help="MQTT broker host (required).")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port (default: 1883).")
    parser.add_argument("--mqtt-client-id", required=True, help="MQTT client/edge device ID (required).")
    parser.add_argument("--mqtt-username", help="MQTT username. Password is read from --mqtt-password-env.")
    parser.add_argument("--mqtt-password-env", help="Environment variable containing the MQTT password.")
    parser.add_argument("--mqtt-ca-cert", help="CA certificate path for TLS MQTT connections.")
    parser.add_argument("--heartbeat-interval", type=float, default=5.0, help="Status heartbeat interval in seconds (default: 5.0).")
    return parser


def parse_args() -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args()
    if args.mqtt_username:
        try:
            password_from_env(args.mqtt_username, args.mqtt_password_env)
        except ValueError as error:
            parser.error(str(error))
    if args.mqtt_port <= 0 or args.heartbeat_interval <= 0:
        parser.error("--mqtt-port and --heartbeat-interval must be positive")
    if args.motion_width <= 0 or args.motion_height <= 0 or args.motion_fps <= 0:
        parser.error("motion width, height, and fps must be positive")
    if not 0 < args.motion_area_threshold <= 1 or args.motion_window_size <= 0:
        parser.error("motion area threshold must be in (0, 1] and window size must be positive")
    if not 0 < args.motion_trigger_frames <= args.motion_window_size:
        parser.error("motion trigger frames must be within the motion window")
    if args.motion_warmup < 0 or args.face_discovery_timeout <= 0 or args.face_keepalive_timeout <= 0:
        parser.error("motion warmup must be non-negative and session timeouts must be positive")
    try:
        profile = resolve_profile(args.profile, platform.system(), platform.machine())
    except ProfileValidationError as error:
        parser.error(str(error))
    if profile == RPI_CSI and args.motion_triggered:
        parser.error(
            "--motion-triggered is not supported with the rpi-csi profile; "
            "MediaMTX owns the camera through libcamera. Use the v4l2 profile "
            "with a USB camera."
        )
    if profile_uses_ffmpeg(profile) and not args.device:
        parser.error(f"--device is required for the {profile} profile")
    args.profile = profile
    return args


class EdgeAgent:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.commands: queue.Queue[EdgeCommand | InvalidCommand] = queue.Queue()
        self.process: subprocess.Popen[bytes] | None = None
        self.client: MqttClient | None = None
        self._first_connect = True
        self.channel = AgentChannelServer(self.on_child_event)
        self.session_id: str | None = None
        self.session_state = "monitoring"
        self.motion_active = False
        self.supervisor = EdgeSupervisor(
            device_id=args.mqtt_client_id,
            start_runtime=self.start_runtime,
            stop_runtime=self.stop_runtime,
            runtime_alive=self.runtime_alive,
            rtsp_healthy=self.rtsp_port_open,
            stream_active=self.rtsp_stream_active,
            mode="motion-triggered" if args.motion_triggered else "continuous",
        )

    def publisher_command(self) -> list[str]:
        command = [
            sys.executable,
            str(STREAM_SERVER),
            "--no-mqtt",
            "--profile",
            self.args.profile,
        ]
        if self.args.device:
            command.extend(["--device", self.args.device])
        command.extend(
            [
                "--framerate",
                str(self.args.framerate),
                "--video-size",
                self.args.video_size,
                "--bitrate",
                self.args.bitrate,
            ]
        )
        if self.args.motion_triggered:
            command.append("--motion-triggered")
        if self.args.motion_device:
            command.extend(["--motion-device", self.args.motion_device])
        command.extend([
            "--motion-width", str(getattr(self.args, "motion_width", 320)), "--motion-height", str(getattr(self.args, "motion_height", 240)),
            "--motion-fps", str(getattr(self.args, "motion_fps", 5.0)), "--motion-area-threshold", str(getattr(self.args, "motion_area_threshold", 0.02)),
            "--motion-window-size", str(getattr(self.args, "motion_window_size", 5)), "--motion-trigger-frames", str(getattr(self.args, "motion_trigger_frames", 3)),
            "--motion-warmup", str(getattr(self.args, "motion_warmup", 2.0)), "--face-discovery-timeout", str(getattr(self.args, "face_discovery_timeout", 30.0)),
            "--face-keepalive-timeout", str(getattr(self.args, "face_keepalive_timeout", 120.0)),
        ])
        return command

    def start_runtime(self) -> None:
        if self.runtime_alive():
            return
        environment = os.environ.copy()
        environment.update(self.channel.child_environment())
        self.process = subprocess.Popen(self.publisher_command(), cwd=PROJECT_ROOT, env=environment)
        require_stream = not self.args.motion_triggered
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"publisher exited during startup with code {self.process.returncode}")
            if require_stream:
                if self.rtsp_stream_active():
                    return
            elif self.rtsp_port_open():
                return
            time.sleep(0.1)
        raise RuntimeError("RTSP endpoint did not become reachable during startup")

    def stop_runtime(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        if sys.platform.startswith("win"):
            self._terminate_tree_windows()
        else:
            self._terminate_posix()

    def _terminate_posix(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def _terminate_tree_windows(self) -> None:
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            self._terminate_posix()
            return
        if result.returncode != 0:
            self._terminate_posix()
            return
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def runtime_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def rtsp_port_open(self) -> bool:
        if not self.runtime_alive():
            return False
        try:
            with socket.create_connection((RTSP_HOST, RTSP_PORT), timeout=0.2):
                return True
        except OSError:
            return False

    def rtsp_stream_active(self) -> bool:
        if not self.runtime_alive():
            return False
        return probe_rtsp_stream(RTSP_HOST, RTSP_PORT, timeout=0.5)

    def publish(self, topic: str, message: dict, *, retain: bool | None = None) -> None:
        if self.client is None:
            return
        policy = topic_policy(topic)
        try:
            self.client.publish(
                topic,
                message,
                qos=policy.qos,
                retain=policy.retain if retain is None else retain,
            )
        except MqttPublishError as error:
            print(f"[MQTT] {error}", file=sys.stderr)

    def publish_status(self, message: str | None = None) -> None:
        self.supervisor.observe_runtime()
        status = self.supervisor.status()
        published_state = status["state"]
        if self.args.motion_triggered and status["runtime_alive"]:
            published_state = self.session_state
        self.publish(
            system_status_topic(self.args.mqtt_client_id),
            payloads.system_status(
                device_id=self.args.mqtt_client_id,
                component="edge-agent",
                state=published_state,
                message=message,
                metrics={
                    "mode": status["mode"],
                    "runtime_alive": status["runtime_alive"],
                    "rtsp_healthy": status["rtsp_healthy"],
                    "rtsp_stream_active": status.get("rtsp_stream_active"),
                    "session_phase": self.session_state,
                    "motion_active": self.motion_active,
                    "publisher_pid": self.process.pid if self.process else None,
                    "rtsp_url": f"rtsp://{RTSP_HOST}:{RTSP_PORT}/camera",
                },
                stream_session_id=self.session_id,
            ),
        )

    def on_child_event(self, event: dict) -> None:
        """Relay trusted loopback child lifecycle events through MQTT."""
        event_type = event.get("type")
        if event_type == "motion" and isinstance(event.get("active"), bool):
            self.motion_active = event["active"]
            self.publish(
                TOPIC_MOTION_DETECTED,
                payloads.motion_detected(device_id=self.args.mqtt_client_id, sensor_id="software-motion", active=self.motion_active),
            )
            return
        if event_type == "session" and event.get("state") in {"starting", "streaming", "monitoring"}:
            self.session_state = event["state"]
            session_id = event.get("stream_session_id")
            self.session_id = session_id if isinstance(session_id, str) else None
            self.publish_status(f"publisher session {self.session_state}")
            return
        if event_type == "runtime_error" and isinstance(event.get("message"), str):
            self.publish(
                error_rtsp_topic(self.args.mqtt_client_id),
                payloads.error_event(component="rtsp-publisher", device_id=self.args.mqtt_client_id, message=event["message"]),
            )

    def on_message(self, topic: str, message: dict) -> None:
        if topic == stream_activity_topic(self.args.mqtt_client_id):
            if (
                message.get("schema_version") == payloads.SCHEMA_VERSION
                and message.get("device_id") == self.args.mqtt_client_id
                and message.get("action") == "face_presence"
                and isinstance(message.get("stream_session_id"), str)
                and isinstance(message.get("face_count"), int)
                and not isinstance(message.get("face_count"), bool)
            ):
                self.channel.send({"type": "face_presence", **message})
            return
        if topic != control_stream_topic(self.args.mqtt_client_id):
            return
        try:
            command = validate_command(message, self.args.mqtt_client_id)
        except CommandValidationError as error:
            command_id = message.get("command_id", "") if isinstance(message, dict) else ""
            action = message.get("action", "unknown") if isinstance(message, dict) else "unknown"
            self.commands.put(InvalidCommand(str(command_id), str(action), str(error)))
            return
        self.commands.put(command)

    def process_command(self, command: EdgeCommand | InvalidCommand) -> None:
        if isinstance(command, InvalidCommand):
            ack = payloads.command_ack(
                command_id=command.command_id,
                target_device_id=self.args.mqtt_client_id,
                action=command.action,
                result="failed",
                message=command.error,
                state=self.supervisor.state.value,
            )
            self.publish(control_ack_topic(self.args.mqtt_client_id), ack)
            return
        ack = self.supervisor.handle(command)
        self.publish(control_ack_topic(self.args.mqtt_client_id), ack)
        self.publish_status(ack.get("message"))

    def on_connection_state(self, state: str) -> None:
        if state != "connected":
            return
        if self._first_connect:
            self._first_connect = False
            return
        try:
            self.publish_status()
        except Exception as error:
            print(f"[MQTT] status republish after reconnect failed: {error}", file=sys.stderr)

    def connect(self) -> None:
        self.client = MqttClient(
            host=self.args.mqtt_host,
            port=self.args.mqtt_port,
            client_id=self.args.mqtt_client_id,
            username=self.args.mqtt_username,
            password=password_from_env(self.args.mqtt_username, self.args.mqtt_password_env),
            ca_cert=self.args.mqtt_ca_cert,
            on_message=self.on_message,
            on_connection_state=self.on_connection_state,
        )
        self.client.connect()
        self.client.subscribe(
            control_stream_topic(self.args.mqtt_client_id),
            qos=topic_policy(TOPIC_CONTROL_STREAM).qos,
        )
        if self.args.motion_triggered:
            self.client.subscribe(stream_activity_topic(self.args.mqtt_client_id), qos=1)

    def start_publisher(self) -> None:
        self.supervisor.machine.transition(EdgeState.STARTING)
        try:
            self.start_runtime()
            self.supervisor.machine.transition(EdgeState.STREAMING)
        except Exception as error:
            self.supervisor.machine.transition(EdgeState.ERROR)
            self.publish(
                error_rtsp_topic(self.args.mqtt_client_id),
                payloads.error_event(
                    component="edge-agent",
                    device_id=self.args.mqtt_client_id,
                    message=str(error),
                ),
            )

    def run(self) -> int:
        self.connect()
        try:
            self.start_publisher()
            self.publish_status()
            next_heartbeat = time.monotonic() + self.args.heartbeat_interval
            while True:
                try:
                    command = self.commands.get(timeout=0.25)
                except queue.Empty:
                    command = None
                if command is not None:
                    self.process_command(command)
                if time.monotonic() >= next_heartbeat:
                    self.publish_status()
                    next_heartbeat = time.monotonic() + self.args.heartbeat_interval
        except KeyboardInterrupt:
            return 0
        finally:
            self.stop_runtime()
            self.channel.close()
            if self.client is not None:
                self.client.close()


def main() -> int:
    return EdgeAgent(parse_args()).run()


if __name__ == "__main__":
    raise SystemExit(main())
