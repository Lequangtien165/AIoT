import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiot.mqtt.audit_logger import AuditStore, is_audit_topic, parse_args, resolve_audit_db_path
from aiot.mqtt.client import (
    MqttClient,
    MqttConnectionError,
    MqttPublishError,
    MqttSubscriptionError,
    reason_code_failed,
)
from aiot.mqtt import payloads
from aiot.mqtt.topics import (
    AUDIT_TOPICS,
    TOPIC_ERROR_RTSP,
    TOPIC_ERROR_PIPELINE,
    TOPIC_MOTION_DETECTED,
    TOPIC_RECOGNITION_RESULT,
    TOPIC_SYSTEM_STATUS,
    control_stream_topic,
    error_pipeline_topic,
    stream_activity_topic,
    system_status_topic,
)


class PayloadBuilderTests(unittest.TestCase):
    def test_recognition_result_has_stable_schema_fields(self):
        message = payloads.recognition_result(
            source="rtsp://127.0.0.1:8554/camera",
            frame_id=10,
            result_id=2,
            latency_ms=12.34567,
            tracks=[{"track_id": 1, "status": "matched"}],
            events=[{"kind": "identity_confirmed"}],
        )

        self.assertEqual(message["schema_version"], 1)
        self.assertEqual(message["source"], "rtsp://127.0.0.1:8554/camera")
        self.assertEqual(message["frame_id"], 10)
        self.assertEqual(message["result_id"], 2)
        self.assertEqual(message["latency_ms"], 12.346)
        self.assertEqual(message["tracks"][0]["track_id"], 1)
        self.assertEqual(message["events"][0]["kind"], "identity_confirmed")

    def test_topic_set_covers_control_plane_and_audit_events(self):
        self.assertEqual(TOPIC_SYSTEM_STATUS, "system/status")
        self.assertEqual(TOPIC_RECOGNITION_RESULT, "recognition/result")
        self.assertEqual(TOPIC_MOTION_DETECTED, "motion/detected")
        self.assertEqual(TOPIC_ERROR_PIPELINE, "error/pipeline")
        self.assertIn("error/#", AUDIT_TOPICS)
        self.assertEqual(error_pipeline_topic("edge-1"), "error/pipeline/edge-1")
        self.assertEqual(stream_activity_topic("edge-1"), "stream/activity/edge-1")

    def test_redacts_rtsp_credentials_in_payloads(self):
        url = "rtsp://admin:secret@example.test:8554/camera?profile=1"

        self.assertEqual(
            payloads.redact_rtsp_url(url),
            "rtsp://***:***@example.test:8554/camera?profile=1",
        )
        self.assertEqual(payloads.redact_rtsp_url("rtsp://example.test/camera"), "rtsp://example.test/camera")

        message = payloads.error_event(
            component="recognition",
            source=url,
            message="failed",
            details={"last_source": url},
        )

        self.assertEqual(message["source"], "rtsp://***:***@example.test:8554/camera?profile=1")
        self.assertEqual(
            message["details"]["last_source"],
            "rtsp://***:***@example.test:8554/camera?profile=1",
        )

    def test_stream_control_requires_target_device_id(self):
        message = payloads.stream_control(action="stop", target_device_id="edge-1")

        self.assertEqual(message["target_device_id"], "edge-1")

    def test_face_presence_has_session_and_face_count(self):
        message = payloads.face_presence(device_id="edge-1", stream_session_id="session-1", face_count=1)

        self.assertEqual(message["action"], "face_presence")
        self.assertEqual(message["stream_session_id"], "session-1")


