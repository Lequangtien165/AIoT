import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiot.mqtt.audit_logger import AuditStore, is_audit_topic, parse_args, resolve_audit_db_path
from aiot.mqtt import payloads
from aiot.mqtt.topics import (
    AUDIT_TOPICS,
    TOPIC_ERROR_RTSP,
    TOPIC_ERROR_PIPELINE,
    TOPIC_MOTION_DETECTED,
    TOPIC_RECOGNITION_RESULT,
    TOPIC_SYSTEM_STATUS,
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
        self.assertFalse(is_audit_topic("control/stream"))

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
                        source="rtsp://127.0.0.1:8554/camera",
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


if __name__ == "__main__":
    unittest.main()
