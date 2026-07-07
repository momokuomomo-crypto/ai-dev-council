import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council import claude_coding_agent

_SAMPLE_DESIGN = {
    "overview": "顧客管理システム",
    "requirements": ["顧客のCRUD操作ができる"],
    "architecture": "Flask + SQLite",
    "file_plan": [{"path": "app.py", "purpose": "エントリポイント"}],
    "test_plan": "pytestで単体テストを行う",
    "open_questions": [],
}


class _FakeTextBlock:
    def __init__(self, text):
        self.text = text


class _FakeAssistantMessage:
    def __init__(self, texts):
        self.content = [_FakeTextBlock(t) for t in texts]


class _FakeResultMessage:
    def __init__(self, subtype="success", result="完了しました", total_cost_usd=0.05, usage=None):
        self.subtype = subtype
        self.result = result
        self.total_cost_usd = total_cost_usd
        self.usage = usage or {}


def _fake_query_factory(messages):
    async def _fake_query(prompt, options):
        for message in messages:
            yield message

    return _fake_query


class TestRunImplementation(unittest.TestCase):
    def test_returns_success_result_from_result_message(self):
        messages = [
            _FakeAssistantMessage(["ファイルを作成しています"]),
            _FakeResultMessage(subtype="success", result="全テスト成功"),
        ]

        with mock.patch.object(
            claude_coding_agent,
            "query",
            side_effect=_fake_query_factory(messages),
        ), mock.patch.object(
            claude_coding_agent, "AssistantMessage", _FakeAssistantMessage
        ), mock.patch.object(
            claude_coding_agent, "ResultMessage", _FakeResultMessage
        ), mock.patch.object(
            claude_coding_agent, "TextBlock", _FakeTextBlock
        ):
            with tempfile.TemporaryDirectory() as tmp:
                result = claude_coding_agent.run_implementation(
                    "顧客管理システムを作る", _SAMPLE_DESIGN, Path(tmp), {"max_turns": 10}
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["subtype"], "success")
        self.assertIn("ファイルを作成しています", result["transcript"])

    def test_sdk_error_returns_failed_result_instead_of_raising(self):
        # 実際の実行で確認された挙動：max_turns到達時、SDKはResultMessageではなく
        # ClaudeSDKError（ProcessError等）を送出する。これを捕まえて、
        # クラッシュさせずに失敗結果として返せることを検証する。
        async def _fake_query_raising(prompt, options):
            if False:
                yield None  # pragma: no cover (ジェネレータにするためのダミー)
            raise claude_coding_agent.ClaudeSDKError(
                "Claude Code returned an error result: Reached maximum number of turns (15)"
            )

        with mock.patch.object(claude_coding_agent, "query", side_effect=_fake_query_raising):
            with tempfile.TemporaryDirectory() as tmp:
                result = claude_coding_agent.run_implementation(
                    "タスク", _SAMPLE_DESIGN, Path(tmp), {"max_turns": 15}
                )

        self.assertFalse(result["success"])
        self.assertEqual(result["subtype"], "sdk_error")
        self.assertIn("Reached maximum number of turns", result["result_text"])

    def test_raises_when_no_result_message_returned(self):
        messages = [_FakeAssistantMessage(["途中経過"])]

        with mock.patch.object(
            claude_coding_agent,
            "query",
            side_effect=_fake_query_factory(messages),
        ), mock.patch.object(
            claude_coding_agent, "AssistantMessage", _FakeAssistantMessage
        ), mock.patch.object(
            claude_coding_agent, "ResultMessage", _FakeResultMessage
        ), mock.patch.object(
            claude_coding_agent, "TextBlock", _FakeTextBlock
        ):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(RuntimeError):
                    claude_coding_agent.run_implementation(
                        "タスク", _SAMPLE_DESIGN, Path(tmp), {"max_turns": 10}
                    )

    def test_creates_output_dir_if_missing(self):
        messages = [_FakeResultMessage(subtype="success", result="OK")]

        with mock.patch.object(
            claude_coding_agent,
            "query",
            side_effect=_fake_query_factory(messages),
        ), mock.patch.object(
            claude_coding_agent, "ResultMessage", _FakeResultMessage
        ):
            with tempfile.TemporaryDirectory() as tmp:
                nested = Path(tmp) / "nested" / "output"
                claude_coding_agent.run_implementation("タスク", _SAMPLE_DESIGN, nested, {})

                self.assertTrue(nested.exists())

    def test_non_success_subtype_does_not_raise(self):
        messages = [_FakeResultMessage(subtype="error_max_turns", result="途中で打ち切り")]

        with mock.patch.object(
            claude_coding_agent,
            "query",
            side_effect=_fake_query_factory(messages),
        ), mock.patch.object(
            claude_coding_agent, "ResultMessage", _FakeResultMessage
        ):
            with tempfile.TemporaryDirectory() as tmp:
                result = claude_coding_agent.run_implementation(
                    "タスク", _SAMPLE_DESIGN, Path(tmp), {}
                )

        self.assertFalse(result["success"])
        self.assertEqual(result["subtype"], "error_max_turns")


class TestRunImplementationFix(unittest.TestCase):
    def test_includes_review_feedback_in_prompt(self):
        messages = [_FakeResultMessage(subtype="success", result="修正完了")]
        captured_prompts = []

        async def _fake_query(prompt, options):
            captured_prompts.append(prompt)
            for message in messages:
                yield message

        with mock.patch.object(claude_coding_agent, "query", side_effect=_fake_query), mock.patch.object(
            claude_coding_agent, "ResultMessage", _FakeResultMessage
        ):
            with tempfile.TemporaryDirectory() as tmp:
                claude_coding_agent.run_implementation_fix(
                    "タスク",
                    _SAMPLE_DESIGN,
                    {"claude": {"approved": False, "issues": [
                        {"severity": "blocker", "location": "app.py", "description": "SQLインジェクションの恐れ"}
                    ], "suggestions": []}},
                    Path(tmp),
                    {},
                )

        self.assertIn("SQLインジェクション", captured_prompts[0])


if __name__ == "__main__":
    unittest.main()
