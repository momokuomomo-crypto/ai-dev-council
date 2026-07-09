import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council import pipeline

_TASK = "webで動く顧客管理システムを作る"

_FAKE_TEST_RUN = {
    "log_path": "test_logs/fake_pytest_log.txt",
    "csv_path": "test_logs/fake_test_results.csv",
    "returncode": 0,
    "total": 0,
    "passed": 0,
    "failed": 0,
}

_SAMPLE_DESIGN = {
    "overview": "顧客管理システム",
    "requirements": ["顧客のCRUD操作ができる"],
    "architecture": "Flask + SQLite",
    "file_plan": [{"path": "app.py", "purpose": "エントリポイント"}],
    "test_plan": "pytestで単体テストを行う",
    "open_questions": [],
}


def _fake_review(approved):
    return {"approved": approved, "issues": [], "suggestions": []}


class TestRunDesignReview(unittest.TestCase):
    def test_stops_after_one_round_when_all_approved(self):
        fake_funcs = {
            "claude": mock.Mock(return_value=_fake_review(True)),
            "gemini": mock.Mock(return_value=_fake_review(True)),
        }

        with mock.patch.dict(pipeline._DESIGN_REVIEW_FUNCS, fake_funcs):
            with mock.patch.object(pipeline.openai_provider, "generate_design_revision") as fake_revise:
                final_design, rounds = pipeline.run_design_review(_TASK, _SAMPLE_DESIGN, max_rounds=5)

        self.assertEqual(len(rounds), 1)
        fake_revise.assert_not_called()
        self.assertEqual(final_design, _SAMPLE_DESIGN)

    def test_revises_and_respects_max_rounds_when_not_approved(self):
        fake_funcs = {
            "claude": mock.Mock(return_value=_fake_review(False)),
            "gemini": mock.Mock(return_value=_fake_review(False)),
        }
        revised_design = dict(_SAMPLE_DESIGN, overview="改訂版")

        with mock.patch.dict(pipeline._DESIGN_REVIEW_FUNCS, fake_funcs):
            with mock.patch.object(
                pipeline.openai_provider, "generate_design_revision", return_value=revised_design
            ) as fake_revise:
                final_design, rounds = pipeline.run_design_review(_TASK, _SAMPLE_DESIGN, max_rounds=3)

        self.assertEqual(len(rounds), 3)
        # 改訂はラウンド1→2、2→3の間で2回発生する（3回目以降は改訂しない）
        self.assertEqual(fake_revise.call_count, 2)
        self.assertEqual(final_design, revised_design)

    def test_on_round_called_with_round_number(self):
        fake_funcs = {
            "claude": mock.Mock(return_value=_fake_review(True)),
            "gemini": mock.Mock(return_value=_fake_review(True)),
        }
        seen = []

        with mock.patch.dict(pipeline._DESIGN_REVIEW_FUNCS, fake_funcs):
            pipeline.run_design_review(
                _TASK, _SAMPLE_DESIGN, max_rounds=1, on_round=lambda n, fb: seen.append(n)
            )

        self.assertEqual(seen, [1])


class TestRunCodeReview(unittest.TestCase):
    def test_stops_after_one_round_when_all_approved(self):
        fake_funcs = {
            "gemini": mock.Mock(return_value=_fake_review(True)),
            "openai": mock.Mock(return_value=_fake_review(True)),
        }

        with mock.patch.dict(pipeline._CODE_REVIEW_FUNCS, fake_funcs):
            with mock.patch.object(pipeline.context_builder, "build_code_context", return_value=""):
                with mock.patch.object(pipeline.claude_coding_agent, "run_implementation_fix") as fake_fix:
                    last_fix, rounds = pipeline.run_code_review(
                        _TASK, _SAMPLE_DESIGN, Path("/tmp/out"), {}, max_rounds=3
                    )

        self.assertEqual(len(rounds), 1)
        fake_fix.assert_not_called()
        self.assertIsNone(last_fix)

    def test_calls_fix_when_not_approved(self):
        fake_funcs = {
            "gemini": mock.Mock(return_value=_fake_review(False)),
            "openai": mock.Mock(return_value=_fake_review(True)),
        }
        fake_fix_result = {"success": True, "subtype": "success", "result_text": "修正完了"}

        with mock.patch.dict(pipeline._CODE_REVIEW_FUNCS, fake_funcs):
            with mock.patch.object(pipeline.context_builder, "build_code_context", return_value=""):
                with mock.patch.object(
                    pipeline.claude_coding_agent, "run_implementation_fix", return_value=fake_fix_result
                ) as fake_fix:
                    last_fix, rounds = pipeline.run_code_review(
                        _TASK, _SAMPLE_DESIGN, Path("/tmp/out"), {}, max_rounds=2
                    )

        self.assertEqual(len(rounds), 2)
        fake_fix.assert_called_once()
        self.assertEqual(last_fix, fake_fix_result)


