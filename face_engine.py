# Thực hiện lấy ảnh -> InsightFace detect -> lấy embedding -> chuẩn hóa embedding



from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis


class FaceEngine:
    """Phát hiện khuôn mặt và tạo embedding bằng InsightFace."""

    def __init__(self) -> None:
        self.app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )

        # ctx_id=-1: chạy bằng CPU.
        # det_size là kích thước ảnh đầu vào cho detector.
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
        Đọc ảnh, phát hiện khuôn mặt và trả về embedding đã chuẩn hóa.

        Returns:
            np.ndarray có shape (512,), dtype float32.
        """
        image_path = Path(image_path)

        if not image_path.exists():
            raise FileNotFoundError(
                f"Không tìm thấy ảnh: {image_path}"
            )

        image = cv2.imread(str(image_path))

        if image is None:
            raise ValueError(
                f"Không thể đọc ảnh: {image_path}"
            )

        faces = self.app.get(image)

        if len(faces) == 0:
            raise ValueError(
                f"Không tìm thấy khuôn mặt trong ảnh: {image_path}"
            )

        if require_single_face and len(faces) != 1:
            raise ValueError(
                f"Ảnh {image_path} có {len(faces)} khuôn mặt. "
                "Ảnh enrollment phải chỉ có một khuôn mặt."
            )

        # Nếu ảnh có nhiều mặt và không bắt buộc single face,
        # chọn khuôn mặt có bounding box lớn nhất.
        face = max(
            faces,
            key=lambda item: self._face_area(item.bbox),
        )

        embedding = np.asarray(
            face.embedding,
            dtype="float32",
        )

        if embedding.ndim != 1:
            embedding = embedding.flatten()

        # Chuẩn hóa vector về độ dài 1 để dùng cosine similarity.
        norm = np.linalg.norm(embedding)

        if norm == 0:
            raise ValueError(
                f"Embedding bằng vector 0: {image_path}"
            )

        embedding = embedding / norm

        return embedding.astype("float32")

    @staticmethod
    def _face_area(bbox: np.ndarray) -> float:
        x1, y1, x2, y2 = bbox
        return float((x2 - x1) * (y2 - y1))