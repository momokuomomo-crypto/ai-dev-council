"""既存の生成済みアプリケーションを、変更指示に基づいて差分更新する。

処理の流れ:
  1. 対象ディレクトリ（--app-dir）に既存コードがあることを確認する
     （空ディレクトリへの新規生成は本ツールの役割ではない。
     新規生成は `python -m ai_dev_council.pipeline` を使う）
  2. gitの作業ツリーが汚れていれば警告する（更新前の状態へ戻す手段は
     gitに委ねるため、クリーンな状態からの実行を推奨する）
  3. 更新専用プロンプト（「新規作成ではない・既存コードを読んでから
     必要なファイルのみ修正する」ことを明示）でClaude Agent SDKを実行する
  4. テストを実行し、生ログ・CSVを保存する（test_runner流用）
  5. 実装レビュー（Gemini+OpenAI、既存のgenerate_code_review流用）→
     非承認ならClaude Agent SDKで修正、を最大max_implementation_rounds回
  6. 最終テストを実行し、更新レポート（JSON）と更新履歴.mdを保存する

ai-dev-council 本体には手を加えない。設計ドキュメントの生成も行わない
（ai-council側で更新・人間承認済みの設計書を --context-file で受け取る）。
"""

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import yaml

from ai_dev_council import claude_coding_agent, context_builder, test_runner, usage_tracker
from ai_dev_council.gemini_provider import generate_code_review as _gemini_code_review
from ai_dev_council.openai_provider import generate_code_review as _openai_code_review

# updater.py -> dev_updater -> プロジェクトルート -> ai_dev_council/config.yaml
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "ai_dev_council" / "config.yaml"

_CODE_REVIEW_FUNCS = {
    "gemini": _gemini_code_review,
    "openai": _openai_code_review,
}

_HISTORY_LOG_NAME = "更新履歴.md"

# レビューLLMへ渡す設計コンテキストの上限（コード全文とは別に渡すため控えめに）
_MAX_DESIGN_CONTEXT_CHARS = 30_000


def confirm(message: str) -> bool:
    """課金APIを呼ぶ前に[Y/n]で確認する。空入力（Enterのみ）はYとして扱う。"""
    answer = input(f"{message} [Y/n]: ").strip().lower()
    return answer in ("", "y", "yes")


def confirm_agent_run(app_dir: Path, max_turns: int) -> bool:
    """Claude Agent SDKによる自律更新実行前の確認（pipeline.pyと同趣旨）。"""
    message = (
        "\n警告：ここから先はClaude Agent SDKによる自律コーディングエージェントを起動します。\n"
        f"  - 対象ディレクトリ（既存アプリ）: {app_dir}\n"
        "  - このディレクトリ配下で既存ファイルの編集・新規ファイルの作成、および"
        "任意のbashコマンド（テスト実行等）が自動実行されます。\n"
        f"  - 1回の起動で最大{max_turns}ターンまで、費用は変動的です。\n"
        "  - 更新前の状態へ戻す手段はgitです。作業ツリーがクリーンな状態での"
        "実行を推奨します。\n"
    )
    answer = input(f"{message}続行しますか？ [Y/n]: ").strip().lower()
    return answer in ("", "y", "yes")


def _load_config() -> Dict[str, object]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_app_dir(app_dir: Path) -> None:
    """更新対象ディレクトリの妥当性を確認する。

    存在しない、またはソースファイルが1つも無い場合はエラーとする
    （本ツールは既存アプリの更新専用。新規生成はpipelineの役割）。
    """
    if not app_dir.is_dir():
        raise RuntimeError(f"更新対象ディレクトリが存在しません: {app_dir}")
    if not context_builder.iter_source_files(app_dir):
        raise RuntimeError(
            f"更新対象ディレクトリにソースファイルがありません: {app_dir}\n"
            "本ツールは既存アプリの更新専用です。新規生成は "
            "`python -m ai_dev_council.pipeline` を使ってください。"
        )


def git_dirty_files(app_dir: Path) -> Optional[List[str]]:
    """app_dir配下の未コミット変更の一覧を返す。

    gitリポジトリでない・gitが無い等、判定できない場合はNoneを返す
    （判定不能は「警告なし」として扱い、実行は妨げない）。
    """
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", "."],
            cwd=app_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return lines


def combine_context_files(paths: List[Path]) -> str:
    """複数の設計ドキュメント等を1つのcontext文字列に結合する。"""
    if len(paths) == 1:
        return paths[0].read_text(encoding="utf-8-sig")
    sections = []
    for path in paths:
        text = path.read_text(encoding="utf-8-sig")
        sections.append(f"===== 設計ドキュメント: {path.name} =====\n{text}")
    return "\n\n".join(sections)


