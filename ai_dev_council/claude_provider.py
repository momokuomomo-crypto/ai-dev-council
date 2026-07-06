"""
設計.md の共通インターフェースを、Claude APIで実装する。

Claude APIのTool Use機能を用い、構造化出力を強制する。

このモジュールはStage 設計レビュー（generate_design_review）のみを担当する。
Stage 実装（実際のコード生成・テスト実行）はClaude Agent SDKを用いる
別モジュール claude_coding_agent.py が担当し、本モジュールには含めない
（Messages APIでの単発呼び出しと、自律的にファイル操作・bash実行を行う
コーディングエージェントは、プラミングも実行時の性質も全く異なるため）。
"""

import json
from pathlib import Path
from typing import Dict

import anthropic
import yaml

from . import llm_config
from .schema_repair import repair_stuffed_json

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

_REVIEW_REQUIRED_KEYS = ["approved", "issues", "suggestions"]

_REVIEW_TOOL = {
    "name": "submit_review",
    "description": "設計ドキュメントに対するレビュー結果を構造化して提出する。",
    "input_schema": {
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
                },
            },
            "suggestions": {
                "type": "array",
                "description": "必須ではないが検討に値する改善提案",
                "items": {"type": "string"},
            },
        },
        "required": _REVIEW_REQUIRED_KEYS,
    },
}

_DESIGN_REVIEW_SYSTEM_PROMPT = """\
あなたはソフトウェア設計のレビューを行うAIです。与えられたタスク説明と
設計ドキュメントを照らし合わせ、レビュー結果を構造化して提出してください。

以下の制約を必ず守ってください。

* 設計がタスクの要件を満たしているか、file_planに漏れがないかを確認すること。
* 重大な欠陥・矛盾があればseverityをblockerまたはmajorとして報告すること。
* 与えられた情報以外の事実を勝手に創作しないこと。
* submit_review ツールを必ず呼び出し、指定された構造で回答すること。
"""


def _load_model_config() -> Dict[str, object]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config["claude"]


def _build_design_review_user_message(task: str, design: Dict[str, object]) -> str:
    return (
        f"タスク：{task}\n\n"
        "以下は設計ドキュメントです。\n\n"
        f"```json\n{json.dumps(design, ensure_ascii=False, indent=2)}\n```"
    )


def generate_design_review(task: str, design: Dict[str, object]) -> Dict[str, object]:
    """Stage 設計レビュー: 設計ドキュメントをレビューする。"""
    config = _load_model_config()
    client = anthropic.Anthropic(api_key=llm_config.get_api_key("anthropic"))

    response = client.messages.create(
        model=config["model"],
        max_tokens=config.get("max_tokens", 4096),
        system=_DESIGN_REVIEW_SYSTEM_PROMPT,
        tools=[_REVIEW_TOOL],
        tool_choice={"type": "tool", "name": "submit_review"},
        messages=[{"role": "user", "content": _build_design_review_user_message(task, design)}],
    )

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "出力がmax_tokens上限に達し、構造化出力が不完全な状態で打ち切られました。"
            "config.yamlのclaude.max_tokensを増やしてください。"
        )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review":
            return repair_stuffed_json(block.input, _REVIEW_REQUIRED_KEYS)

    raise RuntimeError("Claudeがsubmit_reviewツールを呼び出しませんでした。")
