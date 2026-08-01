import unittest

import numpy as np

from aiot.recognition.face_engine import FaceDetection, FaceEngine, ProviderStatus


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
