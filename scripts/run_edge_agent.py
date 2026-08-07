"""Run the persistent MQTT edge agent for a fixed local publisher runtime."""

from __future__ import annotations

import argparse
import queue
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aiot.mqtt import payloads
from aiot.mqtt.client import MqttClient, password_from_env
from aiot.mqtt.topics import (
    TOPIC_CONTROL_STREAM,
    control_ack_topic,
    control_stream_topic,
    error_rtsp_topic,
    system_status_topic,
    topic_policy,
)
from aiot.streaming.edge_supervisor import (
    EdgeCommand,
    EdgeState,
    EdgeSupervisor,
    CommandValidationError,
    validate_command,
)
from aiot.streaming.stream_settings import RTSP_HOST, RTSP_PORT


STREAM_SERVER = PROJECT_ROOT / "stream_server.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persistently supervise the edge RTSP publisher.")
    parser.add_argument("--device", required=True)
    parser.add_argument("--motion-triggered", action="store_true")
    parser.add_argument("--motion-device")
    parser.add_argument("--framerate", type=int, default=30)
    parser.add_argument("--video-size", default="1280x720")
    parser.add_argument("--bitrate", default="2M")
    parser.add_argument("--mqtt-host", required=True)
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-client-id", required=True)
    parser.add_argument("--mqtt-username")
    parser.add_argument("--mqtt-password-env")
    parser.add_argument("--mqtt-ca-cert")
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    args = parser.parse_args()
    if args.mqtt_username:
        try:
            password_from_env(args.mqtt_username, args.mqtt_password_env)
        except ValueError as error:
            parser.error(str(error))
    if args.mqtt_port <= 0 or args.heartbeat_interval <= 0:
        parser.error("--mqtt-port and --heartbeat-interval must be positive")
    return args


class EdgeAgent:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.commands: queue.Queue[EdgeCommand] = queue.Queue()
        self.process: subprocess.Popen[bytes] | None = None
        self.client: MqttClient | None = None
        self.supervisor = EdgeSupervisor(
            device_id=args.mqtt_client_id,
            start_runtime=self.start_runtime,
            stop_runtime=self.stop_runtime,
            runtime_alive=self.runtime_alive,
            rtsp_healthy=self.rtsp_healthy,
            mode="motion-triggered" if args.motion_triggered else "continuous",
        )

    def publisher_command(self) -> list[str]:
        command = [
            sys.executable,
            str(STREAM_SERVER),
            "--no-mqtt",
            "--device",
            self.args.device,
            "--framerate",
            str(self.args.framerate),
            "--video-size",
            self.args.video_size,
            "--bitrate",
            self.args.bitrate,
        ]
        if self.args.motion_triggered:
            command.append("--motion-triggered")
        if self.args.motion_device:
            command.extend(["--motion-device", self.args.motion_device])
        return command

    def start_runtime(self) -> None:
        if self.runtime_alive():
            return
        self.process = subprocess.Popen(self.publisher_command(), cwd=PROJECT_ROOT)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"publisher exited during startup with code {self.process.returncode}")
            if self.rtsp_healthy():
                return
            time.sleep(0.1)
        raise RuntimeError("RTSP endpoint did not become reachable during startup")

    def stop_runtime(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def runtime_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def rtsp_healthy(self) -> bool:
        if not self.runtime_alive():
            return False
        try:
            with socket.create_connection((RTSP_HOST, RTSP_PORT), timeout=0.2):
                return True
        except OSError:
            return False

    def publish(self, topic: str, message: dict, *, retain: bool | None = None) -> None:
        if self.client is None:
            return
        policy = topic_policy(topic)
        self.client.publish(
            topic,
            message,
            qos=policy.qos,
            retain=policy.retain if retain is None else retain,
        )

    def publish_status(self, message: str | None = None) -> None:
        self.supervisor.observe_runtime()
        status = self.supervisor.status()
        self.publish(
            system_status_topic(self.args.mqtt_client_id),
            payloads.system_status(
                device_id=self.args.mqtt_client_id,
                component="edge-agent",
                state=status["state"],
                message=message,
                metrics={
                    "mode": status["mode"],
                    "runtime_alive": status["runtime_alive"],
                    "rtsp_healthy": status["rtsp_healthy"],
                    "publisher_pid": self.process.pid if self.process else None,
                    "rtsp_url": f"rtsp://{RTSP_HOST}:{RTSP_PORT}/camera",
                },
            ),
        )

    def on_message(self, topic: str, message: dict) -> None:
        if topic != control_stream_topic(self.args.mqtt_client_id):
            return
        try:
            command = validate_command(message, self.args.mqtt_client_id)
        except CommandValidationError as error:
            self.publish(
                control_ack_topic(self.args.mqtt_client_id),
                payloads.command_ack(
                    command_id=str(message.get("command_id", "")) if isinstance(message, dict) else "",
                    target_device_id=self.args.mqtt_client_id,
                    action=str(message.get("action", "unknown")) if isinstance(message, dict) else "unknown",
                    result="failed",
                    message=str(error),
                ),
            )
            return
        self.commands.put(command)

    def connect(self) -> None:
        self.client = MqttClient(
            host=self.args.mqtt_host,
            port=self.args.mqtt_port,
            client_id=self.args.mqtt_client_id,
            username=self.args.mqtt_username,
            password=password_from_env(self.args.mqtt_username, self.args.mqtt_password_env),
            ca_cert=self.args.mqtt_ca_cert,
            on_message=self.on_message,
        )
        self.client.connect()
        self.client.subscribe(
            control_stream_topic(self.args.mqtt_client_id),
            qos=topic_policy(TOPIC_CONTROL_STREAM).qos,
        )

    def run(self) -> int:
        self.connect()
        try:
            self.supervisor.machine.transition(EdgeState.STARTING)
            self.publish_status("edge agent is starting the publisher")
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
            self.publish_status()
            next_heartbeat = time.monotonic() + self.args.heartbeat_interval
            while True:
                try:
                    command = self.commands.get(timeout=0.25)
                except queue.Empty:
                    command = None
                if command is not None:
                    ack = self.supervisor.handle(command)
                    self.publish(control_ack_topic(self.args.mqtt_client_id), ack)
                    self.publish_status(ack.get("message"))
                if time.monotonic() >= next_heartbeat:
                    self.publish_status()
                    next_heartbeat = time.monotonic() + self.args.heartbeat_interval
        except KeyboardInterrupt:
            return 0
        finally:
            self.stop_runtime()
            if self.client is not None:
                self.client.close()


def main() -> int:
    return EdgeAgent(parse_args()).run()


if __name__ == "__main__":
    raise SystemExit(main())