class MqttClientTests(unittest.TestCase):
    def test_reason_code_failed_supports_paho_integer_codes(self):
        self.assertFalse(reason_code_failed(0))
        self.assertTrue(reason_code_failed(5))

    def test_reason_code_failed_supports_paho_reason_code_objects(self):
        success = type("ReasonCode", (), {"value": 0})()
        failure = type("ReasonCode", (), {"value": 135})()

        self.assertFalse(reason_code_failed(success))
        self.assertTrue(reason_code_failed(failure))

    @patch("aiot.mqtt.client._load_mqtt_module")
    def test_connect_raises_when_broker_rejects_connack(self, load_mqtt):
        fake_module = FakeMqttModule(connect_reason=5)
        load_mqtt.return_value = fake_module
        client = MqttClient(host="127.0.0.1", port=1883, client_id="test")

        with self.assertRaises(MqttConnectionError):
            client.connect(timeout=0.1)

    @patch("aiot.mqtt.client._load_mqtt_module")
    def test_connect_raises_when_connack_times_out(self, load_mqtt):
        fake_module = FakeMqttModule(connect_reason=None)
        load_mqtt.return_value = fake_module
        client = MqttClient(host="127.0.0.1", port=1883, client_id="test")

        with self.assertRaises(MqttConnectionError):
            client.connect(timeout=0.01)

    @patch("aiot.mqtt.client._load_mqtt_module")
    def test_publish_raises_when_paho_reports_failure(self, load_mqtt):
        fake_module = FakeMqttModule(connect_reason=0, publish_rc=4)
        load_mqtt.return_value = fake_module
        client = MqttClient(host="127.0.0.1", port=1883, client_id="test")
        client.connect(timeout=0.1)

        with self.assertRaises(MqttPublishError):
            client.publish("recognition/result", {"schema_version": 1}, qos=1)

    @patch("aiot.mqtt.client._load_mqtt_module")
    def test_publish_raises_when_qos_delivery_times_out(self, load_mqtt):
        fake_module = FakeMqttModule(connect_reason=0, publish_completed=False)
        load_mqtt.return_value = fake_module
        client = MqttClient(host="127.0.0.1", port=1883, client_id="test")
        client.connect(timeout=0.1)

        with self.assertRaises(MqttPublishError):
            client.publish("recognition/result", {"schema_version": 1}, qos=1)

    @patch("aiot.mqtt.client._load_mqtt_module")
    def test_connect_raises_when_subscription_is_rejected(self, load_mqtt):
        fake_module = FakeMqttModule(connect_reason=0, subscription_reason=135)
        load_mqtt.return_value = fake_module
        client = MqttClient(host="127.0.0.1", port=1883, client_id="test")
        client.subscribe("control/stream/test", qos=1)

        with self.assertRaises(MqttSubscriptionError):
            client.connect(timeout=0.1)

    @patch("aiot.mqtt.client._load_mqtt_module")
    def test_client_configures_tls_with_the_supplied_ca_certificate(self, load_mqtt):
        fake_module = FakeMqttModule(connect_reason=0)
        load_mqtt.return_value = fake_module

        MqttClient(host="broker.example", port=8883, client_id="test", ca_cert="certs/ca.crt")

        self.assertEqual(fake_module.last_client.tls_ca_cert, "certs/ca.crt")


class FakePublishInfo:
    def __init__(self, rc: int, completed: bool) -> None:
        self.rc = rc
        self.completed = completed

    def wait_for_publish(self, timeout: float | None = None) -> None:
        return None

    def is_published(self) -> bool:
        return self.completed


