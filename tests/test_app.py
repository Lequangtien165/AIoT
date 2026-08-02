import unittest
from unittest.mock import Mock, patch

from app import display_source, open_or_reconnect, read_or_reconnect, run_preview


class DisplaySourceTests(unittest.TestCase):
    def test_redacts_rtsp_password(self):
        source = "rtsp://admin:secret@example.test:8554/camera"

        self.assertEqual(
            display_source(source), "rtsp://admin:***@example.test:8554/camera"
        )

    def test_invalid_port_does_not_leak_credentials(self):
        source = "rtsp://admin:secret@example.test:not-a-port/camera"

        self.assertEqual(display_source(source), "RTSP source")


class PreviewLifecycleTests(unittest.TestCase):
    @patch("app.wait_for_reconnect", return_value=(True, True))
    @patch("app.open_camera", return_value=None)
    def test_open_failure_waits_for_reconnect(self, open_camera, wait_for_reconnect):
        camera, reconnecting, should_stop = open_or_reconnect("rtsp://camera", False, 2.0)

        self.assertIsNone(camera)
        self.assertTrue(reconnecting)
        self.assertTrue(should_stop)
        open_camera.assert_called_once_with("rtsp://camera")
        wait_for_reconnect.assert_called_once_with(
            "rtsp://camera", False, "Could not open RTSP stream", 2.0
        )

    @patch("app.wait_for_reconnect", return_value=(True, True))
    def test_read_failure_releases_camera_before_reconnect(self, wait_for_reconnect):
        camera = Mock()
        camera.read.return_value = False, None

        next_camera, frame, reconnecting, should_stop = read_or_reconnect(
            camera, "rtsp://camera", False, 2.0
        )

        self.assertIsNone(next_camera)
        self.assertIsNone(frame)
        self.assertTrue(reconnecting)
        self.assertTrue(should_stop)
        camera.release.assert_called_once_with()
        wait_for_reconnect.assert_called_once_with(
            "rtsp://camera", False, "Lost RTSP stream", 2.0
        )

    @patch("app.render_frame", return_value=True)
    @patch("app.read_or_reconnect")
    @patch("app.open_or_reconnect")
    def test_render_exit_releases_camera(self, open_or_reconnect, read_or_reconnect, render_frame):
        camera = Mock()
        frame = object()
        open_or_reconnect.return_value = camera, False, False
        read_or_reconnect.return_value = camera, frame, False, False

        run_preview("rtsp://camera", 2.0, Mock())

        render_frame.assert_called_once()
        camera.release.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
