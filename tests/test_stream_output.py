import unittest

from aiot.streaming.stream_output import safe_name


class SafeNameTests(unittest.TestCase):
    def test_removes_path_characters(self):
        self.assertEqual(safe_name("Alice / Admin"), "alice-admin")

    def test_falls_back_when_no_ascii_characters_remain(self):
        self.assertEqual(safe_name("????"), "unknown-person")


if __name__ == "__main__":
    unittest.main()