class FakePahoClient:
    def __init__(self, module, **_kwargs) -> None:
        self.module = module
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.subscriptions = []
        self.tls_ca_cert = None

    def username_pw_set(self, _username, _password) -> None:
        pass

    def tls_set(self, *, ca_certs: str) -> None:
        self.tls_ca_cert = ca_certs

    def reconnect_delay_set(self, min_delay: int, max_delay: int) -> None:
        self.reconnect_delay = (min_delay, max_delay)

    def connect(self, _host, _port, keepalive: int) -> None:
        self.keepalive = keepalive

    def loop_start(self) -> None:
        if self.module.connect_reason is not None and self.on_connect is not None:
            self.on_connect(self, None, None, self.module.connect_reason, None)

    def loop_stop(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscriptions.append((topic, qos))
        mid = len(self.subscriptions)
        if self.on_subscribe is not None:
            self.on_subscribe(self, None, mid, [self.module.subscription_reason], None)
        return self.module.MQTT_ERR_SUCCESS, mid

    def publish(self, _topic, _payload, qos: int = 0, retain: bool = False) -> FakePublishInfo:
        return FakePublishInfo(self.module.publish_rc, self.module.publish_completed)


class FakeMqttModule:
    MQTT_ERR_SUCCESS = 0

    class CallbackAPIVersion:
        VERSION2 = object()

    def __init__(
        self,
        *,
        connect_reason: int | None,
        publish_rc: int = 0,
        publish_completed: bool = True,
        subscription_reason: int = 0,
    ) -> None:
        self.connect_reason = connect_reason
        self.publish_rc = publish_rc
        self.publish_completed = publish_completed
        self.subscription_reason = subscription_reason
        self.last_client = None

    def Client(self, **kwargs):
        self.last_client = FakePahoClient(self, **kwargs)
        return self.last_client


class AuditStoreTests(unittest.TestCase):
    @patch(
        "sys.argv",
        [
            "run_mqtt_logger.py",
            "--mqtt-host",
            "127.0.0.1",
            "--mqtt-port",
            "1884",
            "--client-id",
            "logger-test",
            "--mqtt-username",
            "logger",
            "--mqtt-password-env",
            "AIOT_MQTT_PASSWORD",
        ],
    )
    @patch.dict("os.environ", {"AIOT_MQTT_PASSWORD": "secret"})
    def test_parse_args_supports_mqtt_auth_flags(self):
        args = parse_args()

        self.assertEqual(args.mqtt_host, "127.0.0.1")
        self.assertEqual(args.mqtt_port, 1884)
        self.assertEqual(args.client_id, "logger-test")
        self.assertEqual(args.mqtt_username, "logger")
        self.assertEqual(args.mqtt_password_env, "AIOT_MQTT_PASSWORD")

    @patch("sys.argv", ["run_mqtt_logger.py", "--mqtt-username", "logger"])
    @patch.dict("os.environ", {}, clear=True)
    def test_mqtt_username_requires_password_env(self):
        with self.assertRaises(SystemExit):
            parse_args()

    def test_audit_topic_filter_matches_configured_topics(self):
        self.assertTrue(is_audit_topic(TOPIC_RECOGNITION_RESULT))
        self.assertTrue(is_audit_topic(TOPIC_MOTION_DETECTED))
        self.assertTrue(is_audit_topic(TOPIC_ERROR_RTSP))
        self.assertTrue(is_audit_topic(TOPIC_ERROR_PIPELINE))
        self.assertFalse(is_audit_topic(TOPIC_SYSTEM_STATUS))
        self.assertFalse(is_audit_topic(system_status_topic("edge-1")))
        self.assertFalse(is_audit_topic("control/stream"))
        self.assertFalse(is_audit_topic(control_stream_topic("edge-1")))

    def test_record_persists_audited_payloads_to_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            db_path = database_dir / "audit.sqlite3"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                store = AuditStore(db_path)
                try:
                    motion = payloads.motion_detected(
                        device_id="pi4-edge",
                        sensor_id="pir-1",
                        active=True,
                    )
                    recognition = payloads.recognition_result(
                        source="rtsp://admin:secret@127.0.0.1:8554/camera",
                        frame_id=10,
                        result_id=2,
                        latency_ms=12.3,
                        tracks=[],
                        events=[],
                    )
                    error = payloads.error_event(
                        component="recognition",
                        message="pipeline failed",
                    )
                    store.record(TOPIC_MOTION_DETECTED, motion)
                    store.record(TOPIC_RECOGNITION_RESULT, recognition)
                    store.record(TOPIC_ERROR_PIPELINE, error)

                    rows = store._connection.execute(
                        "SELECT topic, event_ts_ms, schema_version, payload_json "
                        "FROM mqtt_audit_events ORDER BY id"
                    ).fetchall()
                finally:
                    store.close()

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][0], TOPIC_MOTION_DETECTED)
        self.assertEqual(rows[0][1], motion["ts_ms"])
        self.assertEqual(rows[0][2], 1)
        self.assertIn('"device_id": "pi4-edge"', rows[0][3])
        self.assertEqual(rows[1][0], TOPIC_RECOGNITION_RESULT)
        self.assertIn("rtsp://***:***@127.0.0.1:8554/camera", rows[1][3])
        self.assertNotIn("secret", rows[1][3])
        self.assertIn('"result_id": 2', rows[1][3])
        self.assertEqual(rows[2][0], TOPIC_ERROR_PIPELINE)
        self.assertIn('"message": "pipeline failed"', rows[2][3])

    def test_audit_database_path_rejects_paths_outside_database_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                with self.assertRaises(ValueError):
                    resolve_audit_db_path(Path(temp_dir) / "outside.sqlite3")
                with self.assertRaises(ValueError):
                    resolve_audit_db_path("file:audit.sqlite3")
                with self.assertRaises(ValueError):
                    resolve_audit_db_path(database_dir / "audit.db")

    def test_audit_database_path_accepts_sqlite_file_below_database_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            path = database_dir / "nested" / "audit.sqlite3"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                self.assertEqual(resolve_audit_db_path(path), path.resolve())

    def test_record_rejects_invalid_schema_and_oversized_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            db_path = database_dir / "audit.sqlite3"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                store = AuditStore(db_path, max_payload_bytes=120)
                try:
                    with self.assertRaises(ValueError):
                        store.record(TOPIC_RECOGNITION_RESULT, {"schema_version": 2})
                    with self.assertRaises(ValueError):
                        store.record(
                            TOPIC_ERROR_PIPELINE,
                            {
                                "schema_version": 1,
                                "ts_ms": 1,
                                "component": "recognition",
                                "message": "x" * 200,
                            },
                        )
                finally:
                    store.close()

    def test_record_rejects_invalid_field_types(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                store = AuditStore(database_dir / "audit.sqlite3")
                try:
                    with self.assertRaises(ValueError):
                        store.record(
                            TOPIC_MOTION_DETECTED,
                            {
                                "schema_version": 1,
                                "ts_ms": True,
                                "device_id": "edge-1",
                                "sensor_id": "motion",
                                "active": "true",
                            },
                        )
                finally:
                    store.close()

    def test_age_retention_uses_local_receipt_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                store = AuditStore(database_dir / "audit.sqlite3", retention_days=1, max_records=0)
                try:
                    old_event_time = {
                        "schema_version": 1,
                        "ts_ms": 1,
                        "component": "recognition",
                        "message": "recently received",
                    }
                    store.record(error_pipeline_topic("edge-1"), old_event_time)
                    rows = store._connection.execute("SELECT payload_json FROM mqtt_audit_events").fetchall()
                    self.assertEqual(len(rows), 1)

                    store._connection.execute(
                        "UPDATE mqtt_audit_events SET received_at = datetime('now', '-2 days')"
                    )
                    store._connection.commit()
                    store.record(
                        error_pipeline_topic("edge-1"),
                        {
                            "schema_version": 1,
                            "ts_ms": 2,
                            "component": "recognition",
                            "message": "current",
                        },
                    )
                    rows = store._connection.execute("SELECT payload_json FROM mqtt_audit_events").fetchall()
                finally:
                    store.close()

        self.assertEqual(len(rows), 1)
        self.assertIn("current", rows[0][0])

    def test_record_applies_max_records_retention(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            db_path = database_dir / "audit.sqlite3"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                store = AuditStore(db_path, retention_days=0, max_records=2)
                try:
                    for index in range(3):
                        store.record(
                            TOPIC_ERROR_PIPELINE,
                            {
                                "schema_version": 1,
                                "ts_ms": index + 1,
                                "component": "recognition",
                                "message": f"error {index}",
                            },
                        )
                    rows = store._connection.execute(
                        "SELECT payload_json FROM mqtt_audit_events ORDER BY id"
                    ).fetchall()
                finally:
                    store.close()

        self.assertEqual(len(rows), 2)
        self.assertNotIn("error 0", rows[0][0])


if __name__ == "__main__":
    unittest.main()
