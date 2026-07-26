import unittest

from stream_platform import get_platform_config, mediamtx_download_spec


class PlatformConfigTests(unittest.TestCase):
    def test_windows_configuration(self):
        config = get_platform_config("Windows", "AMD64")

        self.assertEqual(config.capture_format, "dshow")
        self.assertEqual(config.video_encoder, "libx264")
        self.assertEqual(config.camera_input("Camera"), "video=Camera")

    def test_macos_arm_configuration(self):
        config = get_platform_config("Darwin", "arm64")

        self.assertEqual(config.capture_format, "avfoundation")
        self.assertEqual(config.video_encoder, "h264_videotoolbox")
        self.assertEqual(config.camera_input("0"), "0:none")
        self.assertEqual(mediamtx_download_spec(config)[0], "darwin_arm64.tar.gz")

    def test_unsupported_platform_is_rejected(self):
        with self.assertRaises(RuntimeError):
            get_platform_config("Linux", "aarch64")


if __name__ == "__main__":
    unittest.main()
