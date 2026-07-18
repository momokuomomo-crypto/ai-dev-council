import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dev_updater import updater

_INSTRUCTION = "横断価格比較機能を追加する"

_FAKE_TEST_RUN = {
    "log_path": "test_logs/fake_pytest_log.txt",
    "csv_path": "test_logs/fake_test_results.csv",
    "returncode": 0,
    "total": 3,
    "passed": 3,
    "failed": 0,
}


def _fake_agent_result(success=True):
    return {
        "success": success,
        "subtype": "success" if success else "sdk_error",
        "result_text": "更新しました",
        "total_cost_usd": 0.1,
        "usage": None,
        "transcript": "",
    }


def _fake_review(approved):
    return {"approved": approved, "issues": []}


def _make_app_dir(tmp):
    """既存アプリを模したディレクトリを作る。"""
    app_dir = Path(tmp) / "app"
    app_dir.mkdir()
    (app_dir / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (app_dir / "adapters").mkdir()
    (app_dir / "adapters" / "price_source.py").write_text("# adapter\n", encoding="utf-8")
    return app_dir


class TestCheckAppDir(unittest.TestCase):
    def test_raises_when_dir_missing(self):
        with self.assertRaisesRegex(RuntimeError, "存在しません"):
            updater.check_app_dir(Path("/no/such/dir"))

    def test_raises_when_dir_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "更新専用"):
                updater.check_app_dir(Path(tmp))

    def test_passes_when_source_files_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = _make_app_dir(tmp)
            updater.check_app_dir(app_dir)  # 例外が出ないこと


class TestBuildUpdatePrompt(unittest.TestCase):
    def test_prompt_declares_update_not_greenfield(self):
        prompt = updater.build_update_prompt(_INSTRUCTION, "設計内容", ["app.py"])
        self.assertIn("既存アプリケーションの更新タスク", prompt)
        self.assertIn("新規作成ではありません", prompt)
        self.assertIn("ゼロから作り直さない", prompt)

    def test_prompt_contains_instruction_design_and_files(self):
        prompt = updater.build_update_prompt(
            _INSTRUCTION, "設計ドキュメントの中身", ["app.py", "adapters/price_source.py"]
        )
        self.assertIn(_INSTRUCTION, prompt)
        self.assertIn("設計ドキュメントの中身", prompt)
        self.assertIn("- app.py", prompt)
        self.assertIn("- adapters/price_source.py", prompt)

    def test_prompt_omits_design_section_when_no_context(self):
        prompt = updater.build_update_prompt(_INSTRUCTION, "", ["app.py"])
        self.assertNotIn("# 設計ドキュメント", prompt)


class TestBuildPseudoDesign(unittest.TestCase):
    def test_contains_instruction_and_update_framing(self):
        design = updater.build_pseudo_design(_INSTRUCTION, "設計本文")
        self.assertIn(_INSTRUCTION, design["overview"])
        self.assertIn("差分更新", design["overview"])
        self.assertEqual(design["design_document"], "設計本文")

    def test_truncates_long_design_context(self):
        long_text = "あ" * (updater._MAX_DESIGN_CONTEXT_CHARS + 100)
        design = updater.build_pseudo_design(_INSTRUCTION, long_text)
        self.assertIn("省略", design["design_document"])
        self.assertLess(len(design["design_document"]), len(long_text))


