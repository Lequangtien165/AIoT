"""SQLite audit logger for selected MQTT events."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import threading
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
    "control/ack": {"schema_version", "ts_ms", "command_id", "target_device_id", "action", "result"},
}


def topic_matches(subscription: str, topic: str) -> bool:
    """Return whether a concrete topic matches a subscription pattern."""
    if subscription.endswith("/#"):
        return topic.startswith(subscription[:-1])
    if "+" in subscription:
        subscription_parts = subscription.split("/")
        topic_parts = topic.split("/")
        if len(subscription_parts) != len(topic_parts):
            return False
        return all(pattern == "+" or part == pattern for part, pattern in zip(topic_parts, subscription_parts))
    return topic == subscription


def is_audit_topic(topic: str) -> bool:
    return any(topic_matches(subscription, topic) for subscription in AUDIT_TOPICS)


def required_fields_for_topic(topic: str) -> set[str]:
    if topic.startswith("error/"):
        return {"schema_version", "ts_ms", "component", "message"}
    if topic.startswith("control/ack/"):
        return REQUIRED_FIELDS_BY_TOPIC["control/ack"]
    return REQUIRED_FIELDS_BY_TOPIC.get(topic, set())


def validate_audit_payload(topic: str, payload: dict[str, Any], max_payload_bytes: int = MAX_PAYLOAD_BYTES) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version for {topic}.")
    missing = sorted(required_fields_for_topic(topic) - payload.keys())
    if missing:
        raise ValueError(f"Missing required audit fields for {topic}: {', '.join(missing)}.")
    _validate_common_payload(payload)
    _validate_topic_payload(topic, payload)
    redacted_payload = redact_sensitive_values(payload)
    payload_json = json.dumps(redacted_payload, ensure_ascii=False, sort_keys=True)
    if len(payload_json.encode("utf-8")) > max_payload_bytes:
        raise ValueError(f"Audit payload for {topic} exceeds {max_payload_bytes} bytes.")
    return redacted_payload


def _is_non_negative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _require_non_empty_string(payload: dict[str, Any], field: str) -> None:
    if not isinstance(payload.get(field), str) or not payload[field].strip():
        raise ValueError(f"Audit field {field} must be a non-empty string.")


def _validate_common_payload(payload: dict[str, Any]) -> None:
    if not _is_non_negative_integer(payload.get("ts_ms")):
        raise ValueError("Audit field ts_ms must be a non-negative integer.")


def _validate_recognition_payload(payload: dict[str, Any]) -> None:
    _require_non_empty_string(payload, "source")
    for field in ("frame_id", "result_id"):
        if not _is_non_negative_integer(payload.get(field)):
            raise ValueError(f"Audit field {field} must be a non-negative integer.")
    latency_ms = payload.get("latency_ms")
    if (
        not isinstance(latency_ms, (int, float))
        or isinstance(latency_ms, bool)
        or not math.isfinite(latency_ms)
        or latency_ms < 0
    ):
        raise ValueError("Audit field latency_ms must be a non-negative finite number.")
    for field in ("tracks", "events"):
        if not isinstance(payload.get(field), list) or not all(isinstance(item, dict) for item in payload[field]):
            raise ValueError(f"Audit field {field} must be a list of objects.")


def _validate_motion_payload(payload: dict[str, Any]) -> None:
    _require_non_empty_string(payload, "device_id")
    _require_non_empty_string(payload, "sensor_id")
    if not isinstance(payload.get("active"), bool):
        raise ValueError("Audit field active must be a boolean.")


def _validate_control_ack_payload(payload: dict[str, Any]) -> None:
    for field in ("command_id", "target_device_id", "action", "result"):
        _require_non_empty_string(payload, field)
    if not isinstance(payload.get("message"), str):
        raise ValueError("Audit field message must be a string.")
    if payload.get("state") is not None and not isinstance(payload["state"], str):
        raise ValueError("Audit field state must be a string or null.")


def _validate_error_payload(payload: dict[str, Any]) -> None:
    _require_non_empty_string(payload, "component")
    _require_non_empty_string(payload, "message")
    if payload.get("source") is not None and not isinstance(payload["source"], str):
        raise ValueError("Audit field source must be a string or null.")
    if payload.get("details", {}) is not None and not isinstance(payload.get("details", {}), dict):
        raise ValueError("Audit field details must be an object.")


def _validate_topic_payload(topic: str, payload: dict[str, Any]) -> None:
    if topic == "recognition/result":
        _validate_recognition_payload(payload)
    elif topic == "motion/detected":
        _validate_motion_payload(payload)
    elif topic.startswith("control/ack/"):
        _validate_control_ack_payload(payload)
    elif topic.startswith("error/"):
        _validate_error_payload(payload)


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
            self._connection.execute(
                "DELETE FROM mqtt_audit_events WHERE received_at < datetime('now', ?)",
                (f"-{self.retention_days} days",),
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


def query_audit_events(
    path: str | Path | None = None,
    *,
    topics: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
    since_ts_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Return recent audit events, newest first, decoded from SQLite.

    The database file is opened read-only per call so the dashboard can query
    the same file the logger writes to. A missing file returns an empty list.
    """
    resolved_path = resolve_audit_db_path(path)
    if not resolved_path.exists():
        return []
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    clauses: list[str] = []
    parameters: list[Any] = []
    if topics:
        clause = " OR ".join("topic LIKE ?" for _ in topics)
        clauses.append(f"({clause})")
        parameters.extend(_topic_like_pattern(topic) for topic in topics)
    if since_ts_ms is not None and since_ts_ms >= 0:
        clauses.append("event_ts_ms >= ?")
        parameters.append(int(since_ts_ms))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.extend((limit, offset))
    connection = sqlite3.connect(resolved_path)
    try:
        rows = connection.execute(
            f"""
            SELECT id, received_at, topic, event_ts_ms, schema_version, payload_json
            FROM mqtt_audit_events
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            parameters,
        ).fetchall()
    finally:
        connection.close()
    events: list[dict[str, Any]] = []
    for row_id, received_at, topic, event_ts_ms, schema_version, payload_json in rows:
        try:
            payload = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        events.append(
            {
                "id": row_id,
                "received_at": received_at,
                "topic": topic,
                "event_ts_ms": event_ts_ms,
                "schema_version": schema_version,
                "payload": payload,
            }
        )
    return events


def _topic_like_pattern(subscription: str) -> str:
    if subscription.endswith("/#"):
        return f"{subscription[:-1]}%"
    if "+" in subscription:
        return subscription.replace("+", "%")
    return subscription


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persist AIoT MQTT audit events to SQLite.")
    parser.add_argument("--mqtt-host", default="127.0.0.1", help="MQTT broker host (default: 127.0.0.1).")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port (default: 1883).")
    parser.add_argument("--client-id", default="aiot-audit-logger", help="MQTT client ID (default: aiot-audit-logger).")
    parser.add_argument("--mqtt-username", help="MQTT username. Password is read from --mqtt-password-env.")
    parser.add_argument("--mqtt-password-env", help="Environment variable containing the MQTT password.")
    parser.add_argument("--mqtt-ca-cert", help="CA certificate path for TLS MQTT connections.")
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS, help="Retention period in days (default: 30).")
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS, help="Maximum stored audit records (default: 100000).")
    parser.add_argument("--max-payload-bytes", type=int, default=MAX_PAYLOAD_BYTES, help="Maximum accepted payload size in bytes (default: 16384).")
    return parser


def parse_args() -> argparse.Namespace:
    parser = build_parser()
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
        ca_cert=args.mqtt_ca_cert,
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

