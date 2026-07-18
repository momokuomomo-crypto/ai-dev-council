"""価格取得アダプタの抽象基底クラスと、各アダプタ実装。

将来的にECサイトのAPI連携やスクレイピングによる自動価格取得を追加する場合は、
`PriceSource` を継承した新しいアダプタクラスを追加し、`get_price_source()` の
切り替え先を増やすことでフックできる設計にしている（案C）。

- `ManualInputPriceSource`: MVPで利用する手動入力アダプタ。価格自動取得は常に
  「未対応（None）」を返す。外部ECサイトの検索結果ページへのリンク生成のみ
  サポートする（自動取得は行わない）。
- `RakutenPriceSource`: 第2フェーズで追加した楽天市場APIアダプタ（サーバー
  サイド）。PythonAnywhere無料プランのホワイトリストに app.rakuten.co.jp が
  含まれることを確認済みのため、Flask側から呼び出す。RAKUTEN_APP_ID未設定
  時は `DisabledPriceComparisonSource` に切り替わり、機能自体を無効化する。
- Yahoo!ショッピングAPI（shopping.yahooapis.jp）はホワイトリスト対象外の
  ため、ブラウザ側（static/js/app.js）から直接呼び出す構成とし、本モジュール
  ではサーバーサイドアダプタを実装しない。
"""

import json
import os
import statistics
import threading
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import List, Optional
from urllib.parse import quote

import config
from config import EC_SEARCH_SITES


class PriceInfo:
    """価格情報を表す単純なデータクラス。"""

    def __init__(self, price: float, source_name: str, item_name: str = "", url: str = ""):
        self.price = price
        self.source_name = source_name
        self.item_name = item_name
        self.url = url

    def to_dict(self):
        return {
            "price": self.price,
            "source_name": self.source_name,
            "item_name": self.item_name,
            "url": self.url,
        }


class PriceFetchError(Exception):
    """価格取得（外部API呼び出し等）に失敗した場合に送出する例外。

    呼び出し側（Flaskルート）でハンドルし、一部サイト失敗時の部分表示・
    再取得導線の表示につなげる。
    """


class PriceSource(ABC):
    """価格取得アダプタの抽象基底クラス。"""

    @abstractmethod
    def fetch_price(self, jan_code: str) -> Optional[PriceInfo]:
        """JAN/EANコードから価格情報を取得する。取得できない場合は None を返す。"""
        raise NotImplementedError

    @abstractmethod
    def get_search_links(self, jan_code: str) -> list:
        """JAN/EANコードから、各ECサイトの検索結果ページへのリンク一覧を返す。

        戻り値は [{"key": str, "name": str, "url": str}, ...] の形式。
        あくまで検索結果ページへのリンクを組み立てるだけであり、
        ページ内容の自動取得（スクレイピング）は一切行わない。
        """
        raise NotImplementedError


def _build_search_links(jan_code: str) -> list:
    """JAN/EANコードから各ECサイトの検索結果ページへのリンク一覧を組み立てる。

    複数のアダプタ（手動入力・楽天等）で共通利用するヘルパー。
    """
    links = []
    query = quote(jan_code or "")
    for site in EC_SEARCH_SITES:
        url = site["url_template"].format(jan=query)
        links.append({"key": site["key"], "name": site["name"], "url": url})
    return links


class ManualInputPriceSource(PriceSource):
    """MVPで利用する「手動入力アダプタ」。

    価格の自動取得は一切行わず、常に None を返す（ユーザーが手動で入力する前提）。
    検索リンクの生成のみサポートする。
    """

    def fetch_price(self, jan_code: str) -> Optional[PriceInfo]:
        # MVPでは自動取得は行わない仕様のため、常に None（未対応）を返す。
        return None

    def get_search_links(self, jan_code: str) -> list:
        return _build_search_links(jan_code)


def get_price_source() -> PriceSource:
    """現在使用する価格取得アダプタを返す（MVPでは手動入力アダプタ固定）。"""
    return ManualInputPriceSource()


# ---------------------------------------------------------------------------
# 横断価格比較機能（楽天市場API）: 第2フェーズで追加
# ---------------------------------------------------------------------------

class RakutenThrottle:
    """楽天APIへのリクエスト間隔を最低限空けるための簡易スロットリング。

    直前呼び出し時刻を記録し、最小間隔（デフォルト1秒）未満のリクエストは
    待機してから実行する。複数リクエストにまたがって間隔を守れるよう、
    モジュール共有のインスタンス（`_rakuten_throttle`）を介して利用する。
    time_func/sleep_funcはテストで注入できるようにするための引数。
    """

    def __init__(self, min_interval=None, time_func=time.monotonic, sleep_func=time.sleep):
        self._min_interval = (
            min_interval if min_interval is not None else config.RAKUTEN_THROTTLE_INTERVAL_SECONDS
        )
        self._time_func = time_func
        self._sleep_func = sleep_func
        self._lock = threading.Lock()
        self._last_call = None

    def wait(self):
        """必要であれば待機し、呼び出し直前の時刻を記録する。"""
        with self._lock:
            now = self._time_func()
            if self._last_call is not None:
                elapsed = now - self._last_call
                if elapsed < self._min_interval:
                    self._sleep_func(self._min_interval - elapsed)
                    now = self._time_func()
            self._last_call = now


