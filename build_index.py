# Read enrollment images, generate embeddings, and write the FAISS index with metadata.


from pathlib import Path
import json
import sys

import faiss
import numpy as np

from aiot.recognition.face_engine import FaceEngine


# Prevent non-ASCII output from failing on legacy Windows code pages.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


DATASET_DIR = Path("dataset")
DATABASE_DIR = Path("database")

INDEX_PATH = DATABASE_DIR / "faces.index"
METADATA_PATH = DATABASE_DIR / "metadata.json"

VALID_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


def collect_images() -> list[tuple[str, Path]]:
    """
    Return entries in this form:
    [
        ("tien", Path("dataset/tien/tien_01.jpg")),
        ...
    ]
    """
    samples: list[tuple[str, Path]] = []

    if not DATASET_DIR.exists():
        raise FileNotFoundError(
            f"Dataset directory was not found: "
            f"{DATASET_DIR.resolve()}"
        )

    for person_dir in sorted(DATASET_DIR.iterdir()):
        if not person_dir.is_dir():
            continue

        person_name = person_dir.name

        for image_path in sorted(person_dir.iterdir()):
            if image_path.suffix.lower() not in VALID_EXTENSIONS:
                continue

            samples.append((person_name, image_path))

    return samples


def main() -> None:
    samples = collect_images()

    if not samples:
        raise RuntimeError(
            "The dataset contains no valid images."
        )

    engine = FaceEngine()

    embeddings: list[np.ndarray] = []
    metadata: list[dict[str, str | int]] = []

    print(f"Found {len(samples)} images.")
    print("-" * 60)

    for person_name, image_path in samples:
        print(f"Processing: {image_path}")

        try:
            embedding = engine.extract_embedding(
                image_path,
                require_single_face=True,
            )
        except Exception as error:
            print(f"  Skipped: {error}")
            continue

        vector_id = len(embeddings)

        embeddings.append(embedding)

        metadata.append(
            {
                "vector_id": vector_id,
                "person_name": person_name,
                "image_path": str(image_path),
            }
        )

        print(
            f"  OK | person={person_name} "
            f"| dimensions={embedding.shape[0]}"
        )

    if not embeddings:
        raise RuntimeError(
            "No embeddings were created."
        )

    embedding_matrix = np.vstack(
        embeddings
    ).astype("float32")

    dimension = embedding_matrix.shape[1]

    # Verify normalization before adding vectors to FAISS.
    faiss.normalize_L2(embedding_matrix)

    # IndexFlatIP performs exact inner-product search.
    # With normalized vectors, the score is cosine similarity.
    index = faiss.IndexFlatIP(dimension)

    index.add(embedding_matrix)

    DATABASE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    faiss.write_index(
        index,
        str(INDEX_PATH),
    )

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2,
        )

    people = {
        item["person_name"]
        for item in metadata
    }

    print("\n" + "=" * 60)
    print("INDEX BUILD SUCCEEDED")
    print(f"People: {len(people)}")
    print(f"Embeddings: {index.ntotal}")
    print(f"Dimensions: {dimension}")
    print(f"FAISS index: {INDEX_PATH.resolve()}")
    print(f"Metadata: {METADATA_PATH.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nError: {error}")
        sys.exit(1)
