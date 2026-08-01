import tempfile
import unittest
from pathlib import Path

from aiot.mqtt.audit_logger import AuditStore
from aiot.mqtt import payloads
from aiot.mqtt.topics import (
    AUDIT_TOPICS,
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
    def test_record_persists_payload_to_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "audit.sqlite3"
            store = AuditStore(db_path)
            try:
                message = payloads.motion_detected(
                    device_id="pi4-edge",
                    sensor_id="pir-1",
                    active=True,
                )
                store.record(TOPIC_MOTION_DETECTED, message)

                rows = store._connection.execute(
                    "SELECT topic, event_ts_ms, schema_version, payload_json FROM mqtt_audit_events"
                ).fetchall()
            finally:
                store.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], TOPIC_MOTION_DETECTED)
        self.assertEqual(rows[0][1], message["ts_ms"])
        self.assertEqual(rows[0][2], 1)
        self.assertIn('"device_id": "pi4-edge"', rows[0][3])


if __name__ == "__main__":
    unittest.main()
