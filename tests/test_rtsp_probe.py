import unittest
from unittest.mock import patch

from aiot.streaming.rtsp_probe import probe_rtsp_stream


class FakeSocket:
    def __init__(self, response=b"", error=None):
        self.response = response
        self.error = error
        self.sent = b""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def sendall(self, data):
        self.sent = data

    def recv(self, size):
        if self.error is not None:
            raise self.error
        return self.response


class RtspProbeTests(unittest.TestCase):
    def probe(self, response=b"", error=None, connect_error=None):
        if connect_error is not None:
            mock = patch(
                "aiot.streaming.rtsp_probe.socket.create_connection",
                side_effect=connect_error,
            )
            with mock:
                return probe_rtsp_stream("127.0.0.1", 8554, "camera")
        fake = FakeSocket(response=response, error=error)
        with patch("aiot.streaming.rtsp_probe.socket.create_connection", return_value=fake):
            result = probe_rtsp_stream("127.0.0.1", 8554, "camera")
        return result

    def test_returns_true_when_publisher_is_serving(self):
        fake = FakeSocket(response=b"RTSP/1.0 200 OK\r\nContent-Type: application/sdp\r\n\r\nv=0\r\n")
        with patch("aiot.streaming.rtsp_probe.socket.create_connection", return_value=fake):
            result = probe_rtsp_stream("127.0.0.1", 8554, "camera")
        self.assertTrue(result)
        self.assertTrue(
            fake.sent.startswith(b"DESCRIBE rtsp://127.0.0.1:8554/camera RTSP/1.0")
        )

    def test_returns_false_for_missing_publisher(self):
        self.assertFalse(self.probe(response=b"RTSP/1.0 404 Not Found\r\n\r\n"))

    def test_returns_false_when_connection_fails(self):
        self.assertFalse(self.probe(connect_error=OSError("connection refused")))

    def test_returns_false_when_read_fails(self):
        self.assertFalse(self.probe(error=OSError("read timed out")))

    def test_returns_false_for_empty_response(self):
        self.assertFalse(self.probe(response=b""))

    def test_returns_false_for_redirect_status(self):
        self.assertFalse(self.probe(response=b"RTSP/1.0 301 Moved Permanently\r\n\r\n"))


if __name__ == "__main__":
    unittest.main()