class TestRunUpdate(unittest.TestCase):
    def test_runs_agent_tests_and_review_with_early_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = _make_app_dir(tmp)
            agent_runner = mock.Mock(return_value=_fake_agent_result())
            fix_runner = mock.Mock()
            review_funcs = {
                "gemini": mock.Mock(return_value=_fake_review(True)),
                "openai": mock.Mock(return_value=_fake_review(True)),
            }
            test_fn = mock.Mock(return_value=dict(_FAKE_TEST_RUN))

            result = updater.run_update(
                app_dir,
                _INSTRUCTION,
                design_context="設計",
                max_implementation_rounds=3,
                verbose=False,
                agent_runner=agent_runner,
                fix_runner=fix_runner,
                review_funcs=review_funcs,
                test_fn=test_fn,
            )

            agent_runner.assert_called_once()
            # 全員承認なのでラウンド1で早期終了、修正は走らない
            self.assertEqual(len(result["review_rounds"]), 1)
            fix_runner.assert_not_called()
            # テストはupdateとupdate_finalの2回
            self.assertEqual(test_fn.call_count, 2)
            labels = [c.kwargs.get("label") for c in test_fn.call_args_list]
            self.assertEqual(labels, ["update", "update_final"])

    def test_fix_called_when_review_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = _make_app_dir(tmp)
            fix_runner = mock.Mock(return_value=_fake_agent_result())
            review_funcs = {
                "gemini": mock.Mock(return_value=_fake_review(False)),
                "openai": mock.Mock(return_value=_fake_review(True)),
            }

            result = updater.run_update(
                app_dir,
                _INSTRUCTION,
                max_implementation_rounds=2,
                verbose=False,
                agent_runner=mock.Mock(return_value=_fake_agent_result()),
                fix_runner=fix_runner,
                review_funcs=review_funcs,
                test_fn=mock.Mock(return_value=dict(_FAKE_TEST_RUN)),
            )

            fix_runner.assert_called_once()
            self.assertEqual(len(result["review_rounds"]), 2)
            # 最後の修正結果がagent_resultとして採用される
            self.assertEqual(result["agent_result"], fix_runner.return_value)

    def test_no_review_skips_review_funcs(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = _make_app_dir(tmp)
            review_funcs = {
                "gemini": mock.Mock(),
                "openai": mock.Mock(),
            }

            result = updater.run_update(
                app_dir,
                _INSTRUCTION,
                run_review=False,
                verbose=False,
                agent_runner=mock.Mock(return_value=_fake_agent_result()),
                fix_runner=mock.Mock(),
                review_funcs=review_funcs,
                test_fn=mock.Mock(return_value=dict(_FAKE_TEST_RUN)),
            )

            for func in review_funcs.values():
                func.assert_not_called()
            self.assertEqual(result["review_rounds"], [])

    def test_agent_prompt_includes_existing_file_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = _make_app_dir(tmp)
            agent_runner = mock.Mock(return_value=_fake_agent_result())

            updater.run_update(
                app_dir,
                _INSTRUCTION,
                run_review=False,
                verbose=False,
                agent_runner=agent_runner,
                test_fn=mock.Mock(return_value=dict(_FAKE_TEST_RUN)),
            )

            prompt = agent_runner.call_args.args[0]
            self.assertIn("adapters/price_source.py", prompt)

    def test_raises_for_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                updater.run_update(
                    Path(tmp),
                    _INSTRUCTION,
                    verbose=False,
                    agent_runner=mock.Mock(),
                    test_fn=mock.Mock(),
                )


class TestReportAndHistory(unittest.TestCase):
    def test_write_report_and_append_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = _make_app_dir(tmp)
            result = {"instruction": _INSTRUCTION, "agent_result": _fake_agent_result()}

            report_path = updater.write_report(result, app_dir, "20260718_1200")
            history_path = updater.append_history(
                app_dir, "20260718_1200", _INSTRUCTION, report_path
            )

            self.assertTrue(report_path.exists())
            data = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(data["instruction"], _INSTRUCTION)

            history = history_path.read_text(encoding="utf-8")
            self.assertIn("# 更新履歴", history)
            self.assertIn(_INSTRUCTION, history)
            self.assertIn("20260718_1200_update_report.json", history)

    def test_append_history_appends_without_duplicating_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = _make_app_dir(tmp)
            report = app_dir / "r.json"
            report.write_text("{}", encoding="utf-8")

            updater.append_history(app_dir, "20260718_1200", "1回目", report)
            updater.append_history(app_dir, "20260718_1300", "2回目", report)

            history = (app_dir / "更新履歴.md").read_text(encoding="utf-8")
            self.assertEqual(history.count("# 更新履歴"), 1)
            self.assertIn("1回目", history)
            self.assertIn("2回目", history)


class TestCombineContextFiles(unittest.TestCase):
    def test_single_file_returns_content_as_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text("設計A", encoding="utf-8")
            self.assertEqual(updater.combine_context_files([path]), "設計A")

    def test_multiple_files_joined_with_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "要件.md"
            b = Path(tmp) / "設計.md"
            a.write_text("要件本文", encoding="utf-8")
            b.write_text("設計本文", encoding="utf-8")
            combined = updater.combine_context_files([a, b])
            self.assertIn("設計ドキュメント: 要件.md", combined)
            self.assertIn("要件本文", combined)
            self.assertIn("設計本文", combined)


class TestGitDirtyFiles(unittest.TestCase):
    def test_returns_none_when_git_fails(self):
        with mock.patch.object(
            updater.subprocess, "run", side_effect=OSError("git not found")
        ):
            self.assertIsNone(updater.git_dirty_files(Path(".")))

    def test_returns_lines_when_dirty(self):
        fake_proc = mock.Mock(returncode=0, stdout=" M app.py\n?? new.py\n")
        with mock.patch.object(updater.subprocess, "run", return_value=fake_proc):
            dirty = updater.git_dirty_files(Path("."))
        self.assertEqual(len(dirty), 2)

    def test_returns_empty_when_clean(self):
        fake_proc = mock.Mock(returncode=0, stdout="")
        with mock.patch.object(updater.subprocess, "run", return_value=fake_proc):
            self.assertEqual(updater.git_dirty_files(Path(".")), [])


if __name__ == "__main__":
    unittest.main()
