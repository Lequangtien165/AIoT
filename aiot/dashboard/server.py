"""FastAPI web dashboard: live WebRTC video, event timeline, and edge control.

The dashboard consumes the existing MQTT control plane and the SQLite audit
log. Video is played directly from MediaMTX WebRTC (WHEP); recognition boxes
are drawn in the browser as an overlay fed by `recognition/result` events.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aiot.mqtt import payloads
from aiot.mqtt.audit_logger import query_audit_events
from aiot.mqtt.client import (
    MqttClient,
    MqttConnectionError,
    MqttPublishError,
    MqttSubscriptionError,
    MqttUnavailable,
)
from aiot.mqtt.topics import (
    TOPIC_CONTROL_ACK,
    TOPIC_CONTROL_STREAM,
    TOPIC_MOTION_DETECTED,
    TOPIC_RECOGNITION_RESULT,
    TOPIC_SYSTEM_STATUS,
    control_stream_topic,
    topic_policy,
)
from aiot.recognition.wanted import WantedList

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_AUDIT_DB = PROJECT_ROOT / "database" / "audit_log.sqlite3"

CONTROL_ACTIONS = {"status", "start", "stop", "restart"}

SUBSCRIBE_TOPICS = (
    TOPIC_RECOGNITION_RESULT,
    TOPIC_MOTION_DETECTED,
    "error/#",
    f"{TOPIC_SYSTEM_STATUS}/+",
    f"{TOPIC_CONTROL_ACK}/+",
)


@dataclass
class DashboardConfig:
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_client_id: str = "aiot-dashboard"
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_ca_cert: str | None = None
    audit_db: str | Path = DEFAULT_AUDIT_DB
    wanted_config: str | Path | None = None
    snapshot_dir: str | Path | None = None
    video_url: str = "http://127.0.0.1:8889"
    video_path: str = "camera"
    video_device_id: str | None = None


class ClientHub:
    """Bridges MQTT callbacks (paho thread) to connected WebSocket clients.

    Each connected client owns an asyncio queue; MQTT messages are routed into
    every queue from the paho thread via call_soon_threadsafe.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queues: set[asyncio.Queue] = set()
        self.statuses: dict[str, dict[str, Any]] = {}
        self.mqtt_connected = False
        self._mqtt: MqttClient | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def register(self, queue: asyncio.Queue) -> None:
        self._queues.add(queue)

    def unregister(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)

    def broadcast(self, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._broadcast_locked, message)

    def _broadcast_locked(self, message: dict[str, Any]) -> None:
        for queue in self._queues:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass

    def on_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic.startswith(f"{TOPIC_SYSTEM_STATUS}/"):
            device_id = topic.rsplit("/", 1)[-1]
            self.statuses[device_id] = payload
            self.broadcast({"type": "status", "topic": topic, "payload": payload})
        elif topic.startswith(f"{TOPIC_CONTROL_ACK}/"):
            self.broadcast({"type": "ack", "topic": topic, "payload": payload})
        else:
            self.broadcast({"type": "event", "topic": topic, "payload": payload})

    def connect(self, config: DashboardConfig) -> None:
        self._mqtt = MqttClient(
            host=config.mqtt_host,
            port=config.mqtt_port,
            client_id=config.mqtt_client_id,
            username=config.mqtt_username,
            password=config.mqtt_password,
            ca_cert=config.mqtt_ca_cert,
            on_message=self.on_message,
        )
        for topic in SUBSCRIBE_TOPICS:
            self._mqtt.subscribe(topic, qos=topic_policy(topic).qos)
        self._mqtt.connect()
        self.mqtt_connected = True

    def publish_command(self, device_id: str, action: str, requested_by: str) -> str:
        if self._mqtt is None or not self.mqtt_connected:
            raise MqttUnavailable("MQTT broker is not connected.")
        message = payloads.stream_control(
            action=action,
            target_device_id=device_id,
            requested_by=requested_by,
        )
        policy = topic_policy(control_stream_topic(device_id))
        self._mqtt.publish(
            control_stream_topic(device_id),
            message,
            qos=policy.qos,
            retain=policy.retain,
        )
        return message["command_id"]

    def close(self) -> None:
        if self._mqtt is not None:
            self._mqtt.close()
            self._mqtt = None
        self.mqtt_connected = False


