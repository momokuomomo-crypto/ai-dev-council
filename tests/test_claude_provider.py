import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council import claude_provider

_SAMPLE_DESIGN = {
    "overview": "顧客管理システム",
    "requirements": ["顧客のCRUD操作ができる"],
    "architecture": "Flask + SQLite",
    "file_plan": [{"path": "app.py", "purpose": "エントリポイント"}],
    "test_plan": "pytestで単体テストを行う",
    "open_questions": [],
}

_SAMPLE_REVIEW = {"approved": True, "issues": [], "suggestions": []}


class _FakeToolUseBlock:
    def __init__(self, name, input_data):
        self.type = "tool_use"
        self.name = name
        self.input = input_data


class _FakeResponse:
    def __init__(self, content, stop_reason="tool_use"):
        self.content = content
        self.stop_reason = stop_reason


def _fake_client_returning_tool(tool_name, tool_input, stop_reason="tool_use"):
    fake_client = mock.MagicMock()
    fake_client.messages.create.return_value = _FakeResponse(
        [_FakeToolUseBlock(tool_name, tool_input)], stop_reason=stop_reason
    )
    return fake_client


class TestGenerateDesignReview(unittest.TestCase):
    def test_returns_parsed_content_from_response(self):
        fake_client = _fake_client_returning_tool("submit_review", _SAMPLE_REVIEW)

        with mock.patch.object(claude_provider.anthropic, "Anthropic", return_value=fake_client):
            with mock.patch.object(
                claude_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                result = claude_provider.generate_design_review("タスク", _SAMPLE_DESIGN)

        self.assertEqual(result, _SAMPLE_REVIEW)

    def test_forces_tool_use_and_model_from_config(self):
        fake_client = _fake_client_returning_tool("submit_review", _SAMPLE_REVIEW)

        with mock.patch.object(claude_provider.anthropic, "Anthropic", return_value=fake_client):
            with mock.patch.object(
                claude_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                claude_provider.generate_design_review("タスク", _SAMPLE_DESIGN)

        _, kwargs = fake_client.messages.create.call_args
        self.assertEqual(kwargs["model"], "claude-sonnet-5")
        self.assertEqual(kwargs["tool_choice"], {"type": "tool", "name": "submit_review"})

    def test_raises_clear_error_when_truncated_by_max_tokens(self):
        fake_client = _fake_client_returning_tool(
            "submit_review", _SAMPLE_REVIEW, stop_reason="max_tokens"
        )

        with mock.patch.object(claude_provider.anthropic, "Anthropic", return_value=fake_client):
            with mock.patch.object(
                claude_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                with self.assertRaisesRegex(RuntimeError, "max_tokens"):
                    claude_provider.generate_design_review("タスク", _SAMPLE_DESIGN)

    def test_raises_when_tool_not_called(self):
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = _FakeResponse([], stop_reason="end_turn")

        with mock.patch.object(claude_provider.anthropic, "Anthropic", return_value=fake_client):
            with mock.patch.object(
                claude_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                with self.assertRaises(RuntimeError):
                    claude_provider.generate_design_review("タスク", _SAMPLE_DESIGN)


if __name__ == "__main__":
    unittest.main()
