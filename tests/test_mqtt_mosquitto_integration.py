import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from aiot.mqtt import payloads
from aiot.mqtt.audit_logger import AUDIT_TOPICS, AuditStore
from aiot.mqtt.client import MqttClient, MqttConnectionError, MqttUnavailable
from aiot.mqtt.topics import (
    TOPIC_ERROR_PIPELINE,
    TOPIC_MOTION_DETECTED,
    TOPIC_RECOGNITION_RESULT,
    control_stream_topic,
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
                    recognizer.publish(
                        TOPIC_ERROR_PIPELINE,
                        payloads.error_event(component="recognition", message="pipeline failed"),
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
                        if len(rows) >= 3:
                            break
                        time.sleep(0.1)
                finally:
                    for client in (logger, edge, recognizer):
                        if client is not None:
                            client.close()
                    store.close()

        topics = [row[0] for row in rows]
        payload_json = "\n".join(row[1] for row in rows)
        self.assertEqual(topics, [TOPIC_RECOGNITION_RESULT, TOPIC_MOTION_DETECTED, TOPIC_ERROR_PIPELINE])
        self.assertIn("rtsp://***:***@example.test:8554/camera", payload_json)
        self.assertNotIn("secret", payload_json)
        self.assertNotIn(system_status_topic("pi4-edge-01"), topics)

    def test_control_topic_is_scoped_per_device(self):
        self.assertEqual(control_stream_topic("pi4-edge-01"), "control/stream/pi4-edge-01")


if __name__ == "__main__":
    unittest.main()
