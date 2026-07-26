import unittest
from pathlib import Path

from stream_settings import RTSP_HOST, RTSP_PATH, RTSP_PORT, RTSP_URL


class StreamSettingsTests(unittest.TestCase):
    def test_url_is_derived_from_shared_settings(self):
        self.assertEqual(RTSP_URL, f"rtsp://{RTSP_HOST}:{RTSP_PORT}/{RTSP_PATH}")

    def test_mediamtx_is_local_and_uses_shared_port_and_path(self):
        config = (Path(__file__).parents[1] / "config" / "mediamtx.yml").read_text()

        self.assertIn(f"rtspAddress: {RTSP_HOST}:{RTSP_PORT}", config)
        self.assertIn(f"  {RTSP_PATH}:", config)
        self.assertIn("rtspTransports: [tcp]", config)


if __name__ == "__main__":
    unittest.main()
