"""JSON payload builders for the MQTT control plane."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit


SCHEMA_VERSION = 1


def redact_rtsp_url(value: str) -> str:
    if not value.lower().startswith("rtsp://"):
        return value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.username and not parsed.password:
        return value
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    if not host:
        return value
    redacted = SplitResult(
        scheme=parsed.scheme,
        netloc=f"***:***@{host}",
        path=parsed.path,
        query=parsed.query,
        fragment=parsed.fragment,
    )
    return urlunsplit(redacted)


def redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, str):
        return redact_rtsp_url(value)
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive_values(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_sensitive_values(item) for key, item in value.items()}
    return value


def now_ms() -> int:
    return int(time.time() * 1000)


def system_status(
    *,
    device_id: str,
    state: str,
    component: str,
    message: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "device_id": device_id,
        "component": component,
        "state": state,
        "message": message,
        "metrics": redact_sensitive_values(metrics or {}),
    }


def recognition_result(
    *,
    source: str,
    frame_id: int,
    result_id: int,
    latency_ms: float,
    tracks: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "source": redact_rtsp_url(source),
        "frame_id": frame_id,
        "result_id": result_id,
        "latency_ms": round(float(latency_ms), 3),
        "tracks": redact_sensitive_values(tracks),
        "events": redact_sensitive_values(events),
    }


def error_event(
    *,
    component: str,
    message: str,
    source: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "component": component,
        "source": redact_rtsp_url(source) if source else None,
        "message": message,
        "details": redact_sensitive_values(details or {}),
    }


def motion_detected(
    *,
    device_id: str,
    sensor_id: str,
    active: bool,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "device_id": device_id,
        "sensor_id": sensor_id,
        "active": active,
    }


def stream_control(
    *,
    action: str,
    target_device_id: str,
    requested_by: str = "cloud",
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "requested_by": requested_by,
        "target_device_id": target_device_id,
        "action": action,
        "parameters": redact_sensitive_values(parameters or {}),
    }

