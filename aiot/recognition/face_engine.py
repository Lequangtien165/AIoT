# Read an image, detect faces with InsightFace, generate embeddings, and normalize them.



from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from insightface.app import FaceAnalysis


@dataclass(frozen=True)
class FaceEmbedding:
    """A normalized embedding and bounding box for one face."""

    bbox: tuple[int, int, int, int]
    embedding: np.ndarray


class FaceEngine:
    """Detect faces and generate embeddings with InsightFace."""

    def __init__(self) -> None:
        available_providers = ort.get_available_providers()
        preferred_providers = [
            provider
            for provider in ("CUDAExecutionProvider", "CPUExecutionProvider")
            if provider in available_providers
        ]
        if not preferred_providers:
            raise RuntimeError(
                "No supported ONNX Runtime providers were found. "
                f"Available providers: {available_providers}"
            )

        self.app = FaceAnalysis(
            name="buffalo_l",
            providers=preferred_providers,
        )
        self.providers = preferred_providers

        # ctx_id=-1 runs inference on the CPU.
        # det_size is the detector input resolution.
        self.app.prepare(
            ctx_id=0 if "CUDAExecutionProvider" in preferred_providers else -1,
            det_size=(640, 640),
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

        faces = self.extract_faces(image)

        if len(faces) == 0:
            raise ValueError(
                f"No face was found in image: {image_path}"
            )

        if require_single_face and len(faces) != 1:
            raise ValueError(
                f"Image {image_path} contains {len(faces)} faces. "
                "An enrollment image must contain exactly one face."
            )

        # When multiple faces are allowed, select the largest bounding box.
        face = max(faces, key=lambda item: self._face_area(item.bbox))
        return face.embedding

    def extract_faces(self, image: np.ndarray) -> list[FaceEmbedding]:
        """Return all faces in a BGR frame with normalized embeddings."""
        if image is None or image.size == 0:
            raise ValueError("Image frame is empty.")

        faces: list[FaceEmbedding] = []
        for face in self.app.get(image):
            embedding = np.asarray(face.embedding, dtype="float32").flatten()
            norm = np.linalg.norm(embedding)
            if norm == 0:
                continue

            x1, y1, x2, y2 = (int(value) for value in face.bbox)
            faces.append(
                FaceEmbedding(
                    bbox=(x1, y1, x2, y2),
                    embedding=(embedding / norm).astype("float32"),
                )
            )
        return faces

    def extract_face_from_bbox(
        self,
        image: np.ndarray,
        bbox: tuple[int, int, int, int],
        margin: float = 0.20,
    ) -> FaceEmbedding | None:
        """Generate an embedding for the face nearest to the supplied bounding box."""
        if image is None or image.size == 0:
            raise ValueError("Image frame is empty.")

        height, width = image.shape[:2]
        x1, y1, x2, y2 = bbox
        box_width = max(1, x2 - x1)
        box_height = max(1, y2 - y1)
        pad_x = int(box_width * margin)
        pad_y = int(box_height * margin)
        crop_x1 = max(0, x1 - pad_x)
        crop_y1 = max(0, y1 - pad_y)
        crop_x2 = min(width, x2 + pad_x)
        crop_y2 = min(height, y2 + pad_y)

        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            return None

        crop = image[crop_y1:crop_y2, crop_x1:crop_x2]
        faces = self.extract_faces(crop)
        if not faces:
            return None

        target_center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

        def distance_to_target(face: FaceEmbedding) -> float:
            fx1, fy1, fx2, fy2 = face.bbox
            center_x = crop_x1 + (fx1 + fx2) / 2.0
            center_y = crop_y1 + (fy1 + fy2) / 2.0
            return float((center_x - target_center[0]) ** 2 + (center_y - target_center[1]) ** 2)

        match = min(faces, key=distance_to_target)
        fx1, fy1, fx2, fy2 = match.bbox
        return FaceEmbedding(
            bbox=(crop_x1 + fx1, crop_y1 + fy1, crop_x1 + fx2, crop_y1 + fy2),
            embedding=match.embedding,
        )

    @staticmethod
    def _face_area(bbox: np.ndarray) -> float:
        x1, y1, x2, y2 = bbox
        return float((x2 - x1) * (y2 - y1))