class TestEstimateFixedCallCount(unittest.TestCase):
    def test_matches_expected_formula(self):
        # design(1) + design_review(2*2=4) + design_revision(2-1=1) + code_review(2*3=6) = 12
        self.assertEqual(pipeline._estimate_fixed_call_count(max_rounds=2, max_implementation_rounds=3), 12)

    def test_single_round_has_no_revision_calls(self):
        # design(1) + design_review(2) + design_revision(0) + code_review(2) = 5
        self.assertEqual(pipeline._estimate_fixed_call_count(max_rounds=1, max_implementation_rounds=1), 5)


class TestConfirmFunctions(unittest.TestCase):
    def test_confirm_api_calls_empty_input_means_yes(self):
        with mock.patch("builtins.input", return_value=""):
            self.assertTrue(pipeline.confirm_api_calls("確認"))

    def test_confirm_api_calls_n_means_no(self):
        with mock.patch("builtins.input", return_value="n"):
            self.assertFalse(pipeline.confirm_api_calls("確認"))

    def test_confirm_agent_run_shows_output_dir_in_prompt(self):
        captured = {}

        def _fake_input(prompt):
            captured["prompt"] = prompt
            return "y"

        output_dir = Path("some_output_dir")
        with mock.patch("builtins.input", side_effect=_fake_input):
            result = pipeline.confirm_agent_run(output_dir, max_turns=40)

        self.assertTrue(result)
        self.assertIn(str(output_dir), captured["prompt"])
        self.assertIn("40", captured["prompt"])


class TestRunPipeline(unittest.TestCase):
    def test_orchestrates_all_stages_and_creates_issue(self):
        agent_result = {"success": True, "subtype": "success", "result_text": "OK", "total_cost_usd": 0.1}

        with mock.patch.object(pipeline, "_load_config", return_value={
            "github_repo": "momokuomomo-crypto/ai-dev-council",
            "claude_agent": {"max_turns": 10},
        }):
            with mock.patch.object(pipeline, "run_design_stage", return_value=_SAMPLE_DESIGN):
                with mock.patch.object(
                    pipeline, "run_design_review", return_value=(_SAMPLE_DESIGN, [{"claude": _fake_review(True)}])
                ):
                    with mock.patch.object(pipeline, "confirm_agent_run", return_value=True):
                        with mock.patch.object(
                            pipeline, "run_implementation", return_value=agent_result
                        ) as fake_impl:
                            with mock.patch.object(
                                pipeline, "run_code_review", return_value=(None, [{"gemini": _fake_review(True)}])
                            ):
                                with mock.patch.object(
                                    pipeline.test_runner,
                                    "run_tests_and_save_log",
                                    return_value=_FAKE_TEST_RUN,
                                ):
                                    with mock.patch.object(
                                        pipeline.github_issue,
                                        "create_run_issue",
                                        return_value="https://github.com/x/y/issues/1",
                                    ) as fake_issue:
                                        result = pipeline.run_pipeline(
                                            _TASK, Path("/tmp/out"), verbose=False
                                        )

        fake_impl.assert_called_once()
        fake_issue.assert_called_once()
        self.assertEqual(result["issue_url"], "https://github.com/x/y/issues/1")
        self.assertEqual(result["agent_result"], agent_result)

    def test_raises_when_agent_run_declined(self):
        with mock.patch.object(pipeline, "_load_config", return_value={
            "github_repo": "momokuomomo-crypto/ai-dev-council",
            "claude_agent": {},
        }):
            with mock.patch.object(pipeline, "run_design_stage", return_value=_SAMPLE_DESIGN):
                with mock.patch.object(
                    pipeline, "run_design_review", return_value=(_SAMPLE_DESIGN, [])
                ):
                    with mock.patch.object(pipeline, "confirm_agent_run", return_value=False):
                        with self.assertRaises(RuntimeError):
                            pipeline.run_pipeline(_TASK, Path("/tmp/out"), verbose=False)

    def test_last_fix_result_overrides_agent_result(self):
        initial_result = {"success": True, "subtype": "success", "result_text": "初回実装"}
        fix_result = {"success": True, "subtype": "success", "result_text": "修正後"}

        with mock.patch.object(pipeline, "_load_config", return_value={
            "github_repo": "momokuomomo-crypto/ai-dev-council",
            "claude_agent": {},
        }):
            with mock.patch.object(pipeline, "run_design_stage", return_value=_SAMPLE_DESIGN):
                with mock.patch.object(
                    pipeline, "run_design_review", return_value=(_SAMPLE_DESIGN, [])
                ):
                    with mock.patch.object(pipeline, "confirm_agent_run", return_value=True):
                        with mock.patch.object(pipeline, "run_implementation", return_value=initial_result):
                            with mock.patch.object(
                                pipeline, "run_code_review", return_value=(fix_result, [])
                            ):
                                with mock.patch.object(
                                    pipeline.test_runner,
                                    "run_tests_and_save_log",
                                    return_value=_FAKE_TEST_RUN,
                                ):
                                    with mock.patch.object(
                                        pipeline.github_issue, "create_run_issue", return_value="url"
                                    ):
                                        result = pipeline.run_pipeline(_TASK, Path("/tmp/out"), verbose=False)

        self.assertEqual(result["agent_result"], fix_result)


if __name__ == "__main__":
    unittest.main()
