"""
ai-dev-council オーケストレーター。

自然言語のタスク説明を受け取り、以下の順で実行する:
  1. 設計 (OpenAI)
  2. 設計レビュー（Claude+Gemini、リビジョンループ、最大max_rounds回）
  3. 実装（Claude Agent SDK、output_dirへ実コード+テストを書く）
  4. 実装レビュー（Gemini+OpenAI、リビジョンループ、最大max_implementation_rounds回）
  5. GitHub issue作成（ai-dev-council自身のリポジトリに、OPENのまま）

会話専用のai-council（別リポジトリ）とは異なり、実際にファイル書き込み・
bash実行を行う自律コーディングエージェント（claude_coding_agent.py）を
含むため、確認ゲートを2段階に分けている（confirm_api_calls / confirm_agent_run）。
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import yaml

from . import (
    claude_coding_agent,
    claude_provider,
    context_builder,
    gemini_provider,
    github_issue,
    openai_provider,
    usage_tracker,
)

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

_DESIGN_REVIEW_FUNCS = {
    "claude": claude_provider.generate_design_review,
    "gemini": gemini_provider.generate_design_review,
}

_CODE_REVIEW_FUNCS = {
    "gemini": gemini_provider.generate_code_review,
    "openai": openai_provider.generate_code_review,
}


def confirm_api_calls(message: str) -> bool:
    """課金APIを呼ぶ前に[Y/n]で確認する。空入力（Enterのみ）はYとして扱う。"""
    answer = input(f"{message} [Y/n]: ").strip().lower()
    return answer in ("", "y", "yes")


def confirm_agent_run(output_dir: Path, max_turns: int) -> bool:
    """
    Claude Agent SDKによる自律コーディング実行前の確認。

    通常の固定回数API呼び出しとは異なり、この段階はファイル書き込み・
    bashコマンド実行を伴う自律的・多ターンの実行であることを明示して警告する。
    """
    message = (
        "\n警告：ここから先はClaude Agent SDKによる自律コーディングエージェントを起動します。\n"
        f"  - 対象ディレクトリ: {output_dir}\n"
        "  - このディレクトリ配下でファイルの作成・編集、および任意のbashコマンド"
        "（テスト実行等）が自動実行されます。\n"
        f"  - 1回の起動で最大{max_turns}ターンまで、通常のAPI呼び出しより遥かに"
        "多くのやり取り・トークンを消費し、費用も変動的です（固定回数ではありません）。\n"
        "  - 実装レビューで指摘があれば、同ディレクトリに対して再度この自律実行が"
        "走ります。\n"
    )
    answer = input(f"{message}続行しますか？ [Y/n]: ").strip().lower()
    return answer in ("", "y", "yes")


def _load_config() -> Dict[str, object]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_design_stage(task: str, context: str = "") -> Dict[str, object]:
    """Stage 設計: OpenAIが設計ドキュメントを生成する。"""
    return openai_provider.generate_design(task, context)


def run_design_review(
    task: str,
    design: Dict[str, object],
    max_rounds: int = 1,
    on_round: Optional[Callable[[int, Dict[str, Dict[str, object]]], None]] = None,
) -> Tuple[Dict[str, object], List[Dict[str, Dict[str, object]]]]:
    """
    Stage 設計レビュー: Claude+Geminiが独立にレビューし、非承認ならOpenAIが
    改訂、を最大max_rounds回繰り返す。全員承認で早期終了。

    戻り値: (最終的な設計ドキュメント, 各ラウンドのレビュー結果一覧)
    """
    current_design = design
    rounds: List[Dict[str, Dict[str, object]]] = []

    for round_num in range(1, max_rounds + 1):
        review_feedback = {
            reviewer: func(task, current_design) for reviewer, func in _DESIGN_REVIEW_FUNCS.items()
        }
        rounds.append(review_feedback)
        if on_round is not None:
            on_round(round_num, review_feedback)

        if all(fb["approved"] for fb in review_feedback.values()):
            break
        if round_num < max_rounds:
            current_design = openai_provider.generate_design_revision(
                task, current_design, review_feedback
            )

    return current_design, rounds


def run_implementation(
    task: str,
    design: Dict[str, object],
    output_dir: Path,
    agent_config: Dict[str, object],
) -> Dict[str, object]:
    """Stage 実装: Claude Agent SDKでoutput_dirへコード+テストを書く。"""
    return claude_coding_agent.run_implementation(task, design, output_dir, agent_config)


def run_code_review(
    task: str,
    design: Dict[str, object],
    output_dir: Path,
    agent_config: Dict[str, object],
    max_rounds: int = 1,
    on_round: Optional[Callable[[int, Dict[str, Dict[str, object]]], None]] = None,
) -> Tuple[Optional[Dict[str, object]], List[Dict[str, Dict[str, object]]]]:
    """
    Stage 実装レビュー: Gemini+OpenAIが生成コードを独立にレビューし、
    非承認ならClaude Agent SDKで修正、を最大max_rounds回繰り返す。
    全員承認で早期終了。

    戻り値: (最後に実行した修正のagent_result、Noneの場合は修正なし, 各ラウンドのレビュー結果一覧)
    """
    rounds: List[Dict[str, Dict[str, object]]] = []
    last_fix_result: Optional[Dict[str, object]] = None

    for round_num in range(1, max_rounds + 1):
        code_context = context_builder.build_code_context(output_dir)
        review_feedback = {
            reviewer: func(task, design, code_context) for reviewer, func in _CODE_REVIEW_FUNCS.items()
        }
        rounds.append(review_feedback)
        if on_round is not None:
            on_round(round_num, review_feedback)

        if all(fb["approved"] for fb in review_feedback.values()):
            break
        if round_num < max_rounds:
            last_fix_result = claude_coding_agent.run_implementation_fix(
                task, design, review_feedback, output_dir, agent_config
            )

    return last_fix_result, rounds


def _estimate_fixed_call_count(max_rounds: int, max_implementation_rounds: int) -> int:
    design_calls = 1
    design_review_calls = 2 * max_rounds
    design_revision_calls = max(0, max_rounds - 1)
    code_review_calls = 2 * max_implementation_rounds
    return design_calls + design_review_calls + design_revision_calls + code_review_calls


def _print_design(design: Dict[str, object]) -> None:
    print("\n=== 設計ドキュメント ===")
    print(f"概要: {design.get('overview', '')}")
    print(f"アーキテクチャ: {design.get('architecture', '')}")


def _print_review_round(stage_label: str, round_num: int, feedback: Dict[str, Dict[str, object]]) -> None:
    print(f"\n=== {stage_label} ラウンド{round_num} ===")
    for reviewer, fb in feedback.items():
        approved = "承認" if fb.get("approved") else "未承認"
        print(f"  {reviewer}: {approved}")
        for issue in fb.get("issues", []):
            print(f"    [{issue.get('severity')}] {issue.get('description')}")


def run_pipeline(
    task: str,
    output_dir: Path,
    context: str = "",
    max_rounds: int = 1,
    max_implementation_rounds: int = 1,
    verbose: bool = True,
) -> Dict[str, object]:
    """設計→設計レビュー→実装→実装レビュー→issue作成を通しで実行する。"""
    config = _load_config()
    agent_config = config.get("claude_agent", {})

    design = run_design_stage(task, context)
    if verbose:
        _print_design(design)

    on_design_round = (lambda n, fb: _print_review_round("設計レビュー", n, fb)) if verbose else None
    final_design, design_review_rounds = run_design_review(
        task, design, max_rounds, on_round=on_design_round
    )

    if not confirm_agent_run(output_dir, agent_config.get("max_turns", 40)):
        raise RuntimeError("ユーザーが自律コーディングエージェントの実行を中止しました。")

    agent_result = run_implementation(task, final_design, output_dir, agent_config)
    if verbose:
        print("\n=== 実装結果 ===")
        print(context_builder.build_test_results_summary(agent_result))

    on_code_round = (lambda n, fb: _print_review_round("実装レビュー", n, fb)) if verbose else None
    last_fix_result, code_review_rounds = run_code_review(
        task, final_design, output_dir, agent_config, max_implementation_rounds, on_round=on_code_round
    )
    if last_fix_result is not None:
        agent_result = last_fix_result

    issue_url = github_issue.create_run_issue(
        repo=config["github_repo"],
        task=task,
        design=final_design,
        design_review_rounds=design_review_rounds,
        agent_result=agent_result,
        code_review_rounds=code_review_rounds,
        output_dir=output_dir,
    )

    return {
        "task": task,
        "design": final_design,
        "design_review_rounds": design_review_rounds,
        "agent_result": agent_result,
        "code_review_rounds": code_review_rounds,
        "issue_url": issue_url,
    }


def _write_report(result: Dict[str, object], output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    report_path = output_dir / f"{timestamp}_pipeline_report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def main_cli() -> int:
    parser = argparse.ArgumentParser(description="タスク説明からコードを自律生成するAIパイプライン")
    parser.add_argument("task", help="作りたいソフトウェアのタスク説明（自由記述）")
    parser.add_argument("--output-dir", type=Path, required=True, help="生成先ディレクトリ")
    parser.add_argument(
        "--context-file", type=Path, default=None, help="参考情報を含むテキストファイル（任意）"
    )
    parser.add_argument(
        "--max-rounds", type=int, default=1, help="設計レビューのリビジョンループ上限回数（デフォルト1）"
    )
    parser.add_argument(
        "--max-implementation-rounds",
        type=int,
        default=1,
        help="実装レビュー→修正のリビジョンループ上限回数（デフォルト1）",
    )
    args = parser.parse_args()

    config = _load_config()
    max_runs_per_day = config.get("max_runs_per_day", 3)

    fixed_call_count = _estimate_fixed_call_count(args.max_rounds, args.max_implementation_rounds)
    if not confirm_api_calls(
        f"OpenAI/Claude/GeminiのAPIを最大{fixed_call_count}回呼び出します"
        f"（設計1回、設計レビュー最大{2 * args.max_rounds}回、"
        f"設計改訂最大{max(0, args.max_rounds - 1)}回、"
        f"実装レビュー最大{2 * args.max_implementation_rounds}回。"
        "この回数にはClaude Agent SDKによる実装ステージは含まれません — "
        "別途確認します）。続行しますか？"
    ):
        print("中断しました。")
        return 1

    context = ""
    if args.context_file is not None:
        try:
            context = args.context_file.read_text(encoding="utf-8-sig")
        except FileNotFoundError as e:
            print(f"エラー：{e}")
            return 1

    try:
        usage_tracker.check_and_increment(max_runs_per_day)
    except RuntimeError as e:
        print(f"エラー：{e}")
        return 1

    try:
        result = run_pipeline(
            args.task,
            args.output_dir,
            context=context,
            max_rounds=args.max_rounds,
            max_implementation_rounds=args.max_implementation_rounds,
        )
    except Exception as e:
        print(f"エラー：{e}")
        return 1

    report_path = _write_report(result, args.output_dir)
    print(f"\nパイプライン実行レポートを出力しました：{report_path}")
    print(f"GitHub issueを作成しました：{result['issue_url']}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main_cli())
