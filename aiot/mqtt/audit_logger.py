"""SQLite audit logger for selected MQTT events."""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from aiot.mqtt.client import MqttClient, password_from_env
from aiot.mqtt.topics import AUDIT_TOPICS, TOPIC_POLICIES


DEFAULT_DB_PATH = Path("database/audit_log.sqlite3")


def is_audit_topic(topic: str) -> bool:
    for subscription in AUDIT_TOPICS:
        if subscription.endswith("/#") and topic.startswith(subscription[:-1]):
            return True
        if topic == subscription:
            return True
    return False


class AuditStore:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
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
            self._connection.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist AIoT MQTT audit events to SQLite.")
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--client-id", default="aiot-audit-logger")
    parser.add_argument("--mqtt-username", help="MQTT username. Password is read from --mqtt-password-env.")
    parser.add_argument("--mqtt-password-env", help="Environment variable containing the MQTT password.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    if args.mqtt_username:
        try:
            password_from_env(args.mqtt_username, args.mqtt_password_env)
        except ValueError as error:
            parser.error(str(error))
    return args


def run_logger(args: argparse.Namespace) -> None:
    store = AuditStore(args.db_path)

    def on_message(topic: str, payload: dict[str, Any]) -> None:
        if not is_audit_topic(topic):
            print(f"ignored topic={topic}")
            return
        store.record(topic, payload)
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
        policy = TOPIC_POLICIES.get(topic)
        client.subscribe(topic, qos=policy.qos if policy else 1)
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

