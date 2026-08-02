"""Small optional wrapper around paho-mqtt."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable
from typing import Any


MessageHandler = Callable[[str, dict[str, Any]], None]
ConnectionStateHandler = Callable[[str], None]


class MqttUnavailable(RuntimeError):
    """Raised when paho-mqtt is not installed."""


class MqttConnectionError(RuntimeError):
    """Raised when the broker rejects or does not complete a connection."""


class MqttPublishError(RuntimeError):
    """Raised when paho-mqtt cannot queue or complete a publish."""


class MqttSubscriptionError(RuntimeError):
    """Raised when the broker rejects a required subscription."""


def _load_mqtt_module():
    try:
        import paho.mqtt.client as mqtt
    except ImportError as error:
        raise MqttUnavailable(
            "MQTT support requires paho-mqtt. Install dependencies with "
            "python -m pip install -r requirements.txt."
        ) from error
    return mqtt


def password_from_env(username: str | None, password_env: str | None) -> str | None:
    if not username:
        return None
    if not password_env:
        raise ValueError("--mqtt-password-env is required when --mqtt-username is set.")
    password = os.environ.get(password_env)
    if password is None:
        raise ValueError(f"Environment variable {password_env} is not set.")
    return password


def reason_code_failed(reason_code: object) -> bool:
    try:
        return int(reason_code) != 0
    except (TypeError, ValueError):
        pass

    value = getattr(reason_code, "value", None)
    if value is not None:
        try:
            return int(value) != 0
        except (TypeError, ValueError):
            pass

    is_failure = getattr(reason_code, "is_failure", None)
    if callable(is_failure):
        return bool(is_failure())
    if is_failure is not None:
        return bool(is_failure)

    return str(reason_code).lower() not in {"0", "success"}


def subscription_reason_failed(reason_code: object) -> bool:
    """Return whether a SUBACK reason code is a failure.

    MQTT grants QoS 0, 1, or 2, so nonzero successful SUBACK values must not
    be treated like failed CONNACK reason codes.
    """
    is_failure = getattr(reason_code, "is_failure", None)
    if callable(is_failure):
        return bool(is_failure())
    if is_failure is not None:
        return bool(is_failure)
    value = getattr(reason_code, "value", reason_code)
    try:
        return int(value) >= 128
    except (TypeError, ValueError):
        return "failure" in str(reason_code).lower() or "not authorized" in str(reason_code).lower()


class MqttClient:
    def __init__(
        self,
        *,
        host: str,
        port: int = 1883,
        client_id: str,
        username: str | None = None,
        password: str | None = None,
        ca_cert: str | None = None,
        on_message: MessageHandler | None = None,
        on_connection_state: ConnectionStateHandler | None = None,
    ) -> None:
        mqtt = _load_mqtt_module()
        self._mqtt = mqtt
        self._on_message = on_message
        self._on_connection_state = on_connection_state
        self._connect_event = threading.Event()
        self._subscription_event = threading.Event()
        self._connection_error: str | None = None
        self._connected_once = False
        self._connected = False
        self._pending_subscription_mids: set[int] = set()
        self._retained_payloads: dict[str, tuple[dict[str, Any], int, bool]] = {}
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        if username:
            self._client.username_pw_set(username, password)
        if ca_cert:
            self._client.tls_set(ca_certs=ca_cert)
        self._client.on_connect = self._handle_connect
        self._client.on_disconnect = self._handle_disconnect
        self._client.on_subscribe = self._handle_subscribe
        self._client.on_message = self._handle_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._subscriptions: list[tuple[str, int]] = []
        self.host = host
        self.port = port

    def connect(self, timeout: float = 10.0) -> None:
        self._connect_event.clear()
        self._subscription_event.clear()
        self._connection_error = None
        try:
            self._client.connect(self.host, self.port, keepalive=30)
        except OSError as error:
            raise MqttConnectionError(f"MQTT broker is not reachable at {self.host}:{self.port}: {error}") from error
        self._client.loop_start()
        deadline = time.monotonic() + timeout
        if not self._connect_event.wait(timeout):
            self.close()
            raise MqttConnectionError(f"MQTT broker did not send CONNACK within {timeout:.1f}s.")
        if self._connection_error is not None:
            self.close()
            if self._connected:
                raise MqttSubscriptionError(self._connection_error)
            raise MqttConnectionError(self._connection_error)
        remaining = deadline - time.monotonic()
        if not self._subscription_event.wait(max(0.0, remaining)):
            self.close()
            raise MqttSubscriptionError(f"MQTT broker did not send SUBACK within {timeout:.1f}s.")
        if self._connection_error is not None:
            self.close()
            raise MqttSubscriptionError(self._connection_error)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def subscribe(self, topic: str, qos: int = 0) -> None:
        self._subscriptions.append((topic, qos))
        if self._connected:
            self._subscribe(topic, qos)

    def publish(self, topic: str, payload: dict[str, Any], qos: int = 0, retain: bool = False) -> None:
        if retain:
            self._retained_payloads[topic] = (payload, qos, retain)
        self._publish(topic, payload, qos=qos, retain=retain, wait_for_delivery=True)

    def _publish(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        qos: int,
        retain: bool,
        wait_for_delivery: bool,
    ) -> None:
        info = self._client.publish(
            topic,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            qos=qos,
            retain=retain,
        )
        if getattr(info, "rc", 0) != self._mqtt.MQTT_ERR_SUCCESS:
            raise MqttPublishError(f"MQTT publish failed for {topic}: rc={info.rc}")
        if qos > 0 and wait_for_delivery and hasattr(info, "wait_for_publish"):
            info.wait_for_publish(timeout=5.0)
            if hasattr(info, "is_published") and not info.is_published():
                raise MqttPublishError(f"MQTT publish timed out for {topic}.")

    def _handle_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code_failed(reason_code):
            self._connection_error = f"MQTT connect failed: {reason_code}"
            self._connect_event.set()
            print(f"[MQTT] {self._connection_error}", file=sys.stderr)
            return
        was_reconnect = self._connected_once
        self._connected_once = True
        self._connected = True
        self._connect_event.set()
        self._notify_connection_state("connected")
        print("[MQTT] connected", file=sys.stderr)
        self._subscribe_all(client)
        if was_reconnect:
            for topic, (payload, qos, retain) in self._retained_payloads.items():
                try:
                    self._publish(topic, payload, qos=qos, retain=retain, wait_for_delivery=False)
                except MqttPublishError as error:
                    print(f"[MQTT] retained state republish failed: {error}", file=sys.stderr)
                    self._notify_connection_state("degraded")

    def _handle_disconnect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        self._connected = False
        if reason_code_failed(reason_code):
            print(f"[MQTT] disconnected unexpectedly: {reason_code}", file=sys.stderr)
            self._notify_connection_state("degraded")
        else:
            print("[MQTT] disconnected", file=sys.stderr)
            self._notify_connection_state("closed")

    def _subscribe_all(self, client) -> None:
        self._pending_subscription_mids.clear()
        if not self._subscriptions:
            self._subscription_event.set()
            return
        for topic, qos in self._subscriptions:
            self._subscribe(topic, qos, client)

    def _subscribe(self, topic: str, qos: int, client=None) -> None:
        client = client or self._client
        result = client.subscribe(topic, qos=qos)
        if not isinstance(result, tuple) or len(result) != 2:
            self._connection_error = f"MQTT subscription failed for {topic}: invalid Paho result."
            self._subscription_event.set()
            return
        rc, mid = result
        if rc != self._mqtt.MQTT_ERR_SUCCESS:
            self._connection_error = f"MQTT subscription failed for {topic}: rc={rc}"
            self._subscription_event.set()
            return
        self._pending_subscription_mids.add(mid)

    def _handle_subscribe(self, _client, _userdata, mid, reason_codes, _properties) -> None:
        if any(subscription_reason_failed(reason_code) for reason_code in reason_codes):
            self._connection_error = f"MQTT subscription rejected for message id {mid}."
            self._notify_connection_state("degraded")
        self._pending_subscription_mids.discard(mid)
        if not self._pending_subscription_mids:
            self._subscription_event.set()

    def _notify_connection_state(self, state: str) -> None:
        if self._on_connection_state is None:
            return
        try:
            self._on_connection_state(state)
        except Exception as error:
            print(f"[MQTT] connection state callback failed: {error}", file=sys.stderr)

    def _handle_message(self, _client, _userdata, message) -> None:
        if self._on_message is None:
            return
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"raw": message.payload.decode("utf-8", errors="replace")}
        if not isinstance(payload, dict):
            payload = {"raw": payload}
        self._on_message(message.topic, payload)

