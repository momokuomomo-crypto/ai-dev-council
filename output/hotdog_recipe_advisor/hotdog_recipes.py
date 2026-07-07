"""ホットドッグの材料データと、好みタグに応じたレシピ選定ロジック。

各材料（パン・ソーセージ・ソース・トッピング）は「tags」という特徴タグの
集合を持つ。ユーザーの回答から得られた好みタグ集合と、各材料のタグの
重なり具合をスコアとして評価し、スコアの高い候補群からランダムに選ぶ
ことで、ロジック（好みへの適合）とランダム性（意外性・バリエーション）
を両立させている。
"""

import random

# パンの種類
BUNS = [
    {
        "name": "定番の白パン",
        "tags": {"classic", "light"},
        "desc": "ふわふわで軽い、昔ながらのホットドッグバンズ。",
    },
    {
        "name": "全粒粉バンズ",
        "tags": {"healthy", "light"},
        "desc": "香ばしくヘルシー志向の人にぴったり。",
    },
    {
        "name": "ブリオッシュバンズ",
        "tags": {"luxury", "rich"},
        "desc": "バターの風味豊かでリッチな味わいの贅沢な一品。",
    },
    {
        "name": "プレッツェルバンズ",
        "tags": {"adventurous", "rich"},
        "desc": "もちっとした食感と塩気が効いた個性的な一品。",
    },
    {
        "name": "コーンブレッドバンズ",
        "tags": {"adventurous", "classic"},
        "desc": "ほんのり甘いアメリカ南部風のバンズ。",
    },
]

# ソーセージの種類
SAUSAGES = [
    {
        "name": "定番フランクフルター",
        "tags": {"classic", "light"},
        "desc": "王道の味わいでどんな組み合わせにも合う万能選手。",
    },
    {
        "name": "スパイシーチョリソー",
        "tags": {"spicy", "adventurous"},
        "desc": "ピリ辛でパンチのある刺激的な味わい。",
    },
    {
        "name": "とろけるチーズ入りソーセージ",
        "tags": {"cheese", "rich"},
        "desc": "中からチーズがとろけ出す濃厚な一本。",
    },
    {
        "name": "ハーブチキンソーセージ",
        "tags": {"healthy", "light"},
        "desc": "鶏肉ベースであっさりヘルシー。",
    },
    {
        "name": "ジューシー牛肉100%ソーセージ",
        "tags": {"luxury", "rich"},
        "desc": "肉々しい満足感のある贅沢な一本。",
    },
]

# ソース
SAUCES = [
    {
        "name": "マスタード",
        "tags": {"classic", "light"},
        "desc": "定番のキリッとした酸味が食欲をそそる。",
    },
    {
        "name": "ケチャップ",
        "tags": {"classic"},
        "desc": "甘みのある誰にでも愛される定番ソース。",
    },
    {
        "name": "チリソース",
        "tags": {"spicy", "adventurous"},
        "desc": "辛さと旨みがクセになる刺激的なソース。",
    },
    {
        "name": "ガーリックマヨネーズ",
        "tags": {"rich", "luxury"},
        "desc": "コクとニンニクの香りが効いた濃厚なソース。",
    },
    {
        "name": "スモーキーBBQソース",
        "tags": {"rich", "adventurous"},
        "desc": "燻製香とスパイスが香ばしいBBQ風味。",
    },
    {
        "name": "アボカドサルサ",
        "tags": {"healthy", "mexican", "adventurous"},
        "desc": "さっぱりとした爽やかな辛味のメキシカンソース。",
    },
]

# トッピング
TOPPINGS = [
    {"name": "刻み玉ねぎ", "tags": {"classic", "light"}, "desc": "シャキシャキとした食感と辛味のアクセント。"},
    {"name": "ザワークラウト", "tags": {"classic", "light"}, "desc": "酸味が効いて味を引き締める定番トッピング。"},
    {"name": "とろけるチーズ", "tags": {"cheese", "rich"}, "desc": "濃厚なコクをプラス。"},
    {"name": "アボカド", "tags": {"healthy", "luxury"}, "desc": "クリーミーで贅沢な満足感。"},
    {"name": "半熟目玉焼き", "tags": {"luxury", "rich"}, "desc": "とろける黄身が贅沢さを演出。"},
    {"name": "コールスロー", "tags": {"light", "healthy"}, "desc": "さっぱりとした野菜の甘みと食感。"},
    {"name": "ハラペーニョ", "tags": {"spicy", "adventurous"}, "desc": "ピリッとした刺激的な辛さ。"},
    {"name": "フライドオニオン", "tags": {"rich", "adventurous"}, "desc": "香ばしくカリカリの食感がクセになる。"},
    {"name": "パクチー", "tags": {"adventurous", "mexican"}, "desc": "独特の香りでエスニックな仕上がりに。"},
]


def _score(item, preference_tags):
    """材料アイテムと好みタグ集合との一致度をスコア化する。"""
    return len(item["tags"] & preference_tags)


def _best_candidates(items, preference_tags):
    """最も好みに一致するスコアを持つ候補アイテムのリストを返す。"""
    if not items:
        return []
    max_score = max(_score(item, preference_tags) for item in items)
    return [item for item in items if _score(item, preference_tags) == max_score]


def pick_one(items, preference_tags, rng):
    """スコア最大の候補群からランダムに1つ選ぶ。"""
    candidates = _best_candidates(items, preference_tags)
    if not candidates:
        return None
    return rng.choice(candidates)


def pick_toppings(preference_tags, rng, count=2, items=None):
    """好みに近い候補を中心に、重複のないトッピングを複数選ぶ。

    上位互換な組み合わせだけに固定しないよう、スコア上位半分程度の
    プール内からランダムサンプリングすることでバリエーションを持たせる。
    """
    pool_items = list(TOPPINGS if items is None else items)
    if not pool_items:
        return []
    scored = sorted(pool_items, key=lambda it: _score(it, preference_tags), reverse=True)
    pool_size = max(count, len(scored) // 2, 1)
    pool = scored[:pool_size]
    n = min(count, len(pool))
    return rng.sample(pool, n)


def generate_recipe(preference_tags=None, rng=None):
    """好みタグ集合を受け取り、パン・ソーセージ・ソース・トッピングの
    組み合わせを1つのレシピ(dict)として返す。

    preference_tags: 好みを表す文字列タグの集合（例: {"spicy", "rich"}）。
                      Noneまたは空集合の場合は全体からランダムに選ばれる。
    rng: 乱数生成器（random.Randomインスタンス）。テストで再現性を
         確保したい場合に指定する。省略時は標準のrandomモジュールを使う。
    """
    tags = set(preference_tags) if preference_tags else set()
    rng = rng or random

    bun = pick_one(BUNS, tags, rng)
    sausage = pick_one(SAUSAGES, tags, rng)
    sauce = pick_one(SAUCES, tags, rng)
    toppings = pick_toppings(tags, rng, count=2)

    return {
        "bun": bun,
        "sausage": sausage,
        "sauce": sauce,
        "toppings": toppings,
        "tags": tags,
    }
