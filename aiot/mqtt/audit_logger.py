"""SQLite audit logger for selected MQTT events."""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from aiot.mqtt.client import MqttClient, password_from_env
from aiot.mqtt.payloads import SCHEMA_VERSION, redact_sensitive_values
from aiot.mqtt.topics import AUDIT_TOPICS, topic_policy


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DB_DIR = PROJECT_ROOT / "database"
MAX_PAYLOAD_BYTES = 16 * 1024
DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_RECORDS = 100_000


REQUIRED_FIELDS_BY_TOPIC = {
    "recognition/result": {"schema_version", "ts_ms", "frame_id", "result_id", "tracks", "events"},
    "motion/detected": {"schema_version", "ts_ms", "device_id", "sensor_id", "active"},
}


def is_audit_topic(topic: str) -> bool:
    for subscription in AUDIT_TOPICS:
        if subscription.endswith("/#") and topic.startswith(subscription[:-1]):
            return True
        if topic == subscription:
            return True
    return False


def required_fields_for_topic(topic: str) -> set[str]:
    if topic.startswith("error/"):
        return {"schema_version", "ts_ms", "component", "message"}
    return REQUIRED_FIELDS_BY_TOPIC.get(topic, set())


def validate_audit_payload(topic: str, payload: dict[str, Any], max_payload_bytes: int = MAX_PAYLOAD_BYTES) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version for {topic}.")
    missing = sorted(required_fields_for_topic(topic) - payload.keys())
    if missing:
        raise ValueError(f"Missing required audit fields for {topic}: {', '.join(missing)}.")
    redacted_payload = redact_sensitive_values(payload)
    payload_json = json.dumps(redacted_payload, ensure_ascii=False, sort_keys=True)
    if len(payload_json.encode("utf-8")) > max_payload_bytes:
        raise ValueError(f"Audit payload for {topic} exceeds {max_payload_bytes} bytes.")
    return redacted_payload


def resolve_audit_db_path(path: str | Path | None = None) -> Path:
    """Return a SQLite path contained by the project's audit-data directory."""
    raw_path = Path(path) if path is not None else AUDIT_DB_DIR / "audit_log.sqlite3"
    if str(raw_path).lower().startswith("file:") or raw_path.suffix.lower() != ".sqlite3":
        raise ValueError("Audit database path must be a .sqlite3 file under database/.")

    database_dir = AUDIT_DB_DIR.resolve()
    resolved_path = raw_path.resolve()
    if not resolved_path.is_relative_to(database_dir):
        raise ValueError("Audit database path must be inside database/.")
    return resolved_path


class AuditStore:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        max_records: int = DEFAULT_MAX_RECORDS,
        max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    ) -> None:
        self.path = resolve_audit_db_path(path)
        self.retention_days = retention_days
        self.max_records = max_records
        self.max_payload_bytes = max_payload_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, uri=False, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mqtt_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                topic TEXT NOT NULL,
                event_ts_ms INTEGER,
                schema_version INTEGER,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_mqtt_audit_events_topic_received "
            "ON mqtt_audit_events(topic, received_at)"
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def record(self, topic: str, payload: dict[str, Any]) -> None:
        payload = validate_audit_payload(topic, payload, self.max_payload_bytes)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO mqtt_audit_events(topic, event_ts_ms, schema_version, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    topic,
                    payload.get("ts_ms"),
                    payload.get("schema_version"),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )
            self._cleanup_locked()
            self._connection.commit()

    def _cleanup_locked(self) -> None:
        if self.retention_days > 0:
            cutoff_ms = int((time.time() - self.retention_days * 24 * 60 * 60) * 1000)
            self._connection.execute(
                "DELETE FROM mqtt_audit_events WHERE event_ts_ms IS NOT NULL AND event_ts_ms < ?",
                (cutoff_ms,),
            )
        if self.max_records > 0:
            self._connection.execute(
                """
                DELETE FROM mqtt_audit_events
                WHERE id NOT IN (
                    SELECT id FROM mqtt_audit_events ORDER BY id DESC LIMIT ?
                )
                """,
                (self.max_records,),
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist AIoT MQTT audit events to SQLite.")
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--client-id", default="aiot-audit-logger")
    parser.add_argument("--mqtt-username", help="MQTT username. Password is read from --mqtt-password-env.")
    parser.add_argument("--mqtt-password-env", help="Environment variable containing the MQTT password.")
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--max-payload-bytes", type=int, default=MAX_PAYLOAD_BYTES)
    args = parser.parse_args()
    if args.retention_days < 0 or args.max_records < 0 or args.max_payload_bytes <= 0:
        parser.error("--retention-days and --max-records must be >= 0; --max-payload-bytes must be > 0.")
    if args.mqtt_username:
        try:
            password_from_env(args.mqtt_username, args.mqtt_password_env)
        except ValueError as error:
            parser.error(str(error))
    return args


def run_logger(args: argparse.Namespace) -> None:
    store = AuditStore(
        retention_days=args.retention_days,
        max_records=args.max_records,
        max_payload_bytes=args.max_payload_bytes,
    )

    def on_message(topic: str, payload: dict[str, Any]) -> None:
        if not is_audit_topic(topic):
            print(f"ignored topic={topic}")
            return
        try:
            store.record(topic, payload)
        except ValueError as error:
            print(f"rejected topic={topic}: {error}")
            return
        print(f"stored topic={topic} ts_ms={payload.get('ts_ms')}")

    client = MqttClient(
        host=args.mqtt_host,
        port=args.mqtt_port,
        client_id=args.client_id,
        username=args.mqtt_username,
        password=password_from_env(args.mqtt_username, args.mqtt_password_env),
        on_message=on_message,
    )
    for topic in AUDIT_TOPICS:
        client.subscribe(topic, qos=topic_policy(topic).qos)
    client.connect()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
        store.close()


def main() -> int:
    run_logger(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

