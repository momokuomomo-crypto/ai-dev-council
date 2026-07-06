"""
1日あたりの実行回数を記録・制限する。

`.usage_count.json`（プロジェクトルート、git管理対象外）に日付ごとの
実行回数を記録する。CLI実行時、config.yamlのmax_runs_per_dayを超える
実行は拒否する（実APIを呼ぶ前にチェックする）。
"""

import json
from datetime import date
from pathlib import Path
from typing import Dict, Optional

# usage_tracker.py -> ai_dev_council -> プロジェクトルート
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_USAGE_PATH = _PROJECT_ROOT / ".usage_count.json"


def _read_usage() -> Dict[str, int]:
    if not _USAGE_PATH.exists():
        return {}
    return json.loads(_USAGE_PATH.read_text(encoding="utf-8"))


def _write_usage(usage: Dict[str, int]) -> None:
    _USAGE_PATH.write_text(json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")


def check_and_increment(max_runs_per_day: int, today: Optional[str] = None) -> None:
    """
    本日の実行回数がmax_runs_per_dayに達していればRuntimeErrorを送出する。

    達していなければ、実行回数を1増やして記録する（実APIを呼ぶ前に
    呼び出すことで、上限超過時に課金を発生させない）。
    """
    today = today or date.today().isoformat()
    usage = _read_usage()
    count = usage.get(today, 0)
    if count >= max_runs_per_day:
        raise RuntimeError(
            f"本日の実行回数が上限（{max_runs_per_day}回）に達しています。"
            "上限はconfig.yamlのmax_runs_per_dayで変更できます。"
        )
    usage[today] = count + 1
    _write_usage(usage)
