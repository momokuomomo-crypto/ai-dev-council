import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council import test_runner


class TestRunTestsAndSaveLog(unittest.TestCase):
    def test_skips_when_tests_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch.object(test_runner.subprocess, "run") as fake_run:
                result = test_runner.run_tests_and_save_log(output_dir, label="impl")

            fake_run.assert_not_called()
            self.assertEqual(result["total"], 0)
            self.assertTrue(result["log_path"].exists())
            self.assertTrue(result["csv_path"].exists())
            self.assertIn("見つからない", result["log_path"].read_text(encoding="utf-8"))

    def test_parses_pytest_verbose_output_into_csv_rows(self):
        fake_stdout = (
            "tests/test_app.py::test_a PASSED                    [ 50%]\n"
            "tests/test_app.py::test_b FAILED                    [100%]\n"
        )
        fake_proc = mock.Mock(stdout=fake_stdout, stderr="", returncode=1)

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "tests").mkdir()
            with mock.patch.object(test_runner.subprocess, "run", return_value=fake_proc):
                result = test_runner.run_tests_and_save_log(output_dir, label="final")

            csv_text = result["csv_path"].read_text(encoding="utf-8-sig")

            self.assertEqual(result["total"], 2)
            self.assertEqual(result["passed"], 1)
            self.assertEqual(result["failed"], 1)
            self.assertIn("tests/test_app.py::test_a", csv_text)
            self.assertIn("PASSED", csv_text)
            self.assertIn("tests/test_app.py::test_b", csv_text)
            self.assertIn("FAILED", csv_text)
            # ログファイルの相対パスと行数が記録されていること
            self.assertIn("test_logs", csv_text)
            self.assertIn(",1\n", csv_text.replace("\r\n", "\n") + "\n")

    def test_does_not_raise_when_subprocess_fails_to_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "tests").mkdir()
            with mock.patch.object(
                test_runner.subprocess, "run", side_effect=FileNotFoundError("python not found")
            ):
                result = test_runner.run_tests_and_save_log(output_dir)

            self.assertEqual(result["total"], 0)
            self.assertIn("失敗しました", result["log_path"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
