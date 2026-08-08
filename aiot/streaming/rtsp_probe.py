"""Lightweight RTSP liveness probes for the edge agent."""

from __future__ import annotations

import socket

from aiot.streaming.stream_settings import RTSP_HOST, RTSP_PATH, RTSP_PORT


def _rtsp_request(host: str, port: int, path: str, timeout: float) -> str | None:
    request = (
        f"DESCRIBE rtsp://{host}:{port}/{path} RTSP/1.0\r\n"
        "CSeq: 1\r\n"
        "Accept: application/sdp\r\n"
        "User-Agent: aiot-edge-agent\r\n\r\n"
    )
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(request.encode("ascii"))
            response = sock.recv(4096)
    except OSError:
        return None
    return response.decode("latin-1", errors="replace")


def probe_rtsp_stream(
    host: str = RTSP_HOST,
    port: int = RTSP_PORT,
    path: str = RTSP_PATH,
    timeout: float = 0.5,
) -> bool:
    """Return whether a publisher is currently serving the RTSP path.

    MediaMTX answers DESCRIBE with 200 only while a publisher is connected
    to the path and 404 when the path has no source, so this distinguishes a
    live stream from a MediaMTX that is merely listening on the port.
    """
    response = _rtsp_request(host, port, path, timeout)
    if response is None:
        return False
    return response.split("\r\n", 1)[0].startswith("RTSP/1.0 200")
