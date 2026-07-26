import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.setup_tools import safe_extract, verify_checksum


class ChecksumTests(unittest.TestCase):
    def test_checksum_accepts_matching_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "tool.exe"
            file_path.write_bytes(b"verified")

            verify_checksum(file_path, hashlib.sha256(b"verified").hexdigest())

    def test_checksum_rejects_mismatched_file_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "tool.exe"
            file_path.write_bytes(b"unverified")

            with self.assertRaises(RuntimeError):
                verify_checksum(file_path, "0" * 64)
            self.assertTrue(file_path.exists())

    def test_safe_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("../escape.txt", "no")

            with zipfile.ZipFile(archive) as zip_file:
                with self.assertRaises(RuntimeError):
                    safe_extract(zip_file, root / "extract")


if __name__ == "__main__":
    unittest.main()
