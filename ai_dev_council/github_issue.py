"""
1回のパイプライン実行を1つのGitHub issueとして記録する。

ai-council側の開発ワークフロー（ツール自体への変更をコミットで説明し、
issueをclose済みで残す運用）とは異なり、ここでのissueは「実行結果の
記録・成果物」であり、コード変更のトラッキングではないため、作成後も
OPENのまま残す（closeしない）。
"""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from . import context_builder

_TITLE_TASK_MAX_CHARS = 60


def _build_issue_title(task: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = task if len(task) <= _TITLE_TASK_MAX_CHARS else task[:_TITLE_TASK_MAX_CHARS] + "…"
    return f"[{timestamp}] {summary}"


def _build_review_rounds_text(rounds: List[Dict[str, Dict[str, object]]], label: str) -> str:
    if not rounds:
        return f"（{label}は実行されていません）"

    lines: List[str] = []
    for round_num, round_feedback in enumerate(rounds, start=1):
        lines.append(f"#### ラウンド{round_num}")
        for reviewer, feedback in round_feedback.items():
            approved = "承認" if feedback.get("approved") else "未承認"
            lines.append(f"- **{reviewer}**: {approved}")
            for issue in feedback.get("issues", []):
                lines.append(
                    f"  - [{issue.get('severity')}] {issue.get('location', '')}: "
                    f"{issue.get('description')}"
                )
            for suggestion in feedback.get("suggestions", []):
                lines.append(f"  - (提案) {suggestion}")
    return "\n".join(lines)


def _build_issue_body(
    task: str,
    design: Dict[str, object],
    design_review_rounds: List[Dict[str, Dict[str, object]]],
    agent_result: Dict[str, object],
    code_review_rounds: List[Dict[str, Dict[str, object]]],
    output_dir: Path,
) -> str:
    file_plan_text = "\n".join(
        f"- `{item['path']}`: {item['purpose']}" for item in design.get("file_plan", [])
    )
    generated_files = context_builder.iter_source_files(output_dir)
    generated_files_text = "\n".join(
        f"- `{p.relative_to(output_dir).as_posix()}`" for p in generated_files
    ) or "（ファイルが見つかりませんでした）"

    test_summary = context_builder.build_test_results_summary(agent_result)

    return f"""\
## タスク

{task}

## 最終設計ドキュメント

### 概要
{design.get('overview', '')}

### 要件
{chr(10).join(f"- {r}" for r in design.get('requirements', []))}

### アーキテクチャ
{design.get('architecture', '')}

### 作成予定ファイル
{file_plan_text}

### テスト方針
{design.get('test_plan', '')}

## 設計レビュー

{_build_review_rounds_text(design_review_rounds, "設計レビュー")}

## 実装結果

{test_summary}

- コスト: ${agent_result.get('total_cost_usd', '不明')}

## 実装レビュー

{_build_review_rounds_text(code_review_rounds, "実装レビュー")}

## 出力先ディレクトリ

`{output_dir}`

### 生成ファイル一覧

{generated_files_text}
"""


def create_run_issue(
    repo: str,
    task: str,
    design: Dict[str, object],
    design_review_rounds: List[Dict[str, Dict[str, object]]],
    agent_result: Dict[str, object],
    code_review_rounds: List[Dict[str, Dict[str, object]]],
    output_dir: Path,
) -> str:
    """
    `gh issue create`を実行し、作成されたissueのURLを返す。closeは行わない
    （このツールの実行記録として残す）。

    gh CLIの呼び出しに失敗した場合は、issue本文をoutput_dir配下にファイルとして
    書き出し、その旨を伝える例外を送出する（せっかくの実行記録を失わないため）。
    """
    title = _build_issue_title(task)
    body = _build_issue_body(
        task, design, design_review_rounds, agent_result, code_review_rounds, output_dir
    )

    try:
        result = subprocess.run(
            ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        fallback_path = output_dir / "issue_body_fallback.md"
        fallback_path.write_text(body, encoding="utf-8")
        raise RuntimeError(
            f"GitHub issueの作成に失敗しました（{e}）。"
            f"issue本文は {fallback_path} に保存しました。"
        ) from e

    return result.stdout.strip()
