"""アプリ全体の設定値を一元管理するモジュール。

DBパス、デフォルト手数料率、デフォルト送料などをここにまとめる。
"""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# SQLite DBファイルのパス（環境変数で上書き可能。テスト時はテスト側で差し替える）
DATABASE_PATH = os.environ.get("SEDORI_DB_PATH", os.path.join(BASE_DIR, "sedori.db"))

# 商品登録画面の初期値として使うデフォルト手数料率（%）・送料（円）
# 実際の値は settings テーブルに保存され、ここは初回起動時の初期値として使われる。
DEFAULT_FEE_RATE = 10.0  # %
DEFAULT_SHIPPING_COST = 0.0  # 円

# 手数料率の許容範囲（%）
FEE_RATE_MIN = 0.0
FEE_RATE_MAX = 100.0

# JANコード（JAN/EANコード）として許容する桁数
VALID_JAN_LENGTHS = (8, 13)

# Flaskのシークレットキー（flash message等に使用。本番運用時は環境変数で上書きすること）
SECRET_KEY = os.environ.get("SEDORI_SECRET_KEY", "dev-secret-key-change-me")

# 外部ECサイトの検索結果ページURLテンプレート。
# {jan} はJAN/EANコード（または商品名）に置換される。
# ※ここは検索結果ページへのリンク生成のみに使用し、自動取得（API/スクレイピング）は一切行わない。
EC_SEARCH_SITES = [
    {"key": "amazon", "name": "Amazon", "url_template": "https://www.amazon.co.jp/s?k={jan}"},
    {"key": "mercari", "name": "メルカリ", "url_template": "https://jp.mercari.com/search?keyword={jan}"},
    {"key": "yahoo", "name": "Yahoo!ショッピング", "url_template": "https://shopping.yahoo.co.jp/search?p={jan}"},
    {"key": "rakuten", "name": "楽天市場", "url_template": "https://search.rakuten.co.jp/search/mall/{jan}/"},
]

# 免責事項・古物営業法上の注意喚起文（初回表示・設定画面で必須表示）
DISCLAIMER_TEXT = (
    "本アプリは仕入れ判断を支援するための計算補助ツールであり、"
    "表示される損益計算結果や情報の正確性・完全性を保証するものではありません。"
    "実際の仕入れ・販売の可否や価格は、必ずご自身の責任で各ECサイト・店舗等の"
    "最新情報をご確認の上、判断してください。本アプリの利用によって生じたいかなる損害についても、"
    "開発者は一切の責任を負いません。"
)

KOBUTSU_NOTICE_TEXT = (
    "中古品の仕入れ・販売を継続的に営利目的で行う場合、古物営業法に基づき、"
    "営業所を管轄する都道府県公安委員会（警察署）から古物商許可を取得する必要があります。"
    "無許可での古物営業は法律により罰せられる場合があります。せどり・転売を行う際は、"
    "対象となる商品や取引形態が古物営業法の適用対象かどうかを事前にご確認ください。"
)
