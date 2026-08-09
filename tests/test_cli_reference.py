"""The generated CLI reference must match the argparse definitions.

Run `python scripts/generate_cli_reference.py` when this test fails, then
commit the regenerated `docs/CLI_REFERENCE.md` together with the code change.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.generate_cli_reference as gen


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


DOC_PATH = PROJECT_ROOT / "docs" / "CLI_REFERENCE.md"


class CliReferenceTests(unittest.TestCase):
    def test_committed_auto_region_matches_generated_content(self):
        doc = _normalize(DOC_PATH.read_text(encoding="utf-8"))
        self.assertIn(gen.AUTO_START, doc)
        self.assertIn(gen.AUTO_END, doc)
        start = doc.rindex(gen.AUTO_START)
        end = doc.rindex(gen.AUTO_END) + len(gen.AUTO_END)
        committed = doc[start:end]
        generated = _normalize(gen.render_auto_section())
        self.assertEqual(
            generated,
            committed,
            "docs/CLI_REFERENCE.md is out of date. "
            "Run: python scripts/generate_cli_reference.py",
        )

    def test_every_entry_point_exposes_a_build_parser(self):
        for entry in gen.ENTRIES:
            with self.subTest(command=entry.command):
                parser = gen.build_parser_for(entry)
                self.assertIsNotNone(parser)
                self.assertTrue(parser._actions)


if __name__ == "__main__":
    unittest.main()