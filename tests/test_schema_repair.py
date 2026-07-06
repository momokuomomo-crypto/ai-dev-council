import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council.schema_repair import repair_stuffed_json


class TestRepairStuffedJson(unittest.TestCase):
    def test_returns_data_unchanged_when_all_keys_present(self):
        data = {"approved": True, "issues": [], "suggestions": []}
        result = repair_stuffed_json(data, ["approved", "issues", "suggestions"])
        self.assertEqual(result, data)

    def test_repairs_when_remaining_keys_are_stuffed_into_one_string_value(self):
        malformed = {"approved": 'true, "issues": [], "suggestions": ["a"]}'}
        # approvedがbool以外（文字列先頭）の形で壊れているケースは対象外なので、
        # ai-council同様、文字列値のキーに他キーが埋め込まれるケースを再現する。
        malformed = {
            "issues": '[], "approved": true, "suggestions": ["a"]}'
        }
        result = repair_stuffed_json(malformed, ["approved", "issues", "suggestions"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["approved"], True)
        self.assertEqual(result["suggestions"], ["a"])

    def test_raises_when_repair_is_not_possible(self):
        malformed = {"issues": "not valid json at all"}
        with self.assertRaises(RuntimeError):
            repair_stuffed_json(malformed, ["approved", "issues", "suggestions"])

    def test_raises_with_missing_keys_when_no_string_field_available(self):
        malformed = {"issues": []}
        with self.assertRaises(RuntimeError):
            repair_stuffed_json(malformed, ["approved", "issues", "suggestions"])


if __name__ == "__main__":
    unittest.main()
