import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiot.mqtt import payloads
from aiot.mqtt.audit_logger import AuditStore, is_audit_topic, query_audit_events, topic_matches
from aiot.mqtt.topics import (
    TOPIC_CONTROL_ACK,
    TOPIC_ERROR_PIPELINE,
    TOPIC_MOTION_DETECTED,
    TOPIC_RECOGNITION_RESULT,
    control_ack_topic,
    control_stream_topic,
)


class AuditTopicFilterTests(unittest.TestCase):
    def test_control_ack_is_audited(self):
        self.assertTrue(is_audit_topic(control_ack_topic("edge-1")))

    def test_control_stream_is_not_audited(self):
        self.assertFalse(is_audit_topic(control_stream_topic("edge-1")))

    def test_topic_matches_supports_plus_wildcards(self):
        self.assertTrue(topic_matches("control/ack/+", "control/ack/edge-1"))
        self.assertFalse(topic_matches("control/ack/+", "control/ack/edge-1/extra"))
        self.assertFalse(topic_matches("control/ack/+", "control/ack"))


def valid_ack(**overrides):
    message = payloads.command_ack(
        command_id="cmd-001",
        target_device_id="pi4-edge-01",
        action="stop",
        result="succeeded",
        message="stopped",
        state="stopped",
    )
    message.update(overrides)
    return message


class ControlAckAuditTests(unittest.TestCase):
    def test_record_persists_control_ack(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            db_path = database_dir / "audit.sqlite3"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                store = AuditStore(db_path)
                try:
                    store.record(control_ack_topic("pi4-edge-01"), valid_ack())
                    rows = store._connection.execute(
                        "SELECT topic, payload_json FROM mqtt_audit_events"
                    ).fetchall()
                finally:
                    store.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], control_ack_topic("pi4-edge-01"))
        self.assertIn('"command_id": "cmd-001"', rows[0][1])
        self.assertIn('"state": "stopped"', rows[0][1])

    def test_record_rejects_invalid_control_ack(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                store = AuditStore(database_dir / "audit.sqlite3")
                try:
                    topic = control_ack_topic("pi4-edge-01")

                    def assert_rejected(payload):
                        with self.assertRaises(ValueError):
                            store.record(topic, payload)

                    invalid_cases = [
                        valid_ack(command_id=""),
                        valid_ack(target_device_id=None),
                        valid_ack(action=""),
                        valid_ack(result=""),
                        valid_ack(message=42),
                        valid_ack(state=7),
                        valid_ack(schema_version=2),
                    ]
                    for payload in invalid_cases:
                        assert_rejected(payload)
                finally:
                    store.close()

    def test_ack_without_state_is_valid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                store = AuditStore(database_dir / "audit.sqlite3")
                try:
                    store.record(control_ack_topic("pi4-edge-01"), valid_ack(state=None))
                finally:
                    store.close()


class QueryAuditEventsTests(unittest.TestCase):
    def _seed(self, database_dir: Path, events) -> Path:
        db_path = database_dir / "audit.sqlite3"
        store = AuditStore(db_path)
        try:
            for topic, payload in events:
                store.record(topic, payload)
        finally:
            store.close()
        return db_path

    def _seeded_events(self):
        return [
            (
                TOPIC_MOTION_DETECTED,
                payloads.motion_detected(device_id="edge-1", sensor_id="motion", active=True),
            ),
            (
                TOPIC_RECOGNITION_RESULT,
                payloads.recognition_result(
                    source="rtsp://127.0.0.1:8554/camera",
                    frame_id=1,
                    result_id=1,
                    latency_ms=1.0,
                    tracks=[],
                    events=[],
                ),
            ),
            (
                TOPIC_ERROR_PIPELINE,
                payloads.error_event(component="recognition", message="boom"),
            ),
            (
                control_ack_topic("edge-1"),
                valid_ack(command_id="cmd-002"),
            ),
        ]

    def test_returns_newest_first_and_decodes_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                db_path = self._seed(database_dir, self._seeded_events())
                rows = query_audit_events(db_path)

        self.assertEqual([row["topic"] for row in rows], [
            control_ack_topic("edge-1"),
            TOPIC_ERROR_PIPELINE,
            TOPIC_RECOGNITION_RESULT,
            TOPIC_MOTION_DETECTED,
        ])
        self.assertEqual(rows[3]["payload"]["sensor_id"], "motion")
        self.assertIn("event_ts_ms", rows[3])
        self.assertIn("received_at", rows[3])

    def test_filters_by_topic_pattern(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                db_path = self._seed(database_dir, self._seeded_events())

                errors = query_audit_events(db_path, topics=["error/#"])
                acks = query_audit_events(db_path, topics=["control/ack/edge-1"])

        self.assertEqual([row["topic"] for row in errors], [TOPIC_ERROR_PIPELINE])
        self.assertEqual([row["topic"] for row in acks], [control_ack_topic("edge-1")])

    def test_limit_offset_and_since(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                db_path = self._seed(database_dir, self._seeded_events())
                rows = query_audit_events(db_path)
                oldest_ts = rows[-1]["event_ts_ms"]

                limited = query_audit_events(db_path, limit=2)
                offset = query_audit_events(db_path, limit=2, offset=2)
                since = query_audit_events(db_path, since_ts_ms=oldest_ts)

        self.assertEqual(len(limited), 2)
        self.assertNotEqual([row["id"] for row in limited], [row["id"] for row in offset])
        self.assertEqual(len(since), 4)

    def test_missing_database_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_dir = Path(temp_dir) / "database"
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", database_dir):
                rows = query_audit_events(database_dir / "audit.sqlite3")

        self.assertEqual(rows, [])

    def test_invalid_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("aiot.mqtt.audit_logger.AUDIT_DB_DIR", Path(temp_dir) / "database"):
                with self.assertRaises(ValueError):
                    query_audit_events(Path(temp_dir) / "outside.sqlite3")


if __name__ == "__main__":
    unittest.main()
