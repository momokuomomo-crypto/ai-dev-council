# -*- coding: utf-8 -*-
"""
生成されたコードのテストスイート（pytest想定）を実際に実行し、
記録として残すモジュール。

エージェント（claude_coding_agent）の自己申告（result_text／transcript）
だけでは、テストケース単位でどれが通ったかが後から追いにくい。実際の
pytest実行結果を生ログと、テストケース単位のCSVとしてoutput_dir配下に
保存し、後から参照できるようにする。
"""
import csv
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_RESULT_LINE_RE = re.compile(
    r"^(?P<node_id>\S+::\S+)\s+(?P<result>PASSED|FAILED|ERROR|SKIPPED)\b"
)
_CSV_FIELDNAMES = ["テストケース", "結果", "ログファイル", "行数"]


def _parse_result_rows(output_text: str, log_relative_path: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for line_no, line in enumerate(output_text.splitlines(), start=1):
        m = _RESULT_LINE_RE.match(line.strip())
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


def run_tests_and_save_log(
    output_dir: Path, label: str = "", timeout: int = 300
) -> Dict[str, object]:
    """
    output_dir配下で`pytest -v tests`を実行し、生ログとテストケース単位の
    結果CSVを output_dir/test_logs/ 配下に保存する。

    テストディレクトリが存在しない、pytestが未インストール等で実行自体に
    失敗した場合もクラッシュさせず、その旨を記録として残す
    （呼び出し元のパイプラインを止めないため）。
    """
    log_dir = output_dir / "test_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    log_path = log_dir / f"{timestamp}{suffix}_pytest_log.txt"
    csv_path = log_dir / f"{timestamp}{suffix}_test_results.csv"

    returncode: Optional[int] = None
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
            returncode = proc.returncode
        except Exception as e:
            output_text = f"テスト実行自体に失敗しました: {e}"

    log_path.write_text(output_text, encoding="utf-8")

    rows = _parse_result_rows(output_text, log_path.relative_to(output_dir).as_posix())
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "log_path": log_path,
        "csv_path": csv_path,
        "returncode": returncode,
        "total": len(rows),
        "passed": sum(1 for r in rows if r["結果"] == "PASSED"),
        "failed": sum(1 for r in rows if r["結果"] in ("FAILED", "ERROR")),
    }