# アプリ内で使い回す楽天APIスロットラー（リクエストをまたいで間隔を守るため
# モジュールレベルの単一インスタンスとして保持する）。
_rakuten_throttle = RakutenThrottle()


class RakutenPriceSource(PriceSource):
    """楽天市場APIによる価格取得アダプタ（サーバーサイド）。

    PythonAnywhere無料プランの外部通信ホワイトリストに app.rakuten.co.jp が
    含まれることを確認済みのため、Flask（サーバー側）から呼び出す構成とする。
    RAKUTEN_APP_ID未設定の環境では `get_price_comparison_source()` が
    `DisabledPriceComparisonSource` を返すため、本クラスは使用されない。
    """

    def __init__(self, app_id=None, throttle=None, opener=None):
        self._app_id = app_id if app_id is not None else os.environ.get("RAKUTEN_APP_ID")
        self._throttle = throttle if throttle is not None else _rakuten_throttle
        self._opener = opener if opener is not None else urllib.request.urlopen

    def is_available(self) -> bool:
        return bool(self._app_id)

    def get_search_links(self, jan_code: str) -> list:
        return _build_search_links(jan_code)

    def fetch_price(self, jan_code: str) -> Optional[PriceInfo]:
        prices = self.fetch_prices(jan_code)
        if not prices:
            return None
        return min(prices, key=lambda p: p.price)

    def fetch_prices(self, jan_code: str) -> List[PriceInfo]:
        """楽天市場APIから該当JANコードの現在販売価格一覧を取得する。

        取得に失敗した場合は `PriceFetchError` を送出する（呼び出し側で
        ハンドルし、一部サイト失敗時の部分表示・再取得導線につなげる）。
        該当商品が0件の場合は空リストを返す（エラーにはしない）。
        """
        if not self.is_available():
            raise PriceFetchError("楽天市場APIは未設定です（RAKUTEN_APP_IDが必要）。")

        # 毎秒1回程度のスロットリング（要件(e)）。
        self._throttle.wait()

        params = {
            "applicationId": self._app_id,
            "keyword": jan_code,
            "hits": config.RAKUTEN_SEARCH_HITS,
            "sort": "+itemPrice",
            "formatVersion": 2,
        }
        url = config.RAKUTEN_API_URL + "?" + urllib.parse.urlencode(params)

        try:
            with self._opener(url, timeout=config.RAKUTEN_API_TIMEOUT_SECONDS) as response:
                body = response.read()
        except Exception as exc:  # noqa: BLE001 - 外部通信起因の例外を包括的に扱う
            raise PriceFetchError(f"楽天市場APIの呼び出しに失敗しました: {exc}") from exc

        try:
            data = json.loads(body)
        except (ValueError, TypeError) as exc:
            raise PriceFetchError("楽天市場APIの応答を解析できませんでした。") from exc

        if isinstance(data, dict) and "error" in data:
            raise PriceFetchError(
                "楽天市場APIがエラーを返しました: " + str(data.get("error_description") or data.get("error"))
            )

        items = data.get("Items", []) if isinstance(data, dict) else []
        prices = []
        for entry in items:
            item = entry.get("Item", entry) if isinstance(entry, dict) else None
            if not item or item.get("itemPrice") is None:
                continue
            prices.append(
                PriceInfo(
                    price=float(item["itemPrice"]),
                    source_name="楽天市場",
                    item_name=str(item.get("itemName", "")),
                    url=str(item.get("itemUrl", "")),
                )
            )
        return prices


class DisabledPriceComparisonSource(PriceSource):
    """RAKUTEN_APP_ID未設定環境用。価格比較機能を無効として扱う。

    アプリ本体（バーコード読み取り・利益計算等）はAPIキーなしでも従来通り
    動作させるため、検索リンク生成のみは引き続きサポートする。
    """

    def is_available(self) -> bool:
        return False

    def get_search_links(self, jan_code: str) -> list:
        return _build_search_links(jan_code)

    def fetch_price(self, jan_code: str) -> Optional[PriceInfo]:
        return None

    def fetch_prices(self, jan_code: str) -> List[PriceInfo]:
        raise PriceFetchError("価格比較機能は無効です（RAKUTEN_APP_IDが未設定）。")


def get_price_comparison_source():
    """横断価格比較機能で使うサーバーサイド価格取得アダプタを返す。

    RAKUTEN_APP_IDが設定されていればRakutenPriceSource、未設定なら
    DisabledPriceComparisonSourceを返す（機能自体を無効化し、アプリ本体は
    APIキーなしで動作する）。
    """
    if os.environ.get("RAKUTEN_APP_ID"):
        return RakutenPriceSource()
    return DisabledPriceComparisonSource()


def summarize_prices(prices: List[PriceInfo]) -> dict:
    """価格一覧（PriceInfoのリスト）から最安値・中央値・件数を算出する。

    中央値は取得できた価格全件を対象に、Python標準の`statistics.median`と
    同じ算出方法（件数が偶数の場合は中央2件の平均、奇数の場合は中央値）で
    計算する。件数0件の場合は lowest/median ともに None を返す。
    """
    values = sorted(p.price for p in prices)
    if not values:
        return {"lowest": None, "median": None, "count": 0}
    return {
        "lowest": values[0],
        "median": statistics.median(values),
        "count": len(values),
    }
