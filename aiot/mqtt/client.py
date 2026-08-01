"""Small optional wrapper around paho-mqtt."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any


MessageHandler = Callable[[str, dict[str, Any]], None]


class MqttUnavailable(RuntimeError):
    """Raised when paho-mqtt is not installed."""


def _load_mqtt_module():
    try:
        import paho.mqtt.client as mqtt
    except ImportError as error:
        raise MqttUnavailable(
            "MQTT support requires paho-mqtt. Install dependencies with "
            "python -m pip install -r requirements.txt."
        ) from error
    return mqtt


class MqttClient:
    def __init__(
        self,
        *,
        host: str,
        port: int = 1883,
        client_id: str,
        username: str | None = None,
        password: str | None = None,
        on_message: MessageHandler | None = None,
    ) -> None:
        mqtt = _load_mqtt_module()
        self._mqtt = mqtt
        self._on_message = on_message
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        if username:
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._handle_connect
        self._client.on_message = self._handle_message
        self._subscriptions: list[tuple[str, int]] = []
        self.host = host
        self.port = port

    def connect(self) -> None:
        self._client.connect(self.host, self.port, keepalive=30)
        self._client.loop_start()

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def subscribe(self, topic: str, qos: int = 0) -> None:
        self._subscriptions.append((topic, qos))
        self._client.subscribe(topic, qos=qos)

    def publish(self, topic: str, payload: dict[str, Any], qos: int = 0, retain: bool = False) -> None:
        self._client.publish(
            topic,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            qos=qos,
            retain=retain,
        )

    def _handle_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if int(reason_code) != 0:
            print(f"[MQTT] connect failed: {reason_code}", file=sys.stderr)
            return
        for topic, qos in self._subscriptions:
            client.subscribe(topic, qos=qos)

    def _handle_message(self, _client, _userdata, message) -> None:
        if self._on_message is None:
            return
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"raw": message.payload.decode("utf-8", errors="replace")}
        self._on_message(message.topic, payload)

