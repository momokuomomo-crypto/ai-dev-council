"""価格取得アダプタの抽象基底クラスと、MVPで利用する手動入力アダプタ。

将来的にECサイトのAPI連携やスクレイピングによる自動価格取得を追加する場合は、
`PriceSource` を継承した新しいアダプタクラス（例: AmazonApiPriceSource）を追加し、
`get_price_source()` の切り替え先を増やすことでフックできる設計にしている。

MVP時点では自動取得（API・スクレイピング・画像認識）は一切実装せず、
`ManualInputPriceSource` はユーザーの手入力のみを前提とし、価格自動取得は常に
「未対応（None）」を返す。あわせて、外部ECサイトの検索結果ページへのリンクを
生成するユーティリティを提供する（自動取得は行わない）。
"""

from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import quote

from config import EC_SEARCH_SITES


class PriceInfo:
    """価格情報を表す単純なデータクラス。"""

    def __init__(self, price: float, source_name: str):
        self.price = price
        self.source_name = source_name

    def to_dict(self):
        return {"price": self.price, "source_name": self.source_name}


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


class ManualInputPriceSource(PriceSource):
    """MVPで利用する「手動入力アダプタ」。

    価格の自動取得は一切行わず、常に None を返す（ユーザーが手動で入力する前提）。
    検索リンクの生成のみサポートする。
    """

    def fetch_price(self, jan_code: str) -> Optional[PriceInfo]:
        # MVPでは自動取得は行わない仕様のため、常に None（未対応）を返す。
        return None

    def get_search_links(self, jan_code: str) -> list:
        links = []
        query = quote(jan_code or "")
        for site in EC_SEARCH_SITES:
            url = site["url_template"].format(jan=query)
            links.append({"key": site["key"], "name": site["name"], "url": url})
        return links


def get_price_source() -> PriceSource:
    """現在使用する価格取得アダプタを返す（MVPでは手動入力アダプタ固定）。"""
    return ManualInputPriceSource()
