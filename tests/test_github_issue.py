import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council import github_issue

_SAMPLE_DESIGN = {
    "overview": "顧客管理システム",
    "requirements": ["顧客のCRUD操作ができる"],
    "architecture": "Flask + SQLite",
    "file_plan": [{"path": "app.py", "purpose": "エントリポイント"}],
    "test_plan": "pytestで単体テストを行う",
    "open_questions": [],
}

_SAMPLE_REVIEW_ROUND = [{"claude": {"approved": True, "issues": [], "suggestions": []}}]

_SAMPLE_AGENT_RESULT = {
    "success": True,
    "subtype": "success",
    "result_text": "全テスト成功",
    "total_cost_usd": 0.12,
}


class TestCreateRunIssue(unittest.TestCase):
    def test_calls_gh_issue_create_without_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "app.py").write_text("print('hi')", encoding="utf-8")

            fake_result = mock.Mock(stdout="https://github.com/momokuomomo-crypto/ai-dev-council/issues/1\n")
            with mock.patch.object(github_issue, "_has_git_identity", return_value=True), \
                 mock.patch.object(github_issue, "_has_gh_auth", return_value=True), \
                 mock.patch.object(github_issue.subprocess, "run", return_value=fake_result) as fake_run:
                url = github_issue.create_run_issue(
                    repo="momokuomomo-crypto/ai-dev-council",
                    task="顧客管理システムを作る",
                    design=_SAMPLE_DESIGN,
                    design_review_rounds=_SAMPLE_REVIEW_ROUND,
                    agent_result=_SAMPLE_AGENT_RESULT,
                    code_review_rounds=_SAMPLE_REVIEW_ROUND,
                    output_dir=output_dir,
                )

        self.assertEqual(url, "https://github.com/momokuomomo-crypto/ai-dev-council/issues/1")
        args, kwargs = fake_run.call_args
        argv = args[0]
        self.assertEqual(argv[:3], ["gh", "issue", "create"])
        self.assertIn("--repo", argv)
        self.assertIn("momokuomomo-crypto/ai-dev-council", argv)
        # closeするサブコマンドは呼ばれない
        self.assertNotIn("close", argv)

    def test_includes_test_run_paths_in_body_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            fake_result = mock.Mock(stdout="https://github.com/momokuomomo-crypto/ai-dev-council/issues/2\n")
            with mock.patch.object(github_issue, "_has_git_identity", return_value=True), \
                 mock.patch.object(github_issue, "_has_gh_auth", return_value=True), \
                 mock.patch.object(github_issue.subprocess, "run", return_value=fake_result) as fake_run:
                github_issue.create_run_issue(
                    repo="momokuomomo-crypto/ai-dev-council",
                    task="顧客管理システムを作る",
                    design=_SAMPLE_DESIGN,
                    design_review_rounds=_SAMPLE_REVIEW_ROUND,
                    agent_result=_SAMPLE_AGENT_RESULT,
                    code_review_rounds=_SAMPLE_REVIEW_ROUND,
                    output_dir=output_dir,
                    test_run_final={
                        "passed": 10,
                        "failed": 1,
                        "total": 11,
                        "log_path": "test_logs/x_pytest_log.txt",
                        "csv_path": "test_logs/x_test_results.csv",
                    },
                )

        body = fake_run.call_args.args[0][fake_run.call_args.args[0].index("--body") + 1]
        self.assertIn("10件成功", body)
        self.assertIn("test_logs/x_test_results.csv", body)

    def test_assigns_issue_when_assignee_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            fake_result = mock.Mock(stdout="https://github.com/momokuomomo-crypto/ai-dev-council/issues/3\n")
            with mock.patch.object(github_issue, "_has_git_identity", return_value=True), \
                 mock.patch.object(github_issue, "_has_gh_auth", return_value=True), \
                 mock.patch.object(github_issue.subprocess, "run", return_value=fake_result) as fake_run:
                github_issue.create_run_issue(
                    repo="momokuomomo-crypto/ai-dev-council",
                    task="タスク",
                    design=_SAMPLE_DESIGN,
                    design_review_rounds=_SAMPLE_REVIEW_ROUND,
                    agent_result=_SAMPLE_AGENT_RESULT,
                    code_review_rounds=_SAMPLE_REVIEW_ROUND,
                    output_dir=output_dir,
                    assignee="mokuo",
                )

        argv = fake_run.call_args.args[0]
        self.assertIn("--assignee", argv)
        self.assertEqual(argv[argv.index("--assignee") + 1], "mokuo")

    def test_does_not_assign_when_assignee_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            fake_result = mock.Mock(stdout="https://github.com/momokuomomo-crypto/ai-dev-council/issues/4\n")
            with mock.patch.object(github_issue, "_has_git_identity", return_value=True), \
                 mock.patch.object(github_issue, "_has_gh_auth", return_value=True), \
                 mock.patch.object(github_issue.subprocess, "run", return_value=fake_result) as fake_run:
                github_issue.create_run_issue(
                    repo="momokuomomo-crypto/ai-dev-council",
                    task="タスク",
                    design=_SAMPLE_DESIGN,
                    design_review_rounds=_SAMPLE_REVIEW_ROUND,
                    agent_result=_SAMPLE_AGENT_RESULT,
                    code_review_rounds=_SAMPLE_REVIEW_ROUND,
                    output_dir=output_dir,
                )

        argv = fake_run.call_args.args[0]
        self.assertNotIn("--assignee", argv)

    def test_falls_back_to_file_when_gh_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            with mock.patch.object(github_issue, "_has_git_identity", return_value=True), \
                 mock.patch.object(github_issue, "_has_gh_auth", return_value=True), \
                 mock.patch.object(
                     github_issue.subprocess,
                     "run",
                     side_effect=subprocess.CalledProcessError(1, ["gh"]),
                 ):
                with self.assertRaises(RuntimeError):
                    github_issue.create_run_issue(
                        repo="momokuomomo-crypto/ai-dev-council",
                        task="タスク",
                        design=_SAMPLE_DESIGN,
                        design_review_rounds=_SAMPLE_REVIEW_ROUND,
                        agent_result=_SAMPLE_AGENT_RESULT,
                        code_review_rounds=_SAMPLE_REVIEW_ROUND,
                        output_dir=output_dir,
                    )

            fallback_path = output_dir / "issue_body_fallback.md"
            self.assertTrue(fallback_path.exists())

    def test_skips_without_raising_when_git_identity_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            with mock.patch.object(github_issue, "_has_git_identity", return_value=False), \
                 mock.patch.object(github_issue, "_has_gh_auth", return_value=True), \
                 mock.patch.object(github_issue.subprocess, "run") as fake_run:
                url = github_issue.create_run_issue(
                    repo="momokuomomo-crypto/ai-dev-council",
                    task="タスク",
                    design=_SAMPLE_DESIGN,
                    design_review_rounds=_SAMPLE_REVIEW_ROUND,
                    agent_result=_SAMPLE_AGENT_RESULT,
                    code_review_rounds=_SAMPLE_REVIEW_ROUND,
                    output_dir=output_dir,
                )

            fake_run.assert_not_called()
            self.assertIsNone(url)
            self.assertTrue((output_dir / "issue_body_fallback.md").exists())

    def test_skips_without_raising_when_gh_not_authenticated(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            with mock.patch.object(github_issue, "_has_git_identity", return_value=True), \
                 mock.patch.object(github_issue, "_has_gh_auth", return_value=False), \
                 mock.patch.object(github_issue.subprocess, "run") as fake_run:
                url = github_issue.create_run_issue(
                    repo="momokuomomo-crypto/ai-dev-council",
                    task="タスク",
                    design=_SAMPLE_DESIGN,
                    design_review_rounds=_SAMPLE_REVIEW_ROUND,
                    agent_result=_SAMPLE_AGENT_RESULT,
                    code_review_rounds=_SAMPLE_REVIEW_ROUND,
                    output_dir=output_dir,
                )

            fake_run.assert_not_called()
            self.assertIsNone(url)
            self.assertTrue((output_dir / "issue_body_fallback.md").exists())


class TestHasGitIdentity(unittest.TestCase):
    def test_true_when_both_configured(self):
        fake_result = mock.Mock(returncode=0, stdout="momokuomomo-crypto\n")
        with mock.patch.object(github_issue.subprocess, "run", return_value=fake_result):
            self.assertTrue(github_issue._has_git_identity())

    def test_false_when_user_name_missing(self):
        def _fake_run(argv, **kwargs):
            if argv[-1] == "user.name":
                return mock.Mock(returncode=1, stdout="")
            return mock.Mock(returncode=0, stdout="a@example.com\n")

        with mock.patch.object(github_issue.subprocess, "run", side_effect=_fake_run):
            self.assertFalse(github_issue._has_git_identity())

    def test_false_when_git_not_installed(self):
        with mock.patch.object(github_issue.subprocess, "run", side_effect=FileNotFoundError):
            self.assertFalse(github_issue._has_git_identity())


class TestHasGhAuth(unittest.TestCase):
    def test_true_when_logged_in(self):
        with mock.patch.object(
            github_issue.subprocess, "run", return_value=mock.Mock(returncode=0)
        ):
            self.assertTrue(github_issue._has_gh_auth())

    def test_false_when_not_logged_in(self):
        with mock.patch.object(
            github_issue.subprocess, "run", return_value=mock.Mock(returncode=1)
        ):
            self.assertFalse(github_issue._has_gh_auth())

    def test_false_when_gh_not_installed(self):
        with mock.patch.object(github_issue.subprocess, "run", side_effect=FileNotFoundError):
            self.assertFalse(github_issue._has_gh_auth())


if __name__ == "__main__":
    unittest.main()
