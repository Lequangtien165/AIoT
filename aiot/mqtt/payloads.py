"""JSON payload builders for the MQTT control plane."""

from __future__ import annotations

import time
from typing import Any


SCHEMA_VERSION = 1


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
        "metrics": metrics or {},
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
        "source": source,
        "frame_id": frame_id,
        "result_id": result_id,
        "latency_ms": round(float(latency_ms), 3),
        "tracks": tracks,
        "events": events,
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
        "source": source,
        "message": message,
        "details": details or {},
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
    requested_by: str = "cloud",
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "requested_by": requested_by,
        "action": action,
        "parameters": parameters or {},
    }

