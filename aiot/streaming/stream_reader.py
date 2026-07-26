"""OpenCV RTSP helpers with password-safe diagnostics."""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import cv2


def display_source(source: str) -> str:
    """Return a URL that is safe to display in logs."""
    try:
        parsed = urlsplit(source)
        if not parsed.hostname:
            return "RTSP source"
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        if parsed.username is not None:
            host = f"{parsed.username}:***@{host}"
        return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))
    except ValueError:
        return "RTSP source"


def open_capture(source: str) -> cv2.VideoCapture:
    """Open RTSP over TCP to match the local MediaMTX configuration."""
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;5000000"
    return cv2.VideoCapture(source, cv2.CAP_FFMPEG)
