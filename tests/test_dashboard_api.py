import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiot.mqtt import payloads
from aiot.mqtt.audit_logger import AuditStore
from aiot.mqtt.topics import (
    TOPIC_MOTION_DETECTED,
    TOPIC_RECOGNITION_RESULT,
    control_ack_topic,
    control_stream_topic,
)
from aiot.recognition.wanted import DEFAULT_WANTED_CONFIG

try:
    from fastapi.testclient import TestClient
    from aiot.dashboard.server import DashboardConfig, create_app
    HAS_DASHBOARD_DEPS = True
except ImportError:
    HAS_DASHBOARD_DEPS = False
    TestClient = None


@unittest.skipUnless(HAS_DASHBOARD_DEPS, "dashboard deps not installed (requirements-dashboard.txt)")
class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database_dir = Path(self.temp.name) / "database"
        self.audit_patch = patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", self.database_dir)
        self.audit_patch.start()
        self.addCleanup(self.audit_patch.stop)

        db_path = self.database_dir / "audit.sqlite3"
        store = AuditStore(db_path)
        try:
            store.record(
                TOPIC_MOTION_DETECTED,
                payloads.motion_detected(device_id="pi4-edge-01", sensor_id="motion", active=True),
            )
            store.record(
                control_ack_topic("pi4-edge-01"),
                payloads.command_ack(
                    command_id="cmd-001",
                    target_device_id="pi4-edge-01",
                    action="stop",
                    result="succeeded",
                    message="stopped",
                    state="stopped",
                ),
            )
        finally:
            store.close()

        self.mqtt_patch = patch("aiot.dashboard.server.MqttClient")
        self.mqtt_mock = self.mqtt_patch.start()
        self.addCleanup(self.mqtt_patch.stop)

        self.config = DashboardConfig(
            audit_db=db_path,
            wanted_config=DEFAULT_WANTED_CONFIG,
            video_url="http://127.0.0.1:8889",
            video_path="camera",
        )
        self.app = create_app(self.config)

    def test_health_reports_mqtt_connected(self):
        with TestClient(self.app) as client:
            response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(response.json()["mqtt_connected"])

    def test_events_returns_seeded_audit_rows_newest_first(self):
        with TestClient(self.app) as client:
            response = client.get("/api/events")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(
            [row["topic"] for row in body["events"]],
            [control_ack_topic("pi4-edge-01"), TOPIC_MOTION_DETECTED],
        )
        self.assertEqual(body["events"][0]["payload"]["command_id"], "cmd-001")

    def test_events_filters_by_topic(self):
        with TestClient(self.app) as client:
            response = client.get("/api/events", params={"topic": "motion/detected"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["events"][0]["topic"], TOPIC_MOTION_DETECTED)

    def test_status_returns_empty_device_cache(self):
        with TestClient(self.app) as client:
            response = client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["devices"], {})

    def test_wanted_lists_configured_entries(self):
        with TestClient(self.app) as client:
            response = client.get("/api/wanted")

        self.assertEqual(response.status_code, 200)
        entries = response.json()["entries"]
        self.assertGreater(len(entries), 0)
        self.assertIn("match", entries[0])

    def test_control_publishes_command_and_returns_command_id(self):
        with TestClient(self.app) as client:
            response = client.post(
                "/api/control",
                json={"device_id": "pi4-edge-01", "action": "stop", "requested_by": "test"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["accepted"])
        publish_call = self.mqtt_mock.return_value.publish.call_args
        self.assertEqual(publish_call.args[0], control_stream_topic("pi4-edge-01"))
        self.assertEqual(publish_call.args[1]["action"], "stop")
        self.assertEqual(publish_call.args[1]["target_device_id"], "pi4-edge-01")
        self.assertEqual(publish_call.kwargs["qos"], 1)
        self.assertEqual(body["command_id"], publish_call.args[1]["command_id"])

    def test_control_rejects_unknown_action(self):
        with TestClient(self.app) as client:
            response = client.post(
                "/api/control",
                json={"device_id": "pi4-edge-01", "action": "explode"},
            )

        self.assertEqual(response.status_code, 422)

    def test_control_rejects_missing_device(self):
        with TestClient(self.app) as client:
            response = client.post("/api/control", json={"action": "start"})

        self.assertEqual(response.status_code, 422)

    def test_index_serves_dashboard_page(self):
        with TestClient(self.app) as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("AIoT Guard Console", response.text)

    def test_websocket_sends_hello_and_snapshots(self):
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws") as websocket:
                hello = websocket.receive_json()
                snapshot = websocket.receive_json()
                events = websocket.receive_json()

        self.assertEqual(hello["type"], "hello")
        self.assertEqual(hello["video"]["url"], "http://127.0.0.1:8889")
        self.assertEqual(snapshot["type"], "status_snapshot")
        self.assertEqual(events["type"], "events_snapshot")
        self.assertEqual(len(events["events"]), 2)

    def test_websocket_receives_broadcast_event(self):
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws") as websocket:
                websocket.receive_json()
                websocket.receive_json()
                websocket.receive_json()
                message = payloads.recognition_result(
                    source="rtsp://127.0.0.1:8554/camera",
                    frame_id=1,
                    result_id=1,
                    latency_ms=5.0,
                    tracks=[],
                    events=[],
                )
                self.app.state.hub.on_message(TOPIC_RECOGNITION_RESULT, message)
                received = websocket.receive_json()

        self.assertEqual(received["type"], "event")
        self.assertEqual(received["topic"], TOPIC_RECOGNITION_RESULT)
        self.assertEqual(received["payload"]["result_id"], 1)


if __name__ == "__main__":
    unittest.main()
