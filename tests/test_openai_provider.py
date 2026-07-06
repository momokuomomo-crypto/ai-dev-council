import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council import openai_provider

_SAMPLE_DESIGN = {
    "overview": "顧客管理システム",
    "requirements": ["顧客のCRUD操作ができる"],
    "architecture": "Flask + SQLite",
    "file_plan": [{"path": "app.py", "purpose": "エントリポイント"}],
    "test_plan": "pytestで単体テストを行う",
    "open_questions": [],
}

_SAMPLE_REVIEW = {"approved": True, "issues": [], "suggestions": []}


class _FakeMessage:
    def __init__(self, content, refusal=None):
        self.content = content
        self.refusal = refusal


class _FakeChoice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, message, finish_reason="stop"):
        self.choices = [_FakeChoice(message, finish_reason)]


def _fake_client_returning(payload):
    fake_client = mock.MagicMock()
    fake_client.chat.completions.create.return_value = _FakeResponse(
        _FakeMessage(json.dumps(payload, ensure_ascii=False))
    )
    return fake_client


class TestGenerateDesign(unittest.TestCase):
    def test_returns_parsed_content_from_response(self):
        fake_client = _fake_client_returning(_SAMPLE_DESIGN)

        with mock.patch.object(openai_provider, "OpenAI", return_value=fake_client):
            with mock.patch.object(
                openai_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                result = openai_provider.generate_design("顧客管理システムを作りたい")

        self.assertEqual(result, _SAMPLE_DESIGN)

    def test_forces_json_schema_and_model_from_config(self):
        fake_client = _fake_client_returning(_SAMPLE_DESIGN)

        with mock.patch.object(openai_provider, "OpenAI", return_value=fake_client):
            with mock.patch.object(
                openai_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                openai_provider.generate_design("タスク")

        _, kwargs = fake_client.chat.completions.create.call_args
        self.assertEqual(kwargs["model"], "gpt-4.1")
        self.assertEqual(kwargs["response_format"]["json_schema"]["name"], "submit_design")

    def test_includes_context_when_provided(self):
        fake_client = _fake_client_returning(_SAMPLE_DESIGN)

        with mock.patch.object(openai_provider, "OpenAI", return_value=fake_client):
            with mock.patch.object(
                openai_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                openai_provider.generate_design("タスク", context="参考情報の中身")

        _, kwargs = fake_client.chat.completions.create.call_args
        self.assertIn("参考情報の中身", kwargs["messages"][1]["content"])

    def test_raises_when_model_refuses(self):
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _FakeResponse(
            _FakeMessage(content=None, refusal="対応できません")
        )

        with mock.patch.object(openai_provider, "OpenAI", return_value=fake_client):
            with mock.patch.object(
                openai_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                with self.assertRaises(RuntimeError):
                    openai_provider.generate_design("タスク")

    def test_raises_clear_error_when_truncated_by_max_tokens(self):
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = _FakeResponse(
            _FakeMessage(content="{incomplete"), finish_reason="length"
        )

        with mock.patch.object(openai_provider, "OpenAI", return_value=fake_client):
            with mock.patch.object(
                openai_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                with self.assertRaisesRegex(RuntimeError, "max_tokens"):
                    openai_provider.generate_design("タスク")


class TestGenerateDesignRevision(unittest.TestCase):
    def test_includes_previous_design_and_feedback(self):
        fake_client = _fake_client_returning(_SAMPLE_DESIGN)

        with mock.patch.object(openai_provider, "OpenAI", return_value=fake_client):
            with mock.patch.object(
                openai_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                result = openai_provider.generate_design_revision(
                    "タスク",
                    _SAMPLE_DESIGN,
                    {"claude": {"approved": False, "issues": [], "suggestions": []}},
                )

        self.assertEqual(result, _SAMPLE_DESIGN)
        _, kwargs = fake_client.chat.completions.create.call_args
        user_content = kwargs["messages"][1]["content"]
        self.assertIn("claude", user_content)


class TestGenerateCodeReview(unittest.TestCase):
    def test_returns_parsed_review(self):
        fake_client = _fake_client_returning(_SAMPLE_REVIEW)

        with mock.patch.object(openai_provider, "OpenAI", return_value=fake_client):
            with mock.patch.object(
                openai_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                result = openai_provider.generate_code_review(
                    "タスク", _SAMPLE_DESIGN, "### app.py\n```\nprint('hi')\n```"
                )

        self.assertEqual(result, _SAMPLE_REVIEW)
        _, kwargs = fake_client.chat.completions.create.call_args
        self.assertIn("app.py", kwargs["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