def _validate_control_body(body: dict[str, Any]) -> tuple[str, str, str]:
    """Validate an /api/control request body, returning (device_id, action, requested_by)."""
    device_id = body.get("device_id")
    action = body.get("action")
    requested_by = body.get("requested_by", "dashboard")
    if not isinstance(device_id, str) or not device_id.strip():
        raise HTTPException(status_code=422, detail="device_id is required.")
    if action not in CONTROL_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"action must be one of {sorted(CONTROL_ACTIONS)}.",
        )
    if not isinstance(requested_by, str) or not requested_by.strip():
        requested_by = "dashboard"
    return device_id.strip(), str(action), requested_by


async def _websocket_loop(
    websocket: WebSocket,
    hub: ClientHub,
    config: DashboardConfig,
) -> None:
    """Serve the /ws endpoint: hello, snapshots, then live MQTT events."""
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    hub.register(queue)
    try:
        await websocket.send_json(
            {
                "type": "hello",
                "video": {"url": config.video_url, "path": config.video_path, "device_id": config.video_device_id},
            }
        )
        await websocket.send_json({"type": "status_snapshot", "devices": hub.statuses})
        recent = query_audit_events(config.audit_db, limit=50)
        await websocket.send_json({"type": "events_snapshot", "events": recent})
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(queue)


def create_app(config: DashboardConfig | None = None) -> FastAPI:
    config = config or DashboardConfig()
    hub = ClientHub()
    wanted_list = WantedList(config.wanted_config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        hub.bind_loop(asyncio.get_running_loop())
        try:
            hub.connect(config)
            print(f"[MQTT] dashboard connected to {config.mqtt_host}:{config.mqtt_port}", file=sys.stderr)
        except MqttUnavailable as error:
            print(f"[MQTT] {error}", file=sys.stderr)
        except (MqttConnectionError, MqttSubscriptionError) as error:
            print(f"[MQTT] dashboard running without MQTT: {error}", file=sys.stderr)
        yield
        hub.close()

    app = FastAPI(title="AIoT Dashboard", lifespan=lifespan)
    app.state.hub = hub

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "mqtt_connected": hub.mqtt_connected}

    @app.get("/api/events")
    def events(
        topic: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        since_ts_ms: int | None = Query(default=None, ge=0),
    ) -> dict[str, Any]:
        rows = query_audit_events(
            config.audit_db,
            topics=[topic] if topic else None,
            limit=limit,
            offset=offset,
            since_ts_ms=since_ts_ms,
        )
        return {"events": rows, "count": len(rows)}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {"devices": hub.statuses}

    @app.get("/api/wanted")
    def wanted() -> dict[str, Any]:
        return {
            "entries": [
                {"match": entry.match, "name": entry.name, "severity": entry.severity}
                for entry in wanted_list.entries()
            ]
        }

    @app.get("/api/wanted/match")
    def wanted_match(label: str = Query(default="", max_length=256)) -> dict[str, Any]:
        entry = wanted_list.match(label or None)
        return {
            "wanted": entry is not None,
            "entry": (
                {"name": entry.name, "severity": entry.severity}
                if entry is not None
                else None
            ),
        }

    @app.post(
        "/api/control",
        responses={
            422: {"description": "Invalid request body."},
            502: {"description": "MQTT publish failed."},
            503: {"description": "MQTT broker is not connected."},
        },
    )
    def control(body: dict[str, Any]) -> dict[str, Any]:
        device_id, action, requested_by = _validate_control_body(body)
        try:
            command_id = hub.publish_command(device_id, action, requested_by)
        except MqttUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except MqttPublishError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return {"command_id": command_id, "accepted": True}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await _websocket_loop(websocket, hub, config)

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    if config.snapshot_dir is not None and Path(config.snapshot_dir).is_dir():
        app.mount(
            "/snapshots",
            StaticFiles(directory=str(Path(config.snapshot_dir))),
            name="snapshots",
        )

    return app
