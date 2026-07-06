import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council import usage_tracker


class TestCheckAndIncrement(unittest.TestCase):
    def test_allows_execution_when_under_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage_path = Path(tmp) / ".usage_count.json"
            with mock.patch.object(usage_tracker, "_USAGE_PATH", usage_path):
                usage_tracker.check_and_increment(max_runs_per_day=3, today="2026-07-06")
                usage_tracker.check_and_increment(max_runs_per_day=3, today="2026-07-06")

                self.assertEqual(usage_tracker._read_usage()["2026-07-06"], 2)

    def test_raises_when_limit_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage_path = Path(tmp) / ".usage_count.json"
            with mock.patch.object(usage_tracker, "_USAGE_PATH", usage_path):
                usage_tracker.check_and_increment(max_runs_per_day=2, today="2026-07-06")
                usage_tracker.check_and_increment(max_runs_per_day=2, today="2026-07-06")
                with self.assertRaises(RuntimeError):
                    usage_tracker.check_and_increment(max_runs_per_day=2, today="2026-07-06")

    def test_counts_are_isolated_per_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage_path = Path(tmp) / ".usage_count.json"
            with mock.patch.object(usage_tracker, "_USAGE_PATH", usage_path):
                usage_tracker.check_and_increment(max_runs_per_day=1, today="2026-07-06")
                # 別の日付なら上限がリセットされる
                usage_tracker.check_and_increment(max_runs_per_day=1, today="2026-07-07")


if __name__ == "__main__":
    unittest.main()
