import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from aiot.mqtt import payloads
from aiot.mqtt.audit_logger import AUDIT_TOPICS, AuditStore
from aiot.mqtt.client import MqttClient, MqttConnectionError, MqttPublishError, MqttUnavailable
from aiot.mqtt.topics import (
    TOPIC_ERROR_PIPELINE,
    TOPIC_MOTION_DETECTED,
    TOPIC_RECOGNITION_RESULT,
    control_ack_topic,
    control_stream_topic,
    error_pipeline_topic,
    system_status_topic,
    topic_policy,
)


def integration_enabled() -> bool:
    return os.environ.get("AIOT_RUN_MQTT_INTEGRATION") == "1"


@unittest.skipUnless(integration_enabled(), "Set AIOT_RUN_MQTT_INTEGRATION=1 with Mosquitto running.")
class MosquittoIntegrationTests(unittest.TestCase):
    host = os.environ.get("AIOT_MQTT_HOST", "127.0.0.1")
    port = int(os.environ.get("AIOT_MQTT_PORT", "1883"))

    def connect_client(self, client_id: str, username: str, password: str, on_message=None) -> MqttClient:
        client = MqttClient(
            host=self.host,
            port=self.port,
            client_id=client_id,
            username=username,
            password=password,
            on_message=on_message,
        )
        client.connect(timeout=5.0)
        return client

    def test_broker_rejects_bad_password(self):
        with self.assertRaises((MqttConnectionError, MqttUnavailable)):
            self.connect_client("bad-auth-test", "aiot-edge", "wrong-password")

    def test_audit_logger_persists_only_configured_topics_and_redacts_rtsp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                store = AuditStore(database_dir / "audit.sqlite3")
                logger = None
                edge = None
                recognizer = None
                try:
                    logger = self.connect_client(
                        "integration-logger",
                        "aiot-logger",
                        "logger-secret",
                        on_message=lambda topic, message: store.record(topic, message),
                    )
                    for topic in AUDIT_TOPICS:
                        logger.subscribe(topic, qos=topic_policy(topic).qos)

                    edge = self.connect_client("integration-edge", "aiot-edge", "edge-secret")
                    recognizer = self.connect_client(
                        "integration-recognizer", "aiot-recognition", "recognition-secret"
                    )
                    recognizer.publish(
                        TOPIC_RECOGNITION_RESULT,
                        payloads.recognition_result(
                            source="rtsp://admin:secret@example.test:8554/camera",
                            frame_id=1,
                            result_id=1,
                            latency_ms=4.2,
                            tracks=[],
                            events=[],
                        ),
                        qos=1,
                    )
                    edge.publish(
                        TOPIC_MOTION_DETECTED,
                        payloads.motion_detected(device_id="pi4-edge-01", sensor_id="pir-1", active=True),
                        qos=1,
                    )
                    edge.publish(
                        control_ack_topic("pi4-edge-01"),
                        payloads.command_ack(
                            command_id="integration-stop-1",
                            target_device_id="pi4-edge-01",
                            action="stop",
                            result="succeeded",
                            message="stopped",
                            state="stopped",
                        ),
                        qos=1,
                    )
                    recognizer.publish(
                        error_pipeline_topic("pi4-edge-01"),
                        payloads.error_event(
                            component="recognition",
                            device_id="pi4-edge-01",
                            message="pipeline failed",
                        ),
                        qos=1,
                    )
                    edge.publish(
                        system_status_topic("pi4-edge-01"),
                        payloads.system_status(
                            device_id="pi4-edge-01",
                            component="rtsp-publisher",
                            state="running",
                        ),
                        qos=0,
                        retain=True,
                    )

                    deadline = time.time() + 5.0
                    rows = []
                    while time.time() < deadline:
                        rows = store._connection.execute(
                            "SELECT topic, payload_json FROM mqtt_audit_events ORDER BY id"
                        ).fetchall()
                        if len(rows) >= 4:
                            break
                        time.sleep(0.1)
                finally:
                    for client in (logger, edge, recognizer):
                        if client is not None:
                            client.close()
                    store.close()

        topics = [row[0] for row in rows]
        payload_json = "\n".join(row[1] for row in rows)
        self.assertEqual(
            topics,
            [
                TOPIC_RECOGNITION_RESULT,
                TOPIC_MOTION_DETECTED,
                control_ack_topic("pi4-edge-01"),
                error_pipeline_topic("pi4-edge-01"),
            ],
        )
        self.assertIn("rtsp://***:***@example.test:8554/camera", payload_json)
        self.assertNotIn("secret", payload_json)
        self.assertNotIn(system_status_topic("pi4-edge-01"), topics)

    def test_controller_can_publish_to_the_scoped_edge_control_topic(self):
        received = []
        received_event = threading.Event()
        edge = None
        controller = None
        try:
            edge = MqttClient(
                host=self.host,
                port=self.port,
                client_id="integration-edge-control",
                username="aiot-edge",
                password="edge-secret",
                on_message=lambda topic, message: (received.append((topic, message)), received_event.set()),
            )
            edge.subscribe(control_stream_topic("pi4-edge-01"), qos=1)
            edge.connect(timeout=5.0)
            controller = self.connect_client("integration-controller", "aiot-controller", "controller-secret")
            command = payloads.stream_control(
                action="stop", target_device_id="pi4-edge-01", command_id="integration-stop-1"
            )
            controller.publish(control_stream_topic("pi4-edge-01"), command, qos=1)

            self.assertTrue(received_event.wait(5.0))
            self.assertEqual(received, [(control_stream_topic("pi4-edge-01"), command)])
        finally:
            if controller is not None:
                controller.close()
            if edge is not None:
                edge.close()

    def test_edge_can_publish_ack_and_controller_can_read_it(self):
        received = []
        received_event = threading.Event()
        edge = self.connect_client("integration-edge-ack", "aiot-edge", "edge-secret")
        controller = MqttClient(
            host=self.host,
            port=self.port,
            client_id="integration-controller-ack",
            username="aiot-controller",
            password="controller-secret",
            on_message=lambda topic, message: (received.append((topic, message)), received_event.set()),
        )
        try:
            controller.subscribe(control_ack_topic("pi4-edge-01"), qos=1)
            controller.connect(timeout=5.0)
            ack = payloads.command_ack(
                command_id="integration-start-1",
                target_device_id="pi4-edge-01",
                action="start",
                result="succeeded",
                message="runtime started",
            )
            edge.publish(control_ack_topic("pi4-edge-01"), ack, qos=1)
            self.assertTrue(received_event.wait(5.0))
            self.assertEqual(received, [(control_ack_topic("pi4-edge-01"), ack)])
        finally:
            controller.close()
            edge.close()

    def test_edge_publish_to_control_topic_is_rejected(self):
        edge = self.connect_client("integration-edge-denied", "aiot-edge", "edge-secret")
        try:
            topic = control_stream_topic("pi4-edge-01")
            message = payloads.stream_control(
                action="stop",
                target_device_id="pi4-edge-01",
                command_id="integration-denied-1",
            )
            with self.assertRaises(MqttPublishError):
                edge.publish(topic, message, qos=1)
        finally:
            edge.close()

    def test_retained_status_is_delivered_to_late_subscriber(self):
        received = []
        edge = self.connect_client("integration-edge-retained", "aiot-edge", "edge-secret")
        subscriber = MqttClient(
            host=self.host,
            port=self.port,
            client_id="integration-recognition-retained",
            username="aiot-recognition",
            password="recognition-secret",
            on_message_metadata=lambda topic, message, retained: received.append((topic, message, retained)),
        )
        try:
            status = payloads.system_status(
                device_id="pi4-edge-01",
                component="rtsp-publisher",
                state="stopped",
            )
            edge.publish(system_status_topic("pi4-edge-01"), status, qos=0, retain=True)
            subscriber.subscribe(system_status_topic("pi4-edge-01"), qos=0)
            subscriber.connect(timeout=5.0)
            deadline = time.time() + 5.0
            while time.time() < deadline and not received:
                time.sleep(0.1)
            self.assertEqual(len(received), 1)
            topic, message, retained = received[0]
            self.assertEqual(topic, system_status_topic("pi4-edge-01"))
            self.assertTrue(retained)
            self.assertEqual(message["state"], "stopped")
        finally:
            edge.close()
            subscriber.close()

    def test_broker_restart_reconnects_and_replays_retained_status(self):
        project_root = Path(__file__).resolve().parents[1]
        received = []
        edge = self.connect_client("integration-edge-restart", "aiot-edge", "edge-secret")
        subscriber = MqttClient(
            host=self.host,
            port=self.port,
            client_id="integration-recognition-restart",
            username="aiot-recognition",
            password="recognition-secret",
            on_message=lambda topic, message: received.append((topic, message)),
        )
        try:
            edge.publish(
                system_status_topic("pi4-edge-01"),
                payloads.system_status(
                    device_id="pi4-edge-01",
                    component="rtsp-publisher",
                    state="streaming",
                ),
                qos=0,
                retain=True,
            )
            subscriber.subscribe(system_status_topic("pi4-edge-01"), qos=0)
            subscriber.connect(timeout=5.0)
            deadline = time.time() + 5.0
            while time.time() < deadline and not received:
                time.sleep(0.1)
            received.clear()
            result = subprocess.run(
                ["docker", "compose", "restart", "mosquitto"],
                cwd=project_root,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            deadline = time.time() + 30.0
            while time.time() < deadline and not received:
                time.sleep(0.2)
            self.assertGreater(len(received), 0)
            self.assertIn(system_status_topic("pi4-edge-01"), [item[0] for item in received])
        finally:
            edge.close()
            subscriber.close()


if __name__ == "__main__":
    unittest.main()
