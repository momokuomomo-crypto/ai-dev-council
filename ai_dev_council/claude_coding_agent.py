"""
Claude Agent SDK（claude_agent_sdk）を用いて、設計ドキュメントを実際の
コード＋テストとしてoutput_dirへ書き出す自律コーディングエージェント。

claude_provider.py（Messages APIでの単発・スキーマ強制の意見/レビュー生成）
とは根本的に異なるモジュールとして分離する。このモジュールはファイル書き込み・
bash実行を伴う、output_dirにスコープを限定した自律的・多ターンの実行であり、
固定回数のAPI呼び出しではなく、実行するまで費用・所要時間が確定しない。

pip installだけでは動かない点に注意（README参照）：claude_agent_sdkは
Claude Code CLI / Node.jsランタイムをサブプロセスとして起動する。
"""

import asyncio
from pathlib import Path
from typing import Dict, List, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)


def _build_options(output_dir: Path, agent_config: Dict[str, object]) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=str(output_dir),
        allowed_tools=["Read", "Write", "Edit", "Bash"],
        permission_mode=agent_config.get("permission_mode", "acceptEdits"),
        model=agent_config.get("model"),
        max_turns=agent_config.get("max_turns", 40),
    )


def _build_implementation_prompt(task: str, design: Dict[str, object]) -> str:
    file_plan_text = "\n".join(
        f"- {item['path']}: {item['purpose']}" for item in design.get("file_plan", [])
    )
    return (
        f"以下のタスクと設計ドキュメントに基づき、カレントディレクトリ（作業ディレクトリ）に"
        "実際のコードとテストを作成してください。\n\n"
        f"# タスク\n{task}\n\n"
        f"# 設計ドキュメント\n"
        f"## 概要\n{design.get('overview', '')}\n\n"
        f"## 要件\n"
        + "\n".join(f"- {r}" for r in design.get("requirements", []))
        + "\n\n"
        f"## アーキテクチャ\n{design.get('architecture', '')}\n\n"
        f"## 作成予定ファイル\n{file_plan_text}\n\n"
        f"## テスト方針\n{design.get('test_plan', '')}\n\n"
        "設計に沿ってファイルを作成し、テストを実行し、テストが通るまで"
        "（または明らかに実行不可能と判断できるまで）修正を繰り返してください。"
        "最終的に、何を作成したか・テスト結果はどうだったかを明確に報告してください。"
    )


def _build_fix_prompt(
    task: str,
    design: Dict[str, object],
    review_feedback: Dict[str, Dict[str, object]],
) -> str:
    issues_text = "\n\n".join(
        f"### {reviewer}の指摘\n"
        + "\n".join(
            f"- [{issue['severity']}] {issue.get('location', '')}: {issue['description']}"
            for issue in feedback.get("issues", [])
        )
        for reviewer, feedback in review_feedback.items()
    )
    return (
        "以前あなたが作業ディレクトリに作成したコードについて、レビューで"
        "以下の指摘がありました。既存のファイルは自分でReadして確認した上で、"
        "指摘された問題を修正し、テストを再実行してください。\n\n"
        f"# タスク\n{task}\n\n"
        f"# 設計ドキュメント概要\n{design.get('overview', '')}\n\n"
        f"# レビュー指摘\n{issues_text}\n\n"
        "blocker・majorの指摘には必ず対応してください。修正後のテスト結果を"
        "明確に報告してください。"
    )


async def _run_query(prompt: str, output_dir: Path, agent_config: Dict[str, object]) -> Dict[str, object]:
    """query()を実行し、ResultMessageとAssistantMessageのテキストを収集して返す。"""
    options = _build_options(output_dir, agent_config)
    transcript: List[str] = []
    result_message: Optional[ResultMessage] = None

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    transcript.append(block.text)
        elif isinstance(message, ResultMessage):
            result_message = message

    if result_message is None:
        raise RuntimeError("Claude Agent SDKからResultMessageが返されませんでした。")

    return {
        "success": result_message.subtype == "success",
        "subtype": result_message.subtype,
        "result_text": result_message.result,
        "total_cost_usd": result_message.total_cost_usd,
        "usage": result_message.usage,
        "transcript": "\n".join(transcript),
    }


def run_implementation(
    task: str,
    design: Dict[str, object],
    output_dir: Path,
    agent_config: Dict[str, object],
) -> Dict[str, object]:
    """Stage 実装: 設計ドキュメントに基づきoutput_dirへコード＋テストを書く。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt = _build_implementation_prompt(task, design)
    return asyncio.run(_run_query(prompt, output_dir, agent_config))


def run_implementation_fix(
    task: str,
    design: Dict[str, object],
    review_feedback: Dict[str, Dict[str, object]],
    output_dir: Path,
    agent_config: Dict[str, object],
) -> Dict[str, object]:
    """Stage 実装レビュー→修正: 実装レビューで指摘された問題を修正する。"""
    prompt = _build_fix_prompt(task, design, review_feedback)
    return asyncio.run(_run_query(prompt, output_dir, agent_config))
