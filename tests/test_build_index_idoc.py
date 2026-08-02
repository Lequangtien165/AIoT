import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_index


class IdocDatasetMappingTests(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, str]], *, encoding: str = "utf-8") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding=encoding, newline="") as file:
            writer = csv.DictWriter(file, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def test_load_idoc_labels_maps_manifest_folder_to_id_and_sex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset_dir = root / "dataset"
            labels_path = root / "archive" / "labels_utf8.csv"
            manifest_path = dataset_dir / "IDOC_manifest.csv"
            self.write_csv(
                manifest_path,
                [{"folder": "IDOC_000001", "source_id": "A00147"}],
            )
            self.write_csv(
                labels_path,
                [{"ID": "A00147", "Sex": "Male"}],
                encoding="utf-8-sig",
            )

            with patch.multiple(
                build_index,
                DATASET_DIR=dataset_dir,
                IDOC_MANIFEST_PATH=manifest_path,
                IDOC_LABELS_PATHS=(labels_path,),
            ):
                labels = build_index.load_idoc_labels()

        self.assertEqual(labels, {"IDOC_000001": "A00147 - Male"})

    def test_load_idoc_labels_falls_back_when_manifest_or_labels_are_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset_dir = root / "dataset"
            manifest_path = dataset_dir / "IDOC_manifest.csv"
            with patch.multiple(
                build_index,
                DATASET_DIR=dataset_dir,
                IDOC_MANIFEST_PATH=manifest_path,
                IDOC_LABELS_PATHS=(root / "missing.csv",),
            ):
                self.assertEqual(build_index.load_idoc_labels(), {})

            self.write_csv(
                manifest_path,
                [{"folder": "IDOC_000001", "source_id": "A00147"}],
            )
            with patch.multiple(
                build_index,
                DATASET_DIR=dataset_dir,
                IDOC_MANIFEST_PATH=manifest_path,
                IDOC_LABELS_PATHS=(root / "missing.csv",),
            ):
                self.assertEqual(build_index.load_idoc_labels(), {"IDOC_000001": "A00147"})

    def test_collect_images_applies_idoc_label_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset_dir = root / "dataset"
            labels_path = root / "archive" / "labels_utf8.csv"
            manifest_path = dataset_dir / "IDOC_manifest.csv"
            (dataset_dir / "IDOC_000001").mkdir(parents=True)
            (dataset_dir / "IDOC_000001" / "front.jpg").write_bytes(b"image")
            (dataset_dir / "IDOC_000001" / "notes.txt").write_text("skip", encoding="utf-8")
            (dataset_dir / "Alice").mkdir()
            (dataset_dir / "Alice" / "face.png").write_bytes(b"image")
            self.write_csv(
                manifest_path,
                [{"folder": "IDOC_000001", "source_id": "A00147"}],
            )
            self.write_csv(labels_path, [{"ID": "A00147", "Sex": "Female"}], encoding="utf-8-sig")

            with patch.multiple(
                build_index,
                DATASET_DIR=dataset_dir,
                IDOC_MANIFEST_PATH=manifest_path,
                IDOC_LABELS_PATHS=(labels_path,),
            ):
                samples = build_index.collect_images()

        self.assertEqual(
            samples,
            [
                ("Alice", dataset_dir / "Alice" / "face.png"),
                ("A00147 - Female", dataset_dir / "IDOC_000001" / "front.jpg"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
