# Generate a query embedding, search FAISS, group hits by person, and apply the threshold.



from collections import defaultdict
from pathlib import Path
import argparse
import json
import sys

import cv2
import faiss
import numpy as np

from aiot.recognition.face_engine import FaceEngine


# Prevent non-ASCII output from failing on legacy Windows code pages.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


INDEX_PATH = Path("database/faces.index")
METADATA_PATH = Path("database/metadata.json")

# This is a demo starting point.
# Calibrate it with real data.
DEFAULT_THRESHOLD = 0.45


def load_database() -> tuple[
    faiss.Index,
    list[dict],
]:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            "FAISS index was not found. "
            "Run python build_index.py first."
        )

    if not METADATA_PATH.exists():
        raise FileNotFoundError(
            "metadata.json was not found."
        )

    index = faiss.read_index(
        str(INDEX_PATH)
    )

    with METADATA_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        metadata = json.load(file)

    if index.ntotal != len(metadata):
        raise ValueError(
            "The number of vectors in the index does not match the metadata."
        )

    return index, metadata


def recognize(
    image_path: Path,
    threshold: float,
    top_k: int,
) -> None:
    index, metadata = load_database()
    engine = FaceEngine()

    query_embedding = engine.extract_embedding(
        image_path,
        require_single_face=False,
    )

    query = query_embedding.reshape(
        1,
        -1,
    ).astype("float32")

    faiss.normalize_L2(query)

    k = min(
        top_k,
        index.ntotal,
    )

    similarities, indices = index.search(
        query,
        k,
    )

    # A person can have multiple enrollment images.
    # Keep that person's highest score.
    best_by_person: dict[str, dict] = {}

    print("\nNearest vectors:")

    for rank, (vector_id, similarity) in enumerate(
        zip(indices[0], similarities[0]),
        start=1,
    ):
        vector_id = int(vector_id)
        similarity = float(similarity)

        if vector_id < 0:
            continue

        item = metadata[vector_id]
        person_name = item["person_name"]

        print(
            f"Top {rank}: "
            f"{person_name} "
            f"| similarity={similarity:.4f} "
            f"| source={item['image_path']}"
        )

        current = best_by_person.get(person_name)

        if (
            current is None
            or similarity > current["similarity"]
        ):
            best_by_person[person_name] = {
                "similarity": similarity,
                "image_path": item["image_path"],
            }

    if not best_by_person:
        print("No results found.")
        return

    ranked_people = sorted(
        best_by_person.items(),
        key=lambda item: item[1]["similarity"],
        reverse=True,
    )

    best_name, best_result = ranked_people[0]
    best_similarity = best_result["similarity"]

    print("\nResults by person:")

    for name, result in ranked_people:
        print(
            f"- {name}: "
            f"{result['similarity']:.4f}"
        )

    print("\nRESULT")

    if best_similarity >= threshold:
        print(f"MATCH: {best_name}")
        print(
            f"Cosine similarity: "
            f"{best_similarity:.4f}"
        )
    else:
        print("UNKNOWN")
        print(
            f"Nearest person: {best_name}"
        )
        print(
            f"Cosine similarity: "
            f"{best_similarity:.4f}"
        )
        print(
            f"Threshold: {threshold:.4f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Recognize faces with InsightFace + FAISS."
        )
    )

    parser.add_argument(
        "image",
        type=Path,
        help="Path to the image to recognize.",
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=(
            "Cosine similarity threshold. "
            f"Default: {DEFAULT_THRESHOLD}"
        ),
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of nearest vectors to retrieve.",
    )

    args = parser.parse_args()

    if not args.image.exists():
        raise FileNotFoundError(
            f"Image was not found: {args.image}"
        )

    if not 0.0 <= args.threshold <= 1.0:
        raise ValueError(
            "Threshold must be between 0 and 1."
        )

    if args.top_k <= 0:
        raise ValueError(
            "top-k must be greater than 0."
        )

    recognize(
        image_path=args.image,
        threshold=args.threshold,
        top_k=args.top_k,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nError: {error}")
        sys.exit(1)
