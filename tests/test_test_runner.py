import os
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


_SAMPLE_TRX = """<?xml version="1.0" encoding="utf-8"?>
<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <UnitTestResult testName="Namespace.ClassTests.PassingTest" outcome="Passed" />
    <UnitTestResult testName="Namespace.ClassTests.FailingTest" outcome="Failed" />
  </Results>
</TestRun>
"""


class TestDotnetProjectDetection(unittest.TestCase):
    def test_runs_dotnet_test_when_csproj_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "MyApp.csproj").write_text("<Project />", encoding="utf-8")
            log_dir = output_dir / "test_logs"

            def _fake_run(cmd, cwd, capture_output, text, timeout, env):
                log_dir.mkdir(parents=True, exist_ok=True)
                # --logger trx;LogFileName=... の値からファイル名を取り出して書き出す
                logger_arg = cmd[cmd.index("--logger") + 1]
                trx_filename = logger_arg.split("LogFileName=")[1]
                (log_dir / trx_filename).write_text(_SAMPLE_TRX, encoding="utf-8")
                return mock.Mock(
                    stdout="Passed Namespace.ClassTests.PassingTest\nFailed Namespace.ClassTests.FailingTest\n",
                    stderr="",
                )

            with mock.patch.object(test_runner.subprocess, "run", side_effect=_fake_run) as fake_run:
                result = test_runner.run_tests_and_save_log(output_dir, label="final")

            fake_run.assert_called_once()
            argv = fake_run.call_args.args[0]
            self.assertEqual(argv[:2], ["dotnet", "test"])

            self.assertEqual(result["project_type"], "dotnet")
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["passed"], 1)
            self.assertEqual(result["failed"], 1)

            csv_text = result["csv_path"].read_text(encoding="utf-8-sig")
            self.assertIn("Namespace.ClassTests.PassingTest", csv_text)
            self.assertIn("PASSED", csv_text)
            self.assertIn("Namespace.ClassTests.FailingTest", csv_text)
            self.assertIn("FAILED", csv_text)

    def test_resolves_relative_output_dir_to_avoid_double_nested_results_dir(self):
        """
        実際の不具合の再現テスト。output_dirが相対パスのまま
        --results-directoryに渡されると、dotnet test自身のcwd
        （=output_dir）基準でその相対パスが再解決され、
        `output_dir/output_dir/test_logs/...`という二重ネストした
        場所に結果ファイルが書き出されてしまい、Python側
        （呼び出し時のカレントディレクトリ基準で読み取る）は
        見つけられなかった。output_dirを絶対パス化することで防ぐ。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "relative_subdir").mkdir()
            (root / "relative_subdir" / "MyApp.csproj").write_text("<Project />", encoding="utf-8")

            original_cwd = os.getcwd()
            os.chdir(root)
            try:
                relative_output_dir = Path("relative_subdir")

                def _fake_run(cmd, cwd, capture_output, text, timeout, env):
                    # dotnet testは --results-directory の値が相対パスなら
                    # 自身のcwd（=呼び出し時のcwd引数）基準で解決する。
                    results_dir_arg = cmd[cmd.index("--results-directory") + 1]
                    resolved_results_dir = Path(cwd) / results_dir_arg
                    resolved_results_dir.mkdir(parents=True, exist_ok=True)
                    logger_arg = cmd[cmd.index("--logger") + 1]
                    trx_filename = logger_arg.split("LogFileName=")[1]
                    (resolved_results_dir / trx_filename).write_text(_SAMPLE_TRX, encoding="utf-8")
                    return mock.Mock(stdout="", stderr="")

                with mock.patch.object(test_runner.subprocess, "run", side_effect=_fake_run):
                    result = test_runner.run_tests_and_save_log(relative_output_dir, label="final")
            finally:
                os.chdir(original_cwd)

            self.assertTrue(result["log_path"].is_absolute())
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["passed"], 1)
            self.assertEqual(result["failed"], 1)
            # 二重ネストしたディレクトリが作られていないこと
            self.assertFalse((root / "relative_subdir" / "relative_subdir").exists())

    def test_prefers_pytest_when_no_csproj(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "tests").mkdir()
            fake_proc = mock.Mock(stdout="", stderr="")
            with mock.patch.object(test_runner.subprocess, "run", return_value=fake_proc) as fake_run:
                result = test_runner.run_tests_and_save_log(output_dir)

            self.assertEqual(result["project_type"], "pytest")
            argv = fake_run.call_args.args[0]
            self.assertIn("pytest", argv)


if __name__ == "__main__":
    unittest.main()
