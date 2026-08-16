import unittest
from unittest import mock

import numpy as np

from aiot.recognition.face_engine import FaceDetection, FaceEngine, ProviderStatus
from aiot.recognition.runtime import get_recognition_runtime


class _FakeSession:
    def __init__(self, providers):
        self._providers = list(providers)

    def get_providers(self):
        return self._providers


class _FakeModel:
    def __init__(self, providers):
        self.session = _FakeSession(providers)


_MODEL_PROVIDERS: dict[str, list[str]] = {}


class _NoSessionModel:
    pass


class _FakeFaceAnalysis:
    last: "_FakeFaceAnalysis" = None

    def __init__(self, **kwargs):
        type(self).last = self
        self.kwargs = kwargs
        self.models = {
            name: provider
            for name, provider in _MODEL_PROVIDERS.items()
        }

    def prepare(self, ctx_id, det_size, det_thresh=0.5):
        self.ctx_id = ctx_id
        self.det_size = det_size
        self.det_thresh = det_thresh


class FaceEngineInitTests(unittest.TestCase):
    def setUp(self):
        _MODEL_PROVIDERS.clear()
        _FakeFaceAnalysis.last = None

    def _build(
        self,
        available_providers,
        runtime,
        detector_providers=None,
        recognition_providers=None,
        no_introspection=False,
    ):
        if no_introspection:
            _MODEL_PROVIDERS["detection"] = _NoSessionModel()
            _MODEL_PROVIDERS["recognition"] = _NoSessionModel()
        else:
            _MODEL_PROVIDERS["detection"] = _FakeModel(detector_providers or available_providers)
            _MODEL_PROVIDERS["recognition"] = _FakeModel(recognition_providers or available_providers)
        with mock.patch("aiot.recognition.face_engine.ort") as fake_ort, mock.patch(
            "aiot.recognition.face_engine.FaceAnalysis",
            side_effect=_FakeFaceAnalysis,
        ) as fake_analysis, mock.patch(
            "aiot.recognition.face_engine.get_recognition_runtime",
            return_value=runtime,
        ):
            fake_ort.get_available_providers.return_value = list(available_providers)
            engine = FaceEngine()
            return engine, fake_analysis, _FakeFaceAnalysis.last

    def test_coreml_binds_to_both_models_when_available(self):
        runtime = get_recognition_runtime("Darwin", "arm64")

        engine, fake_analysis, app = self._build(
            ["CoreMLExecutionProvider", "CPUExecutionProvider"],
            runtime,
        )

        self.assertEqual(
            fake_analysis.call_args.kwargs["providers"],
            [
                ("CoreMLExecutionProvider", {"MLComputeUnits": "ALL", "RequireStaticInputShapes": "0"}),
                "CPUExecutionProvider",
            ],
        )
        self.assertEqual(app.ctx_id, 0)
        self.assertEqual(app.det_size, (640, 640))
        self.assertEqual(engine.accelerator_provider, "CoreMLExecutionProvider")
        self.assertEqual(engine.requested_providers, ["CoreMLExecutionProvider", "CPUExecutionProvider"])
        self.assertEqual(engine.providers, ["CoreMLExecutionProvider", "CPUExecutionProvider"])
        self.assertTrue(engine.provider_status.gpu_requested)
        self.assertTrue(engine.provider_status.gpu_active)
        self.assertIsNone(engine.provider_status.warning)

    def test_coreml_unavailable_falls_back_to_cpu(self):
        runtime = get_recognition_runtime("Darwin", "arm64")

        engine, fake_analysis, app = self._build(
            ["CPUExecutionProvider"],
            runtime,
        )

        self.assertEqual(fake_analysis.call_args.kwargs["providers"], ["CPUExecutionProvider"])
        self.assertEqual(app.ctx_id, -1)
        self.assertEqual(engine.provider_status.gpu_requested, False)
        self.assertEqual(engine.provider_status.gpu_active, False)
        self.assertIsNone(engine.provider_status.warning)

    def test_coreml_bound_to_one_model_is_not_active(self):
        runtime = get_recognition_runtime("Darwin", "arm64")

        engine, fake_analysis, app = self._build(
            ["CoreMLExecutionProvider", "CPUExecutionProvider"],
            runtime,
            detector_providers=["CoreMLExecutionProvider", "CPUExecutionProvider"],
            recognition_providers=["CPUExecutionProvider"],
        )

        self.assertEqual(app.ctx_id, 0)
        self.assertEqual(engine.provider_status.gpu_active, False)
        self.assertIsNotNone(engine.provider_status.warning)
        self.assertIn("CoreMLExecutionProvider", engine.provider_status.warning)
        self.assertNotIn("cuBLAS", engine.provider_status.warning)

    def test_windows_cuda_binds_to_both_models(self):
        runtime = get_recognition_runtime("Windows", "AMD64")

        engine, fake_analysis, app = self._build(
            ["CUDAExecutionProvider", "CPUExecutionProvider"],
            runtime,
        )

        self.assertEqual(
            fake_analysis.call_args.kwargs["providers"],
            ["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        self.assertEqual(app.ctx_id, 0)
        self.assertEqual(engine.accelerator_provider, "CUDAExecutionProvider")
        self.assertTrue(engine.provider_status.gpu_requested)
        self.assertTrue(engine.provider_status.gpu_active)
        self.assertIsNone(engine.provider_status.warning)

    def test_windows_cuda_unavailable_falls_back_to_cpu(self):
        runtime = get_recognition_runtime("Windows", "AMD64")

        engine, fake_analysis, app = self._build(
            ["CPUExecutionProvider"],
            runtime,
        )

        self.assertEqual(fake_analysis.call_args.kwargs["providers"], ["CPUExecutionProvider"])
        self.assertEqual(app.ctx_id, -1)
        self.assertEqual(engine.provider_status.gpu_requested, False)
        self.assertEqual(engine.provider_status.gpu_active, False)
        self.assertIsNone(engine.provider_status.warning)


    def test_missing_session_introspection_is_fail_closed(self):
        runtime = get_recognition_runtime("Darwin", "arm64")

        engine, fake_analysis, app = self._build(
            ["CoreMLExecutionProvider", "CPUExecutionProvider"],
            runtime,
            no_introspection=True,
        )

        self.assertEqual(
            fake_analysis.call_args.kwargs["providers"],
            [
                ("CoreMLExecutionProvider", {"MLComputeUnits": "ALL", "RequireStaticInputShapes": "0"}),
                "CPUExecutionProvider",
            ],
        )
        self.assertEqual(app.ctx_id, 0)
        self.assertTrue(engine.provider_status.gpu_requested)
        self.assertFalse(engine.provider_status.gpu_active)
        self.assertIsNotNone(engine.provider_status.warning)

    def test_injected_runtime_bypasses_platform_detection(self):
        windows_runtime = get_recognition_runtime("Windows", "AMD64")
        _MODEL_PROVIDERS["detection"] = _FakeModel(["CUDAExecutionProvider", "CPUExecutionProvider"])
        _MODEL_PROVIDERS["recognition"] = _FakeModel(["CUDAExecutionProvider", "CPUExecutionProvider"])
        with mock.patch("aiot.recognition.face_engine.ort") as fake_ort, mock.patch(
            "aiot.recognition.face_engine.FaceAnalysis",
            side_effect=_FakeFaceAnalysis,
        ) as fake_analysis, mock.patch(
            "aiot.recognition.face_engine.get_recognition_runtime",
            side_effect=AssertionError("platform detection must not run when runtime is injected"),
        ):
            fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            engine = FaceEngine(runtime=windows_runtime)
            app = _FakeFaceAnalysis.last

        self.assertEqual(
            fake_analysis.call_args.kwargs["providers"],
            ["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        self.assertEqual(app.ctx_id, 0)
        self.assertEqual(engine.accelerator_provider, "CUDAExecutionProvider")
        self.assertTrue(engine.provider_status.gpu_active)


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


class SplitInferenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = object.__new__(FaceEngine)

    def test_detect_faces_returns_bbox_score_and_landmarks_without_embedding(self):
        class Detector:
            def detect(self, _image, max_num, metric):
                self.max_num = max_num
                self.metric = metric
                return (
                    np.array([[1.2, 2.1, 20.8, 30.7, 0.9]], dtype="float32"),
                    np.array([[[2, 3], [10, 3], [6, 8], [3, 15], [9, 15]]], dtype="float32"),
                )

        self.engine.detector = Detector()
        image = np.zeros((40, 40, 3), dtype="uint8")

        detections = self.engine.detect_faces(image)

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].bbox, (1, 2, 20, 30))
        self.assertAlmostEqual(detections[0].confidence, 0.9)
        self.assertEqual(detections[0].landmarks.shape, (5, 2))
        self.assertEqual(self.engine.detector.max_num, 0)
        self.assertEqual(self.engine.detector.metric, "default")

    def test_embed_detected_face_normalizes_single_arcface_embedding(self):
        class RecognitionModel:
            def get(self, _image, face):
                self.landmarks = face.kps
                return np.array([3.0, 4.0], dtype="float32")

        self.engine.recognition_model = RecognitionModel()
        detection = FaceDetection(
            bbox=(1, 2, 20, 30),
            confidence=0.9,
            landmarks=np.array([[2, 3], [10, 3], [6, 8], [3, 15], [9, 15]], dtype="float32"),
        )

        result = self.engine.embed_detected_face(np.zeros((40, 40, 3), dtype="uint8"), detection)

        self.assertEqual(result.bbox, detection.bbox)
        self.assertEqual(result.embedding.dtype, np.float32)
        self.assertAlmostEqual(float(np.linalg.norm(result.embedding)), 1.0)
        np.testing.assert_array_equal(self.engine.recognition_model.landmarks, detection.landmarks)

    def test_embed_detected_face_skips_missing_landmarks(self):
        self.engine.recognition_model = object()
        detection = FaceDetection((1, 2, 20, 30), 0.9, None)

        self.assertIsNone(self.engine.embed_detected_face(np.zeros((40, 40, 3), dtype="uint8"), detection))


if __name__ == "__main__":
    unittest.main()
