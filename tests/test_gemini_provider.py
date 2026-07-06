import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council import gemini_provider

_SAMPLE_DESIGN = {
    "overview": "顧客管理システム",
    "requirements": ["顧客のCRUD操作ができる"],
    "architecture": "Flask + SQLite",
    "file_plan": [{"path": "app.py", "purpose": "エントリポイント"}],
    "test_plan": "pytestで単体テストを行う",
    "open_questions": [],
}

_SAMPLE_REVIEW = {"approved": True, "issues": [], "suggestions": []}


class _FakeCandidate:
    def __init__(self, finish_reason):
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, text, finish_reason="STOP"):
        self.text = text
        self.candidates = [_FakeCandidate(finish_reason)]


def _fake_client_returning(payload, finish_reason="STOP"):
    fake_client = mock.MagicMock()
    fake_client.models.generate_content.return_value = _FakeResponse(
        json.dumps(payload, ensure_ascii=False), finish_reason
    )
    return fake_client


class TestGenerateDesignReview(unittest.TestCase):
    def test_returns_parsed_content_from_response(self):
        fake_client = _fake_client_returning(_SAMPLE_REVIEW)

        with mock.patch.object(gemini_provider.genai, "Client", return_value=fake_client):
            with mock.patch.object(
                gemini_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                result = gemini_provider.generate_design_review("タスク", _SAMPLE_DESIGN)

        self.assertEqual(result, _SAMPLE_REVIEW)

    def test_forces_json_schema_and_model_from_config(self):
        fake_client = _fake_client_returning(_SAMPLE_REVIEW)

        with mock.patch.object(gemini_provider.genai, "Client", return_value=fake_client):
            with mock.patch.object(
                gemini_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                gemini_provider.generate_design_review("タスク", _SAMPLE_DESIGN)

        _, kwargs = fake_client.models.generate_content.call_args
        self.assertEqual(kwargs["model"], "gemini-2.5-flash")

    def test_raises_clear_error_when_truncated_by_max_tokens(self):
        fake_client = _fake_client_returning(_SAMPLE_REVIEW, finish_reason="MAX_TOKENS")

        with mock.patch.object(gemini_provider.genai, "Client", return_value=fake_client):
            with mock.patch.object(
                gemini_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                with self.assertRaisesRegex(RuntimeError, "max_output_tokens"):
                    gemini_provider.generate_design_review("タスク", _SAMPLE_DESIGN)


class TestGenerateCodeReview(unittest.TestCase):
    def test_returns_parsed_content_from_response(self):
        fake_client = _fake_client_returning(_SAMPLE_REVIEW)

        with mock.patch.object(gemini_provider.genai, "Client", return_value=fake_client):
            with mock.patch.object(
                gemini_provider.llm_config, "get_api_key", return_value="dummy-key"
            ):
                result = gemini_provider.generate_code_review(
                    "タスク", _SAMPLE_DESIGN, "### app.py\n```\nprint('hi')\n```"
                )

        self.assertEqual(result, _SAMPLE_REVIEW)
        _, kwargs = fake_client.models.generate_content.call_args
        self.assertIn("app.py", kwargs["contents"])


if __name__ == "__main__":
    unittest.main()
