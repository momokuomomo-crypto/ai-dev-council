"""
LLM APIキーの管理を行う。

.envファイル（プロジェクトルート、git管理対象外）からAPIキーを読み込む。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# llm_config.py -> ai_dev_council -> プロジェクトルート
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

_ENV_VAR_BY_PROVIDER = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

# override=True: .envファイルの値を正とする（既存のOS環境変数を優先させない）。
load_dotenv(_ENV_PATH, override=True)


def get_api_key(provider: str) -> str:
    """
    プロバイダ名（"anthropic" / "openai" / "gemini"）からAPIキーを取得する。

    未対応のプロバイダを指定した場合、または該当するAPIキーが未設定の場合は
    例外を送出する。
    """
    if provider not in _ENV_VAR_BY_PROVIDER:
        raise ValueError(f"未対応のプロバイダです: {provider}")

    env_var = _ENV_VAR_BY_PROVIDER[provider]
    api_key = os.environ.get(env_var)
    if not api_key:
        raise RuntimeError(
            f"{env_var} が設定されていません。プロジェクトルートの.envを確認してください。"
        )
    return api_key
