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
from typing import Dict, List, Optional

from . import context_builder

_TITLE_TASK_MAX_CHARS = 60


def _has_git_identity() -> bool:
    """git commitユーザー情報（user.name/user.email）が設定されているか確認する。"""
    try:
        for key in ("user.name", "user.email"):
            result = subprocess.run(["git", "config", "--get", key], capture_output=True, text=True)
            if result.returncode != 0 or not result.stdout.strip():
                return False
        return True
    except FileNotFoundError:
        return False


def _has_gh_auth() -> bool:
    """`gh`コマンドでGitHubにログイン済みか確認する。"""
    try:
        result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


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


def _build_test_run_text(test_run_final: Optional[Dict[str, object]]) -> str:
    if not test_run_final:
        return "（テスト実行記録はありません）"
    return (
        f"- {test_run_final.get('passed', '不明')}件成功 / "
        f"{test_run_final.get('failed', '不明')}件失敗"
        f"（計{test_run_final.get('total', '不明')}件）\n"
        f"- 生ログ: `{test_run_final.get('log_path', '不明')}`\n"
        f"- テストケース単位の結果CSV: `{test_run_final.get('csv_path', '不明')}`"
    )


def _build_issue_body(
    task: str,
    design: Dict[str, object],
    design_review_rounds: List[Dict[str, Dict[str, object]]],
    agent_result: Dict[str, object],
    code_review_rounds: List[Dict[str, Dict[str, object]]],
    output_dir: Path,
    test_run_final: Optional[Dict[str, object]] = None,
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

### 実際のテスト実行結果（最終状態）

{_build_test_run_text(test_run_final)}

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
    test_run_final: Optional[Dict[str, object]] = None,
    assignee: Optional[str] = None,
) -> Optional[str]:
    """
    `gh issue create`を実行し、作成されたissueのURLを返す。closeは行わない
    （このツールの実行記録として残す）。

    assigneeを指定すると、作成したissueをそのGitHubユーザーへ自動アサイン
    する。パイプラインを実行した人と、その後のgit管理（レビュー・マージ等の
    判断）を行う人が別である運用を想定した設定（config.yamlの
    `issue_assignee`）。

    git のcommitter情報（user.name/user.email）が未設定、または
    `gh auth login`が未実施の場合は、GitHubアカウントを持たない人がこの
    ツールを使うケースを想定し、issue作成自体をスキップする（例外は送出
    せず、issue本文をoutput_dir配下にファイルとして保存した上でNoneを
    返す。パイプライン全体はクラッシュさせない）。

    上記の設定が揃っているにもかかわらず`gh issue create`自体が失敗した
    場合（ネットワークエラー・権限不足等）は、想定外の失敗として気づける
    よう、従来通りRuntimeErrorを送出する。
    """
    title = _build_issue_title(task)
    body = _build_issue_body(
        task,
        design,
        design_review_rounds,
        agent_result,
        code_review_rounds,
        output_dir,
        test_run_final,
    )

    if not (_has_git_identity() and _has_gh_auth()):
        fallback_path = output_dir / "issue_body_fallback.md"
        fallback_path.write_text(body, encoding="utf-8")
        return None

    argv = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
    if assignee:
        argv += ["--assignee", assignee]

    try:
        result = subprocess.run(
            argv,
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
