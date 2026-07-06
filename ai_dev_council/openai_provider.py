"""
設計.md の共通インターフェースを、OpenAI APIで実装する。

OpenAI APIのStructured Outputs機能（response_format: json_schema、strict）を
用いる。

Stage 設計（generate_design/generate_design_revision）と、Stage 実装レビュー
（generate_code_review）を担当する。設計を書いたOpenAI自身が実装レビューの
片方を担うのは問題ない（設計は書いたが実装コードそのものは書いていないため、
自分の成果物を自分でレビューすることにはならない）。
"""

import json
from pathlib import Path
from typing import Dict, List

import yaml
from openai import OpenAI

from . import llm_config
from .schema_repair import repair_stuffed_json

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

_DESIGN_REQUIRED_KEYS = [
    "overview",
    "requirements",
    "architecture",
    "file_plan",
    "test_plan",
    "open_questions",
]

_REVIEW_REQUIRED_KEYS = ["approved", "issues", "suggestions"]

# --- 設計ドキュメントのスキーマ（Stage 設計・設計レビュー・実装レビュー共通） ---

_DESIGN_SCHEMA = {
    "name": "submit_design",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "overview": {"type": "string", "description": "何を作るかの概要"},
            "requirements": {
                "type": "array",
                "items": {"type": "string"},
                "description": "機能要件・非機能要件の箇条書き",
            },
            "architecture": {
                "type": "string",
                "description": "全体構成・技術選定の説明（言語/フレームワーク/DB等）",
            },
            "file_plan": {
                "type": "array",
                "description": "作成予定のファイル一覧とその役割",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "purpose": {"type": "string"},
                    },
                    "required": ["path", "purpose"],
                    "additionalProperties": False,
                },
            },
            "test_plan": {
                "type": "string",
                "description": "テスト方針（フレームワーク、カバーすべきケースの概要）",
            },
            "open_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "未決定・要確認の論点",
            },
        },
        "required": _DESIGN_REQUIRED_KEYS,
        "additionalProperties": False,
    },
}

_REVIEW_SCHEMA = {
    "name": "submit_review",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean", "description": "承認するか"},
            "issues": {
                "type": "array",
                "description": "修正が必要な問題点",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
                        "location": {"type": "string", "description": "該当箇所（任意、無ければ空文字）"},
                        "description": {"type": "string"},
                    },
                    "required": ["severity", "location", "description"],
                    "additionalProperties": False,
                },
            },
            "suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "必須ではないが検討に値する改善提案",
            },
        },
        "required": _REVIEW_REQUIRED_KEYS,
        "additionalProperties": False,
    },
}

_DESIGN_SYSTEM_PROMPT = """\
あなたはソフトウェアの設計を行うAIです。与えられたタスク説明から、
実装に着手できるレベルの設計ドキュメントを作成してください。

以下の制約を必ず守ってください。

* 与えられたタスク説明・コンテキスト以外の事実を勝手に創作しないこと。
* file_planには、実際に作成すべきファイルのパスと役割を具体的に列挙すること。
* 未決定・不明な点はopen_questionsに正直に明記すること。
* 指定されたJSON Schemaの構造で回答すること。自由記述のみの回答は行わないこと。
"""

_DESIGN_REVISION_SYSTEM_PROMPT = """\
あなたはソフトウェアの設計を行うAIです。以前作成した設計ドキュメントに対する
レビュアーからの指摘を踏まえ、設計ドキュメントを改訂してください。

以下の制約を必ず守ってください。

* blocker・major指摘には必ず対応すること（対応できない場合はopen_questionsに
  理由とともに明記すること）。
* minor指摘・提案は必要に応じて反映すること。
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
    return config["openai"]


def _call_structured(system_prompt: str, user_message: str, schema: Dict[str, object]) -> Dict[str, object]:
    config = _load_model_config()
    client = OpenAI(api_key=llm_config.get_api_key("openai"))

    response = client.chat.completions.create(
        model=config["model"],
        max_tokens=config.get("max_tokens", 4096),
        response_format={"type": "json_schema", "json_schema": schema},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )

    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise RuntimeError(
            "出力がmax_tokens上限に達し、構造化出力が不完全な状態で打ち切られました。"
            "config.yamlのopenai.max_tokensを増やしてください。"
        )

    message = choice.message
    if message.refusal:
        raise RuntimeError(f"OpenAIが回答を拒否しました: {message.refusal}")

    return json.loads(message.content)


# --- Stage 設計 ---


def _build_design_user_message(task: str, context: str) -> str:
    message = f"以下のタスクについて設計ドキュメントを作成してください。\n\nタスク：{task}"
    if context:
        message += f"\n\n以下は参考情報です。\n\n{context}"
    return message


def generate_design(task: str, context: str = "") -> Dict[str, object]:
    """Stage 設計: タスク説明から設計ドキュメントを生成する。"""
    data = _call_structured(
        _DESIGN_SYSTEM_PROMPT, _build_design_user_message(task, context), _DESIGN_SCHEMA
    )
    return repair_stuffed_json(data, _DESIGN_REQUIRED_KEYS)


def _build_design_revision_user_message(
    task: str,
    previous_design: Dict[str, object],
    review_feedback: Dict[str, Dict[str, object]],
) -> str:
    feedback_text = "\n\n".join(
        f"### {reviewer}のレビュー\n```json\n{json.dumps(feedback, ensure_ascii=False, indent=2)}\n```"
        for reviewer, feedback in review_feedback.items()
    )
    return (
        f"タスク：{task}\n\n"
        "以下は以前作成した設計ドキュメントです。\n\n"
        f"```json\n{json.dumps(previous_design, ensure_ascii=False, indent=2)}\n```\n\n"
        "以下はレビュアーからの指摘です。\n\n"
        f"{feedback_text}"
    )


def generate_design_revision(
    task: str,
    previous_design: Dict[str, object],
    review_feedback: Dict[str, Dict[str, object]],
) -> Dict[str, object]:
    """Stage 設計レビュー: レビュー指摘を踏まえて設計ドキュメントを改訂する。"""
    data = _call_structured(
        _DESIGN_REVISION_SYSTEM_PROMPT,
        _build_design_revision_user_message(task, previous_design, review_feedback),
        _DESIGN_SCHEMA,
    )
    return repair_stuffed_json(data, _DESIGN_REQUIRED_KEYS)


# --- Stage 実装レビュー ---


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
        _CODE_REVIEW_SYSTEM_PROMPT,
        _build_code_review_user_message(task, design, code_context),
        _REVIEW_SCHEMA,
    )
    return repair_stuffed_json(data, _REVIEW_REQUIRED_KEYS)
