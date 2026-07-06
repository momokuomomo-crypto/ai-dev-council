"""
実装レビュー（Stage 実装レビュー）向けに、output_dir配下の生成済み
ファイル内容を、レビューLLMへ渡すための1つのテキストへ連結する。

生成されたコードそのものをコンテキストとして渡す必要があるため、
ファイルパス付きで連結する方式を採る。合計文字数が上限を超える場合は
無言で切り詰めず、打ち切った旨を明記する。
"""

from pathlib import Path
from typing import Dict, Iterable, List

_DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".pytest_cache",
}
_MAX_TOTAL_CHARS = 200_000


def iter_source_files(
    output_dir: Path, exclude_dirs: Iterable[str] = _DEFAULT_EXCLUDE_DIRS
) -> List[Path]:
    """output_dir配下の全ファイルを、除外ディレクトリを飛ばして相対パス順に列挙する。"""
    exclude = set(exclude_dirs)
    files = [
        p
        for p in output_dir.rglob("*")
        if p.is_file() and not any(part in exclude for part in p.relative_to(output_dir).parts)
    ]
    return sorted(files, key=lambda p: p.relative_to(output_dir).as_posix())


def build_code_context(output_dir: Path) -> str:
    """各ファイルをパス付きで連結する。上限を超える場合は打ち切った旨を明記する。"""
    files = iter_source_files(output_dir)
    parts: List[str] = []
    total_chars = 0
    truncated = False

    for path in files:
        relative = path.relative_to(output_dir).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        block = f"### {relative}\n```\n{content}\n```\n"
        if total_chars + len(block) > _MAX_TOTAL_CHARS:
            truncated = True
            break

        parts.append(block)
        total_chars += len(block)

    if truncated:
        parts.append(
            f"（文字数上限（{_MAX_TOTAL_CHARS}文字）に達したため、以降のファイルは省略しました）"
        )

    return "\n".join(parts)


def build_test_results_summary(agent_result: Dict[str, object]) -> str:
    """claude_coding_agentの実行結果から、テスト結果の要約を抽出する。"""
    status = "成功" if agent_result.get("success") else f"未完了（{agent_result.get('subtype')}）"
    result_text = agent_result.get("result_text") or ""
    return f"実装結果: {status}\n\n{result_text}"
