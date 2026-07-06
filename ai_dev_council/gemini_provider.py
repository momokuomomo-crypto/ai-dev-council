"""
設計.md の共通インターフェースを、Gemini APIで実装する。

GeminiのJSON Schema強制出力機能（response_mime_type: application/json、
response_json_schema）を用いる。

Geminiは設計レビュー（generate_design_review）と実装レビュー
（generate_code_review）の両方を担当する（設計・実装のいずれも
Gemini自身は書いていないため、両方のレビュアーとして有効）。
"""

import json
from pathlib import Path
from typing import Dict

import yaml
from google import genai
from google.genai import types

from . import llm_config
from .schema_repair import repair_stuffed_json

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

_REVIEW_REQUIRED_KEYS = ["approved", "issues", "suggestions"]

_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
                    "location": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["severity", "location", "description"],
            },
        },
        "suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": _REVIEW_REQUIRED_KEYS,
}

_DESIGN_REVIEW_SYSTEM_PROMPT = """\
あなたはソフトウェア設計のレビューを行うAIです。与えられたタスク説明と
設計ドキュメントを照らし合わせ、レビュー結果を構造化して提出してください。

以下の制約を必ず守ってください。

* 設計がタスクの要件を満たしているか、file_planに漏れがないかを確認すること。
* 重大な欠陥・矛盾があればseverityをblockerまたはmajorとして報告すること。
* 与えられた情報以外の事実を勝手に創作しないこと。
* 指定されたJSON Schemaの構造で回答すること。
"""

_CODE_REVIEW_SYSTEM_PROMPT = """\
あなたはソフトウェアのコードレビューを行うAIです。設計ドキュメントと、
実際に生成されたコード一式を照らし合わせ、レビュー結果を構造化して
提出してください。

以下の制約を必ず守ってください。

* 設計ドキュメントの要件・ファイル計画に対して、実装が欠落・不整合を
  起こしていないか確認すること。
* 明らかなバグ・セキュリティ上の問題があれば、severityをblockerまたは
  majorとして報告すること。
* 与えられたコード以外の内容を勝手に推測して評価しないこと。
* 指定されたJSON Schemaの構造で回答すること。
"""


def _load_model_config() -> Dict[str, object]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config["gemini"]


def _call_structured(system_prompt: str, user_message: str) -> Dict[str, object]:
    config = _load_model_config()
    client = genai.Client(api_key=llm_config.get_api_key("gemini"))

    response = client.models.generate_content(
        model=config["model"],
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=config.get("max_output_tokens", 4096),
            response_mime_type="application/json",
            response_json_schema=_REVIEW_SCHEMA,
        ),
    )

    finish_reason = response.candidates[0].finish_reason
    if finish_reason == "MAX_TOKENS":
        raise RuntimeError(
            "出力がmax_output_tokens上限に達し、構造化出力が不完全な状態で打ち切られました。"
            "config.yamlのgemini.max_output_tokensを増やしてください。"
        )
    if finish_reason != "STOP":
        raise RuntimeError(f"Geminiが正常に応答を完了しませんでした（finish_reason={finish_reason}）")

    return json.loads(response.text)


def _build_design_review_user_message(task: str, design: Dict[str, object]) -> str:
    return (
        f"タスク：{task}\n\n"
        "以下は設計ドキュメントです。\n\n"
        f"```json\n{json.dumps(design, ensure_ascii=False, indent=2)}\n```"
    )


def generate_design_review(task: str, design: Dict[str, object]) -> Dict[str, object]:
    """Stage 設計レビュー: 設計ドキュメントをレビューする。"""
    data = _call_structured(
        _DESIGN_REVIEW_SYSTEM_PROMPT, _build_design_review_user_message(task, design)
    )
    return repair_stuffed_json(data, _REVIEW_REQUIRED_KEYS)


def _build_code_review_user_message(task: str, design: Dict[str, object], code_context: str) -> str:
    return (
        f"タスク：{task}\n\n"
        "以下は設計ドキュメントです。\n\n"
        f"```json\n{json.dumps(design, ensure_ascii=False, indent=2)}\n```\n\n"
        "以下は生成されたコード一式です。\n\n"
        f"{code_context}"
    )


def generate_code_review(task: str, design: Dict[str, object], code_context: str) -> Dict[str, object]:
    """Stage 実装レビュー: 生成されたコードをレビューする。"""
    data = _call_structured(
        _CODE_REVIEW_SYSTEM_PROMPT, _build_code_review_user_message(task, design, code_context)
    )
    return repair_stuffed_json(data, _REVIEW_REQUIRED_KEYS)