def build_pseudo_design(instruction: str, design_context: str) -> Dict[str, object]:
    """レビュー関数・修正プロンプトへ渡す、更新タスク用の擬似設計ドキュメント。

    既存のgenerate_code_review / run_implementation_fixは設計ドキュメント
    （dict）を引数に取るため、更新タスクの文脈をその形に合わせて包む。
    """
    truncated_context = design_context[:_MAX_DESIGN_CONTEXT_CHARS]
    if len(design_context) > _MAX_DESIGN_CONTEXT_CHARS:
        truncated_context += "\n（文字数上限に達したため以降は省略）"
    return {
        "overview": (
            "既存アプリケーションへの差分更新タスク。新規開発ではない。"
            f"変更指示: {instruction}"
        ),
        "requirements": [
            "変更指示に該当する機能の追加・修正のみを行うこと",
            "既存のファイル構成・設計パターンを維持し、無関係のファイルを変更しないこと",
            "既存テストを壊さず、変更部分のテストを追加すること",
        ],
        "architecture": "既存コードの構造に従う（詳細は設計ドキュメント参照）",
        "design_document": truncated_context,
    }


def build_update_prompt(
    instruction: str, design_context: str, file_listing: List[str]
) -> str:
    """更新専用のエージェントプロンプトを組み立てる。

    pipeline側の実装プロンプト（新規作成前提）と異なり、既存アプリの
    差分更新であることを明示する。
    """
    files_text = "\n".join(f"- {p}" for p in file_listing)
    design_part = (
        f"# 設計ドキュメント（更新方針の参考）\n{design_context}\n\n" if design_context else ""
    )
    return (
        "これは【既存アプリケーションの更新タスク】です。新規作成ではありません。\n"
        "カレントディレクトリ（作業ディレクトリ）には稼働中の既存コードがあります。\n\n"
        "必ず以下の手順・制約に従ってください。\n\n"
        "1. まず既存のファイルをReadで読み、現在の構成・設計パターン"
        "（アダプターパターン等）を把握すること\n"
        "2. 変更指示の実現に必要なファイルのみを修正・追加すること。"
        "無関係のファイルは変更しないこと\n"
        "3. ゼロから作り直さないこと。既存の設計パターン・命名規約に従うこと\n"
        "4. 既存のテストを壊さないこと。変更部分に対するテストを追加すること\n"
        "5. テストを実行し、全て通るまで（または明らかに実行不可能と判断できる"
        "まで）修正を繰り返すこと\n"
        "6. 最後に、変更・追加したファイルの一覧とそれぞれの変更理由、"
        "テスト結果を明確に報告すること\n\n"
        f"# 変更指示\n{instruction}\n\n"
        f"{design_part}"
        f"# 既存ファイル一覧\n{files_text}\n"
    )


def _default_agent_runner(
    prompt: str, app_dir: Path, agent_config: Dict[str, object]
) -> Dict[str, object]:
    return asyncio.run(claude_coding_agent._run_query(prompt, app_dir, agent_config))


def run_update(
    app_dir: Path,
    instruction: str,
    design_context: str = "",
    max_implementation_rounds: int = 1,
    run_review: bool = True,
    agent_config: Optional[Dict[str, object]] = None,
    verbose: bool = True,
    agent_runner: Optional[Callable[..., Dict[str, object]]] = None,
    fix_runner: Optional[Callable[..., Dict[str, object]]] = None,
    review_funcs: Optional[Dict[str, Callable[..., Dict[str, object]]]] = None,
    test_fn: Optional[Callable[..., Dict[str, object]]] = None,
) -> Dict[str, object]:
    """コア処理。エージェント・レビュー・テストは差し替え可能（テスト用）。"""
    agent_config = agent_config or {}
    agent_runner = agent_runner or _default_agent_runner
    fix_runner = fix_runner or claude_coding_agent.run_implementation_fix
    review_funcs = review_funcs if review_funcs is not None else _CODE_REVIEW_FUNCS
    test_fn = test_fn or test_runner.run_tests_and_save_log

    check_app_dir(app_dir)

    file_listing = [
        p.relative_to(app_dir).as_posix() for p in context_builder.iter_source_files(app_dir)
    ]
    prompt = build_update_prompt(instruction, design_context, file_listing)

    agent_result = agent_runner(prompt, app_dir, agent_config)
    if verbose:
        print("\n=== 更新実行結果 ===")
        print(context_builder.build_test_results_summary(agent_result))

    test_run_update = _run_and_report_tests(test_fn, app_dir, "update", verbose)

    pseudo_design = build_pseudo_design(instruction, design_context)
    review_rounds: List[Dict[str, Dict[str, object]]] = []
    last_fix_result: Optional[Dict[str, object]] = None

    if run_review:
        for round_num in range(1, max_implementation_rounds + 1):
            code_context = context_builder.build_code_context(app_dir)
            feedback = {
                reviewer: func(instruction, pseudo_design, code_context)
                for reviewer, func in review_funcs.items()
            }
            review_rounds.append(feedback)
            if verbose:
                _print_review_round(round_num, feedback)
            if all(fb.get("approved") for fb in feedback.values()):
                break
            if round_num < max_implementation_rounds:
                last_fix_result = fix_runner(
                    instruction, pseudo_design, feedback, app_dir, agent_config
                )

    if last_fix_result is not None:
        agent_result = last_fix_result

    test_run_final = _run_and_report_tests(test_fn, app_dir, "update_final", verbose)

    return {
        "instruction": instruction,
        "agent_result": agent_result,
        "review_rounds": review_rounds,
        "test_run_update": test_run_update,
        "test_run_final": test_run_final,
    }


