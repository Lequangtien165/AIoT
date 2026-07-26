import unittest

from app import display_source


class DisplaySourceTests(unittest.TestCase):
    def test_redacts_rtsp_password(self):
        source = "rtsp://admin:secret@example.test:8554/camera"

        self.assertEqual(
            display_source(source), "rtsp://admin:***@example.test:8554/camera"
        )

    def test_invalid_port_does_not_leak_credentials(self):
        source = "rtsp://admin:secret@example.test:not-a-port/camera"

        self.assertEqual(display_source(source), "RTSP source")


if __name__ == "__main__":
    unittest.main()
