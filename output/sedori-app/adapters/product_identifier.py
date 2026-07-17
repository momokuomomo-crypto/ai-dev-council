"""写真からの商品特定アダプタ。

バーコード（JAN/EAN）読み取りを主軸としつつ、バーコードの無い商品向けの
補助機能として、マルチモーダルLLM（Claude API）に商品写真を渡して
商品名の候補を返させる（ai-council議論の案B「バーコード主軸＋画像認識は
補助、候補を複数表示しユーザーに選択させるUX」に対応）。

注意:
- 判別1回ごとにClaude APIの利用料金が発生する（バーコード読み取りは
  端末内処理のため無料）。
- ANTHROPIC_API_KEY が未設定の環境では機能自体を無効として扱い、
  アプリ本体（バーコード・利益計算）はAPIキーなしでも動作する。
"""

import base64
import json
import os
import re
from abc import ABC, abstractmethod
from typing import List

import config

_PROMPT = (
    "この写真に写っている商品を特定してください。"
    "日本のECサイト（Amazon・メルカリ等）で検索しやすい商品名の候補を、"
    "確からしい順に最大3件挙げてください。"
    '各要素が {"name": "検索用の商品名", "note": "メーカー・型番・シリーズ等の補足（なければ空文字）"} '
    "であるJSON配列のみを出力してください。JSON以外の文章は含めないでください。"
    "商品が特定できない場合は空配列 [] を返してください。"
)


class ProductIdentifier(ABC):
    """写真からの商品特定アダプタの抽象基底クラス。"""

    @abstractmethod
    def is_available(self) -> bool:
        """この環境で画像判別が利用可能かを返す。"""
        raise NotImplementedError

    @abstractmethod
    def identify(self, image_bytes: bytes, media_type: str) -> List[dict]:
        """画像から商品名候補を返す。

        戻り値は [{"name": str, "note": str}, ...]（最大3件、確からしい順）。
        """
        raise NotImplementedError


class DisabledIdentifier(ProductIdentifier):
    """APIキー未設定環境用。機能を無効として扱う。"""

    def is_available(self) -> bool:
        return False

    def identify(self, image_bytes: bytes, media_type: str) -> List[dict]:
        raise RuntimeError("画像判別機能は無効です（ANTHROPIC_API_KEYが未設定）。")


class ClaudeProductIdentifier(ProductIdentifier):
    """Claude API（マルチモーダル）による商品特定アダプタ。"""

    def __init__(self, model: str = None):
        self._model = model or config.IDENTIFY_MODEL
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def is_available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def identify(self, image_bytes: bytes, media_type: str) -> List[dict]:
        client = self._get_client()
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        response = client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        return _parse_candidates(text)


def _parse_candidates(text: str) -> List[dict]:
    """モデル出力から候補のJSON配列を頑健に取り出す。"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\[.*\]", text or "", re.DOTALL)
        if m is None:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []

    if not isinstance(data, list):
        return []
    candidates = []
    for item in data[:3]:
        if isinstance(item, dict) and item.get("name"):
            candidates.append(
                {"name": str(item["name"]), "note": str(item.get("note", "") or "")}
            )
    return candidates


def get_product_identifier() -> ProductIdentifier:
    """現在の環境で使用する商品特定アダプタを返す。

    ANTHROPIC_API_KEYが設定されていればClaude、なければ無効アダプタを返す
    （アプリ本体はAPIキーなしでも動作させるため）。
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeProductIdentifier()
    return DisabledIdentifier()
