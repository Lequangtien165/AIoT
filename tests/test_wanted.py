import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiot.recognition.wanted import DEFAULT_WANTED_CONFIG, WantedList


def write_config(directory: Path, data) -> Path:
    path = directory / "wanted.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class WantedListTests(unittest.TestCase):
    def test_default_config_matches_idoc_labels(self):
        self.assertTrue(DEFAULT_WANTED_CONFIG.exists())
        wanted = WantedList(DEFAULT_WANTED_CONFIG)

        entry = wanted.match("A00147 - Male")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.severity, "high")
        self.assertTrue(wanted.is_wanted("A00147 - Female"))
        self.assertFalse(wanted.is_wanted("Alice"))
        self.assertFalse(wanted.is_wanted(None))

    def test_exact_pattern_matches_only_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_config(
                Path(temp_dir),
                {"schema_version": 1, "wanted": [{"match": "^Nguyen Van A$", "name": "Suspect A", "severity": "critical"}]},
            )
            wanted = WantedList(path)

            self.assertTrue(wanted.is_wanted("Nguyen Van A"))
            self.assertFalse(wanted.is_wanted("Nguyen Van B"))
            self.assertEqual(wanted.match("Nguyen Van A").display_name, "Suspect A")
            self.assertEqual(wanted.match("Nguyen Van A").severity, "critical")

    def test_entries_returns_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wanted = WantedList(write_config(Path(temp_dir), {"schema_version": 1, "wanted": [{"match": "x"}]}))

            entries = wanted.entries()
            entries.clear()

            self.assertEqual(len(wanted.entries()), 1)

    def test_reload_picks_up_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_config(Path(temp_dir), {"schema_version": 1, "wanted": [{"match": "^Alice$"}]})
            wanted = WantedList(path)
            self.assertTrue(wanted.is_wanted("Alice"))

            path.write_text(
                json.dumps({"schema_version": 1, "wanted": [{"match": "^Bob$"}]}),
                encoding="utf-8",
            )
            wanted.reload()

            self.assertFalse(wanted.is_wanted("Alice"))
            self.assertTrue(wanted.is_wanted("Bob"))

    def test_malformed_config_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            cases = [
                "not-json",
                json.dumps({"schema_version": 2, "wanted": []}),
                json.dumps({"schema_version": 1}),
                json.dumps({"schema_version": 1, "wanted": [{"name": "missing match"}]}),
                json.dumps({"schema_version": 1, "wanted": [{"match": "[unclosed"}]}),
                json.dumps({"schema_version": 1, "wanted": "not-a-list"}),
            ]
            for index, content in enumerate(cases):
                path = base / f"wanted-{index}.json"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises((ValueError, json.JSONDecodeError), msg=content[:60]):
                    WantedList(path)

    def test_missing_config_file_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileNotFoundError):
                WantedList(Path(temp_dir) / "missing.json")


if __name__ == "__main__":
    unittest.main()
