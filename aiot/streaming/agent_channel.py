"""Authenticated loopback channel between the edge agent and publisher child."""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading
from collections.abc import Callable
from typing import Any


MAX_MESSAGE_BYTES = 16 * 1024


class AgentChannelServer:
    """Own one authenticated publisher-child connection on localhost."""

    def __init__(self, on_event: Callable[[dict[str, Any]], None]) -> None:
        self.token = secrets.token_urlsafe(32)
        self._on_event = on_event
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.host, self.port = self._listener.getsockname()
        self._connection: socket.socket | None = None
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True, name="agent-channel")
        self._thread.start()

    def child_environment(self) -> dict[str, str]:
        return {
            "AIOT_AGENT_CHANNEL_HOST": self.host,
            "AIOT_AGENT_CHANNEL_PORT": str(self.port),
            "AIOT_AGENT_CHANNEL_TOKEN": self.token,
        }

    def send(self, message: dict[str, Any]) -> bool:
        encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock:
            connection = self._connection
            if connection is None:
                return False
            try:
                connection.sendall(encoded)
                return True
            except OSError:
                self._connection = None
                return False

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            for connection in (self._connection, self._listener):
                if connection is not None:
                    try:
                        connection.close()
                    except OSError:
                        pass
            self._connection = None

    def _accept_loop(self) -> None:
        while not self._closed.is_set():
            try:
                connection, _ = self._listener.accept()
            except OSError:
                return
            threading.Thread(target=self._read_connection, args=(connection,), daemon=True).start()

    def _read_connection(self, connection: socket.socket) -> None:
        try:
            reader = connection.makefile("r", encoding="utf-8", newline="\n")
            hello = reader.readline(MAX_MESSAGE_BYTES + 1)
            if len(hello) > MAX_MESSAGE_BYTES:
                return
            try:
                payload = json.loads(hello)
            except json.JSONDecodeError:
                return
            if not isinstance(payload, dict) or payload.get("type") != "hello" or not secrets.compare_digest(str(payload.get("token", "")), self.token):
                return
            with self._lock:
                previous = self._connection
                self._connection = connection
            if previous is not None and previous is not connection:
                previous.close()
            for line in reader:
                if len(line) > MAX_MESSAGE_BYTES:
                    return
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    self._on_event(event)
        finally:
            with self._lock:
                if self._connection is connection:
                    self._connection = None
            try:
                connection.close()
            except OSError:
                pass


class PublisherChannel:
    """Child-side event emitter and inbound face-presence receiver."""

    def __init__(self, on_message: Callable[[dict[str, Any]], None]) -> None:
        self._on_message = on_message
        self._socket: socket.socket | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls, on_message: Callable[[dict[str, Any]], None]) -> PublisherChannel | None:
        host = os.environ.get("AIOT_AGENT_CHANNEL_HOST")
        port = os.environ.get("AIOT_AGENT_CHANNEL_PORT")
        token = os.environ.get("AIOT_AGENT_CHANNEL_TOKEN")
        if not host or not port or not token:
            return None
        channel = cls(on_message)
        connection = socket.create_connection((host, int(port)), timeout=5)
        channel._socket = connection
        channel.emit({"type": "hello", "token": token})
        threading.Thread(target=channel._read_loop, daemon=True, name="publisher-channel").start()
        return channel

    def emit(self, message: dict[str, Any]) -> None:
        encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock:
            if self._socket is None:
                return
            try:
                self._socket.sendall(encoded)
            except OSError:
                self._socket = None

    def close(self) -> None:
        with self._lock:
            if self._socket is not None:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None

    def _read_loop(self) -> None:
        connection = self._socket
        if connection is None:
            return
        try:
            for line in connection.makefile("r", encoding="utf-8", newline="\n"):
                if len(line) > MAX_MESSAGE_BYTES:
                    return
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    self._on_message(message)
        finally:
            self.close()
