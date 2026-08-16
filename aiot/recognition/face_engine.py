# Read an image, detect faces with InsightFace, generate embeddings, and normalize them.

from dataclasses import dataclass
from pathlib import Path
import io
from contextlib import redirect_stderr
from contextlib import redirect_stdout

import cv2
import numpy as np
import onnxruntime as ort
from insightface.app import FaceAnalysis
from insightface.app.common import Face

from aiot.recognition.runtime import RecognitionRuntime, get_recognition_runtime


@dataclass(frozen=True)
class FaceEmbedding:
    """A normalized embedding and bounding box for one face."""

    bbox: tuple[int, int, int, int]
    embedding: np.ndarray


@dataclass(frozen=True)
class FaceDetection:
    """One SCRFD detection with the landmarks needed for ArcFace alignment."""

    bbox: tuple[int, int, int, int]
    confidence: float
    landmarks: np.ndarray | None


@dataclass(frozen=True)
class ProviderStatus:
    requested: list[str]
    effective: list[str]
    warning: str | None
    gpu_requested: bool
    gpu_active: bool


class FaceEngine:
    """Detect faces and generate embeddings with InsightFace."""

    ALIGN_TEMPLATE = np.array(
        [
            [38.2946, 51.6963],
            [73.5318, 51.5014],
            [56.0252, 71.7366],
            [41.5493, 92.3655],
            [70.7299, 92.2041],
        ],
        dtype="float32",
    )

    def __init__(
        self,
        det_size: int = 640,
        det_thresh: float = 0.5,
        runtime: RecognitionRuntime | None = None,
    ) -> None:
        if det_size <= 0:
            raise ValueError("Detection size must be greater than 0.")
        if not 0 <= det_thresh <= 1:
            raise ValueError("Detection threshold must be between 0 and 1.")

        runtime = runtime or get_recognition_runtime()

        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls()

        available_providers = ort.get_available_providers()
        provider_spec = [
            entry
            for entry in runtime.providers
            if (entry[0] if isinstance(entry, tuple) else entry) in available_providers
        ]
        if not provider_spec:
            raise RuntimeError(
                "No supported ONNX Runtime providers were found. "
                f"Available providers: {available_providers}"
            )

        self.requested_providers = [
            entry[0] if isinstance(entry, tuple) else entry
            for entry in provider_spec
        ]

        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
            self.app = FaceAnalysis(
                name="buffalo_l",
                allowed_modules=["detection", "recognition"],
                providers=provider_spec,
            )

            # ctx_id=-1 runs inference on the CPU, so the accelerator
            # (CUDA on Windows, CoreML on macOS) must use a non-negative id.
            # det_size is the detector input resolution.
            self.app.prepare(
                ctx_id=0 if runtime.accelerator_provider in available_providers else -1,
                det_size=(det_size, det_size),
                det_thresh=det_thresh,
            )

        self.startup_output = "\n".join(
            text.rstrip()
            for text in (captured_stdout.getvalue(), captured_stderr.getvalue())
            if text.strip()
        )
        self.accelerator_provider = runtime.accelerator_provider
        self.detector = self.app.models.get("detection")
        self.recognition_model = self.app.models.get("recognition")
        if self.detector is None or self.recognition_model is None:
            raise RuntimeError("InsightFace buffalo_l must provide detection and recognition models.")
        self.detector_providers = self._model_providers(self.detector)
        self.recognition_providers = self._model_providers(self.recognition_model)
        self.providers = list(self.recognition_providers)
        self._provider_introspection_complete = self._provider_queries_available()
        self.provider_status = ProviderStatus(
            requested=list(self.requested_providers),
            effective=list(self.providers),
            warning=self._build_provider_warning(),
            gpu_requested=self.accelerator_provider in self.requested_providers,
            gpu_active=self._accelerator_active_for_all_models(),
        )

    def extract_embedding(
        self,
        image_path: str | Path,
        require_single_face: bool = True,
    ) -> np.ndarray:
        """
        Read an image, detect faces, and return a normalized embedding.

        Returns:
            A float32 array with shape `(512,)`.
        """
        image_path = Path(image_path)

        if not image_path.exists():
            raise FileNotFoundError(
                f"Image was not found: {image_path}"
            )

        image = cv2.imread(str(image_path))

        if image is None:
            raise ValueError(
                f"Could not read image: {image_path}"
            )

        detections = self.detect_faces(image)

        if len(detections) == 0:
            raise ValueError(
                f"No face was found in image: {image_path}"
            )

        if require_single_face and len(detections) != 1:
            raise ValueError(
                f"Image {image_path} contains {len(detections)} faces. "
                "An enrollment image must contain exactly one face."
            )

        # When multiple faces are allowed, select the largest bounding box.
        detection = max(detections, key=lambda item: self._face_area(item.bbox))
        face = self.embed_detected_face(image, detection)
        if face is None:
            raise ValueError(f"Could not generate an embedding for image: {image_path}")
        return face.embedding

    def extract_faces(self, image: np.ndarray) -> list[FaceEmbedding]:
        """Compatibility helper that embeds every detected face."""
        return [embedding for detection in self.detect_faces(image) if (embedding := self.embed_detected_face(image, detection))]

    def detect_faces(self, image: np.ndarray) -> list[FaceDetection]:
        """Run only SCRFD detection and return frame-local alignment landmarks."""
        if image is None or image.size == 0:
            raise ValueError("Image frame is empty.")
        height, width = image.shape[:2]
        bboxes, landmarks = self.detector.detect(image, max_num=0, metric="default")
        detections: list[FaceDetection] = []
        for index, box in enumerate(bboxes):
            x1 = max(0, int(box[0]))
            y1 = max(0, int(box[1]))
            x2 = min(width - 1, int(box[2]))
            y2 = min(height - 1, int(box[3]))
            if x1 >= x2 or y1 >= y2:
                continue
            keypoints = None
            if landmarks is not None and index < len(landmarks):
                candidate = np.asarray(landmarks[index], dtype="float32")
                if candidate.shape == (5, 2) and np.isfinite(candidate).all():
                    keypoints = candidate.copy()
            detections.append(FaceDetection((x1, y1, x2, y2), float(box[4]), keypoints))
        return detections

    def embed_detected_face(self, image: np.ndarray, detection: FaceDetection) -> FaceEmbedding | None:
        """Align and embed one SCRFD detection with the buffalo_l ArcFace model."""
        if image is None or image.size == 0:
            raise ValueError("Image frame is empty.")
        if detection.landmarks is None or detection.landmarks.shape != (5, 2):
            return None
        face = Face(
            bbox=np.asarray(detection.bbox, dtype="float32"),
            kps=detection.landmarks,
            det_score=detection.confidence,
        )
        embedding = np.asarray(self.recognition_model.get(image, face), dtype="float32").flatten()
        norm = np.linalg.norm(embedding)
        if norm == 0 or not np.isfinite(norm):
            return None
        return FaceEmbedding(detection.bbox, (embedding / norm).astype("float32"))

    def embed_aligned_image(self, image: np.ndarray, fill: float = 0.9) -> FaceEmbedding | None:
        """Embed a pre-aligned face crop using the standard five-point template.

        Surveillance datasets such as ChokePoint ship tight face crops that
        SCRFD detects only at very low confidence, which makes landmark-based
        alignment unreliable. This path treats the crop as roughly centered
        and aligned and synthesizes landmarks from the norm_crop template.
        """
        if image is None or image.size == 0:
            raise ValueError("Image frame is empty.")
        if not 0 < fill <= 1:
            raise ValueError("Alignment fill must be in (0, 1].")
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        height, width = image.shape[:2]
        scale = (min(height, width) * fill) / 112.0
        offset = np.array(
            [(width - 112.0 * scale) / 2.0, (height - 112.0 * scale) / 2.0],
            dtype="float32",
        )
        keypoints = self.ALIGN_TEMPLATE * scale + offset
        face = Face(
            bbox=np.array([0, 0, width, height], dtype="float32"),
            kps=keypoints,
            det_score=1.0,
        )
        embedding = np.asarray(self.recognition_model.get(image, face), dtype="float32").flatten()
        norm = np.linalg.norm(embedding)
        if norm == 0 or not np.isfinite(norm):
            return None
        return FaceEmbedding((0, 0, width, height), (embedding / norm).astype("float32"))

    @staticmethod
    def _face_area(bbox: np.ndarray) -> float:
        x1, y1, x2, y2 = bbox
        return float((x2 - x1) * (y2 - y1))

    def _model_providers(self, model: object) -> list[str]:
        session = getattr(model, "session", None)
        if session is not None and hasattr(session, "get_providers"):
            return list(session.get_providers())
        return list(self.requested_providers)

    def _provider_queries_available(self) -> bool:
        return all(
            getattr(getattr(model, "session", None), "get_providers", None) is not None
            for model in (self.detector, self.recognition_model)
        )

    def _accelerator_active_for_all_models(self) -> bool:
        if not self._provider_introspection_complete:
            return False
        return all(
            self.accelerator_provider in providers
            for providers in (self.detector_providers, self.recognition_providers)
        )

    def _build_provider_warning(self) -> str | None:
        gpu_requested = self.accelerator_provider in self.requested_providers
        gpu_active = self._accelerator_active_for_all_models()
        if not gpu_requested:
            return None
        if gpu_active:
            return None
        if self.startup_output:
            return (
                f"{self.accelerator_provider} was requested but InsightFace is running on CPU. "
                f"ONNX Runtime output: {self.startup_output}"
            )
        return (
            f"{self.accelerator_provider} was requested but InsightFace is running on CPU. "
            "Check that the accelerator runtime is installed and configured correctly."
        )
