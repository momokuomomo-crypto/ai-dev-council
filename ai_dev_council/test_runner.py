# -*- coding: utf-8 -*-
"""
生成されたコードのテストスイートを実際に実行し、記録として残すモジュール。

エージェント（claude_coding_agent）の自己申告（result_text／transcript）
だけでは、テストケース単位でどれが通ったかが後から追いにくい。実際の
テスト実行結果を生ログと、テストケース単位のCSVとしてoutput_dir配下に
保存し、後から参照できるようにする。

プロジェクト種別（Python/pytest か C#・.NET/dotnet test か）は
output_dir配下のファイル構成から自動判定する。両者でCSVの列構成
（テストケース／結果／ログファイル／行数）は共通にする。
"""
import csv
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_PYTEST_RESULT_LINE_RE = re.compile(
    r"^(?P<node_id>\S+::\S+)\s+(?P<result>PASSED|FAILED|ERROR|SKIPPED)\b"
)
_TRX_NAMESPACE = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
_TRX_OUTCOME_MAP = {
    "Passed": "PASSED",
    "Failed": "FAILED",
    "NotExecuted": "SKIPPED",
}
_CSV_FIELDNAMES = ["テストケース", "結果", "ログファイル", "行数"]


def _detect_project_type(output_dir: Path) -> str:
    """output_dir配下に.sln/.csprojがあれば'dotnet'、なければ'pytest'を返す。"""
    if list(output_dir.glob("*.sln")) or list(output_dir.rglob("*.csproj")):
        return "dotnet"
    return "pytest"


def _parse_pytest_result_rows(output_text: str, log_relative_path: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for line_no, line in enumerate(output_text.splitlines(), start=1):
        m = _PYTEST_RESULT_LINE_RE.match(line.strip())
        if m:
            rows.append(
                {
                    "テストケース": m.group("node_id"),
                    "結果": m.group("result"),
                    "ログファイル": log_relative_path,
                    "行数": line_no,
                }
            )
    return rows


def _run_pytest(output_dir: Path, log_dir: Path, timestamp: str, suffix: str, timeout: int) -> Tuple[Path, List[Dict[str, object]]]:
    log_path = log_dir / f"{timestamp}{suffix}_pytest_log.txt"

    if not (output_dir / "tests").is_dir():
        output_text = "テストディレクトリ（tests/）が見つからないため、実行をスキップしました。"
    else:
        try:
            proc = subprocess.run(
                ["python", "-m", "pytest", "-v", "--tb=short", "tests"],
                cwd=str(output_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output_text = proc.stdout + proc.stderr
        except Exception as e:
            output_text = f"テスト実行自体に失敗しました: {e}"

    log_path.write_text(output_text, encoding="utf-8")
    rows = _parse_pytest_result_rows(output_text, log_path.relative_to(output_dir).as_posix())
    return log_path, rows


def _find_line_number(output_text: str, needle: str) -> Optional[int]:
    for line_no, line in enumerate(output_text.splitlines(), start=1):
        if needle in line:
            return line_no
    return None


def _parse_trx_result_rows(
    trx_path: Path, log_relative_path: str, output_text: str
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    try:
        tree = ET.parse(trx_path)
    except ET.ParseError:
        return rows

    for result_el in tree.getroot().findall(".//t:Results/t:UnitTestResult", _TRX_NAMESPACE):
        test_name = result_el.get("testName", "unknown")
        outcome = _TRX_OUTCOME_MAP.get(result_el.get("outcome", ""), "ERROR")
        short_name = test_name.rsplit(".", 1)[-1]
        line_no = _find_line_number(output_text, short_name)
        rows.append(
            {
                "テストケース": test_name,
                "結果": outcome,
                "ログファイル": log_relative_path,
                "行数": line_no if line_no is not None else "",
            }
        )
    return rows


def _run_dotnet_test(output_dir: Path, log_dir: Path, timestamp: str, suffix: str, timeout: int) -> Tuple[Path, List[Dict[str, object]]]:
    log_path = log_dir / f"{timestamp}{suffix}_dotnet_test_log.txt"
    trx_filename = f"{timestamp}{suffix}_results.trx"
    env = {**os.environ, "DOTNET_CLI_UI_LANGUAGE": "en"}

    try:
        proc = subprocess.run(
            [
                "dotnet",
                "test",
                "--logger",
                f"trx;LogFileName={trx_filename}",
                "--results-directory",
                str(log_dir),
            ],
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        output_text = proc.stdout + proc.stderr
    except Exception as e:
        output_text = f"テスト実行自体に失敗しました: {e}"

    log_path.write_text(output_text, encoding="utf-8")

    trx_path = log_dir / trx_filename
    rows = (
        _parse_trx_result_rows(trx_path, log_path.relative_to(output_dir).as_posix(), output_text)
        if trx_path.exists()
        else []
    )
    return log_path, rows


def run_tests_and_save_log(
    output_dir: Path, label: str = "", timeout: int = 300
) -> Dict[str, object]:
    """
    output_dir配下でテストスイートを実行し、生ログとテストケース単位の
    結果CSVを output_dir/test_logs/ 配下に保存する。

    output_dir配下に.sln/.csprojがあれば`dotnet test`を、なければ
    `pytest`を実行する。テスト自体が存在しない、コマンドが見つからない等で
    実行自体に失敗した場合もクラッシュさせず、その旨を記録として残す
    （呼び出し元のパイプラインを止めないため）。

    output_dirは相対パスの場合、絶対パスへ解決してから使う。
    `--results-directory`等、dotnet testに渡す相対パスはdotnet test自身の
    cwd（=output_dir）基準で再解決されるため、output_dirが相対のままだと
    `output_dir/output_dir/test_logs/...`のような二重ネストしたパスに
    結果ファイルが書き出され、Python側で読み取れなくなる不具合があった。
    """
    output_dir = output_dir.resolve()
    log_dir = output_dir / "test_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""

    project_type = _detect_project_type(output_dir)
    if project_type == "dotnet":
        log_path, rows = _run_dotnet_test(output_dir, log_dir, timestamp, suffix, timeout)
    else:
        log_path, rows = _run_pytest(output_dir, log_dir, timestamp, suffix, timeout)

    csv_path = log_dir / f"{timestamp}{suffix}_test_results.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "project_type": project_type,
        "log_path": log_path,
        "csv_path": csv_path,
        "total": len(rows),
        "passed": sum(1 for r in rows if r["結果"] == "PASSED"),
        "failed": sum(1 for r in rows if r["結果"] in ("FAILED", "ERROR")),
    }
