"""Shared settings for the local-only RTSP pipeline."""

RTSP_HOST = "127.0.0.1"
RTSP_PORT = 8554
RTSP_PATH = "camera"
RTSP_URL = f"rtsp://{RTSP_HOST}:{RTSP_PORT}/{RTSP_PATH}"
