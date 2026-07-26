# Read an image, detect faces with InsightFace, generate embeddings, and normalize them.



from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis


@dataclass(frozen=True)
class FaceEmbedding:
    """A normalized embedding and bounding box for one face."""

    bbox: tuple[int, int, int, int]
    embedding: np.ndarray


class FaceEngine:
    """Detect faces and generate embeddings with InsightFace."""

    def __init__(self) -> None:
        self.app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )

        # ctx_id=-1 runs inference on the CPU.
        # det_size is the detector input resolution.
        self.app.prepare(
            ctx_id=-1,
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

    @staticmethod
    def _face_area(bbox: np.ndarray) -> float:
        x1, y1, x2, y2 = bbox
        return float((x2 - x1) * (y2 - y1))