def _run_and_report_tests(
    test_fn: Callable[..., Dict[str, object]], app_dir: Path, label: str, verbose: bool
) -> Dict[str, object]:
    result = test_fn(app_dir, label=label)
    if verbose:
        print(f"\n=== テスト実行結果（{label}） ===")
        print(f"  {result['passed']}件成功 / {result['failed']}件失敗（計{result['total']}件）")
    return {
        **result,
        "log_path": str(result.get("log_path", "")),
        "csv_path": str(result.get("csv_path", "")),
    }


def _print_review_round(round_num: int, feedback: Dict[str, Dict[str, object]]) -> None:
    print(f"\n=== 実装レビュー ラウンド{round_num} ===")
    for reviewer, fb in feedback.items():
        approved = "承認" if fb.get("approved") else "未承認"
        print(f"  {reviewer}: {approved}")
        for issue in fb.get("issues", []):
            print(f"    [{issue.get('severity')}] {issue.get('description')}")


def write_report(result: Dict[str, object], app_dir: Path, timestamp: str) -> Path:
    report_path = app_dir / f"{timestamp}_update_report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def append_history(
    app_dir: Path, timestamp: str, instruction: str, report_path: Path
) -> Path:
    log_path = app_dir / _HISTORY_LOG_NAME
    lines: List[str] = []
    if not log_path.exists():
        lines.append("# 更新履歴\n")
        lines.append("dev_updater による既存アプリの更新履歴。旧版へ戻す場合はgitを使う。\n")
    lines.append(f"## {timestamp}")
    lines.append(f"- 変更指示: {instruction}")
    lines.append(f"- 更新レポート: {report_path.name}")
    lines.append("")
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return log_path


def main_cli() -> int:
    parser = argparse.ArgumentParser(
        description="生成済みアプリケーションを変更指示に基づいて差分更新する"
    )
    parser.add_argument("instruction", help="変更指示（例：横断価格比較機能を追加して）")
    parser.add_argument(
        "--app-dir", type=Path, required=True, help="更新対象の既存アプリのディレクトリ"
    )
    parser.add_argument(
        "--context-file",
        type=Path,
        action="append",
        dest="context_files",
        default=None,
        help="更新方針の設計ドキュメント（複数回指定可。ai-council側で更新・承認済みのもの）",
    )
    parser.add_argument(
        "--max-implementation-rounds",
        type=int,
        default=1,
        help="実装レビュー→修正のループ上限回数（デフォルト1）",
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="実装レビュー（Gemini+OpenAI）を省略する（低コスト。エージェント実行とテストのみ）",
    )
    args = parser.parse_args()

    try:
        check_app_dir(args.app_dir)
    except RuntimeError as e:
        print(f"エラー：{e}")
        return 1

    design_context = ""
    if args.context_files:
        try:
            design_context = combine_context_files(args.context_files)
        except FileNotFoundError as e:
            print(f"エラー：{e}")
            return 1

    config = _load_config()
    agent_config = config.get("claude_agent", {})
    max_runs_per_day = config.get("max_runs_per_day", 3)

    run_review = not args.no_review
    review_calls = 2 * args.max_implementation_rounds if run_review else 0
    if run_review:
        message = (
            f"Gemini/OpenAIのAPIを最大{review_calls}回呼び出します"
            f"（実装レビュー最大{args.max_implementation_rounds}ラウンド×2社。"
            "この回数にはClaude Agent SDKによる更新実行は含まれません — 別途確認します）。"
            "続行しますか？"
        )
    else:
        message = (
            "--no-review のため固定回数のAPI呼び出しはありません"
            "（Claude Agent SDKによる更新実行のみ — 次で確認します）。続行しますか？"
        )
    if not confirm(message):
        print("中断しました。")
        return 1

    dirty = git_dirty_files(args.app_dir)
    if dirty:
        print(
            f"\n注意：{args.app_dir} 配下に未コミットの変更が{len(dirty)}件あります。\n"
            "更新前の状態へ戻す手段はgitのため、先にコミットしてからの実行を推奨します。"
        )
        if not confirm("このまま続行しますか？"):
            print("中断しました。")
            return 1

    try:
        usage_tracker.check_and_increment(max_runs_per_day)
    except RuntimeError as e:
        print(f"エラー：{e}")
        return 1

    if not confirm_agent_run(args.app_dir, agent_config.get("max_turns", 40)):
        print("中断しました。")
        return 1

    try:
        result = run_update(
            args.app_dir,
            args.instruction,
            design_context=design_context,
            max_implementation_rounds=args.max_implementation_rounds,
            run_review=run_review,
            agent_config=agent_config,
        )
    except Exception as e:
        print(f"エラー：{e}")
        return 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    report_path = write_report(result, args.app_dir, timestamp)
    history_path = append_history(args.app_dir, timestamp, args.instruction, report_path)

    print(f"\n更新レポートを出力しました：{report_path}")
    print(f"更新履歴に追記しました：{history_path}")
    print("変更内容は git diff で確認し、問題なければコミットしてください。")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
