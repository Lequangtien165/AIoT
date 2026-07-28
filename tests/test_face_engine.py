import unittest

from aiot.recognition.face_engine import ProviderStatus


class ProviderStatusTests(unittest.TestCase):
    def test_warning_present_when_gpu_requested_but_not_active(self):
        status = ProviderStatus(
            requested=["CUDAExecutionProvider", "CPUExecutionProvider"],
            effective=["CPUExecutionProvider"],
            warning="missing cublasLt64_13.dll",
            gpu_requested=True,
            gpu_active=False,
        )

        self.assertTrue(status.gpu_requested)
        self.assertFalse(status.gpu_active)
        self.assertIn("cublasLt64_13.dll", status.warning)


if __name__ == "__main__":
    unittest.main()
