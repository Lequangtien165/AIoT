"""FAISS database access shared by image and stream recognition."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import faiss
import numpy as np


INDEX_PATH = Path("database/faces.index")
METADATA_PATH = Path("database/metadata.json")


class FaceRecognizer:
    """Find the nearest person in FAISS using cosine similarity."""

    def __init__(self) -> None:
        if not INDEX_PATH.exists() or not METADATA_PATH.exists():
            raise FileNotFoundError("Recognition database was not found. Run python build_index.py first.")
        self.index = faiss.read_index(str(INDEX_PATH))
        with METADATA_PATH.open(encoding="utf-8") as file:
            self.metadata: list[dict[str, str | int]] = json.load(file)
        if self.index.ntotal != len(self.metadata):
            raise ValueError("The number of vectors in the index does not match the metadata.")

    def search(self, embeddings: np.ndarray, top_k: int = 5) -> list[tuple[str, float]]:
        """Return the highest-scoring person for each input embedding."""
        if embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)
        if embeddings.shape[0] == 0:
            return []

        queries = np.ascontiguousarray(embeddings, dtype="float32")
        faiss.normalize_L2(queries)
        k = min(top_k, self.index.ntotal)
        similarities, indices = self.index.search(queries, k)
        results: list[tuple[str, float]] = []

        for vector_ids, scores in zip(indices, similarities):
            best_by_person: dict[str, float] = defaultdict(lambda: float("-inf"))
            for vector_id, score in zip(vector_ids, scores):
                if vector_id < 0:
                    continue
                person_name = str(self.metadata[int(vector_id)]["person_name"])
                best_by_person[person_name] = max(best_by_person[person_name], float(score))
            if not best_by_person:
                results.append(("", float("-inf")))
                continue
            name, score = max(best_by_person.items(), key=lambda item: item[1])
            results.append((name, score))

        return results
