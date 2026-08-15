import unittest

from aiot.recognition.runtime import get_recognition_runtime


class RecognitionRuntimeTests(unittest.TestCase):
    def test_windows_amd64_prefers_cuda(self):
        runtime = get_recognition_runtime("Windows", "AMD64")

        self.assertEqual(runtime.name, "windows-amd64")
        self.assertEqual(runtime.accelerator_provider, "CUDAExecutionProvider")
        self.assertEqual(runtime.provider_names, ("CUDAExecutionProvider", "CPUExecutionProvider"))

    def test_windows_x86_64_prefers_cuda(self):
        runtime = get_recognition_runtime("Windows", "x86_64")

        self.assertEqual(runtime.accelerator_provider, "CUDAExecutionProvider")
        self.assertEqual(runtime.providers[0], "CUDAExecutionProvider")

    def test_macos_arm64_prefers_coreml_with_options(self):
        runtime = get_recognition_runtime("Darwin", "arm64")

        self.assertEqual(runtime.name, "macos-arm64")
        self.assertEqual(runtime.accelerator_provider, "CoreMLExecutionProvider")
        self.assertEqual(runtime.provider_names, ("CoreMLExecutionProvider", "CPUExecutionProvider"))
        coreml_entry = runtime.providers[0]
        self.assertEqual(coreml_entry[0], "CoreMLExecutionProvider")
        self.assertEqual(coreml_entry[1]["MLComputeUnits"], "ALL")
        self.assertEqual(coreml_entry[1]["RequireStaticInputShapes"], "0")
        self.assertEqual(runtime.providers[1], "CPUExecutionProvider")

    def test_macos_aarch64_prefers_coreml(self):
        runtime = get_recognition_runtime("Darwin", "aarch64")

        self.assertEqual(runtime.accelerator_provider, "CoreMLExecutionProvider")
        self.assertEqual(runtime.provider_names[0], "CoreMLExecutionProvider")

    def test_unsupported_platforms_are_rejected_with_diagnostic(self):
        for system, machine in [
            ("Windows", "ARM64"),
            ("Darwin", "x86_64"),
            ("Linux", "x86_64"),
            ("Linux", "aarch64"),
        ]:
            with self.subTest(system=system, machine=machine):
                with self.assertRaises(RuntimeError) as context:
                    get_recognition_runtime(system, machine)
                message = str(context.exception)
                self.assertIn(f"{system} {machine.lower()}", message)
                self.assertIn("Windows AMD64", message)
                self.assertIn("macOS Apple Silicon", message)


if __name__ == "__main__":
    unittest.main()
