"""せどり仕入れ判断支援アプリ（MVP） Flaskメインアプリケーション。

ルーティング、DB操作、利益計算、APIハンドラをまとめて実装する。
"""

import os
import sqlite3
from datetime import datetime, timezone

from flask import Flask, flash, g, jsonify, redirect, render_template, request, url_for

try:
    # 画像判別機能用のANTHROPIC_API_KEYを.envから読み込む（任意）。
    # python-dotenv未導入・.envなしでもアプリ本体は動作する。
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import config
from adapters.price_source import PriceFetchError, get_price_comparison_source, get_price_source, summarize_prices
from adapters.product_identifier import get_product_identifier

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["DATABASE_PATH"] = config.DATABASE_PATH


# ---------------------------------------------------------------------------
# DB関連
# ---------------------------------------------------------------------------

def get_db():
    """リクエストコンテキスト内で使い回すDBコネクションを取得する。"""
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(database_path=None):
    """テーブルを作成し、設定行が無ければデフォルト値で作成する。"""
    path = database_path or app.config["DATABASE_PATH"]
    db = sqlite3.connect(path)
    try:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                jan_code TEXT NOT NULL,
                name TEXT NOT NULL,
                purchase_price REAL NOT NULL,
                selling_price REAL NOT NULL,
                fee_rate REAL NOT NULL,
                shipping_cost REAL NOT NULL,
                profit REAL NOT NULL,
                profit_margin REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                default_fee_rate REAL NOT NULL,
                default_shipping_cost REAL NOT NULL,
                kobutsu_license_number TEXT
            )
            """
        )
        existing = db.execute("SELECT id FROM settings WHERE id = 1").fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO settings (id, default_fee_rate, default_shipping_cost, "
                "kobutsu_license_number) VALUES (1, ?, ?, ?)",
                (config.DEFAULT_FEE_RATE, config.DEFAULT_SHIPPING_COST, None),
            )
        db.commit()
    finally:
        db.close()


def get_settings():
    """現在の設定値を dict で返す。"""
    db = get_db()
    row = db.execute(
        "SELECT default_fee_rate, default_shipping_cost, kobutsu_license_number "
        "FROM settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return {
            "default_fee_rate": config.DEFAULT_FEE_RATE,
            "default_shipping_cost": config.DEFAULT_SHIPPING_COST,
            "kobutsu_license_number": "",
        }
    return {
        "default_fee_rate": row["default_fee_rate"],
        "default_shipping_cost": row["default_shipping_cost"],
        "kobutsu_license_number": row["kobutsu_license_number"] or "",
    }


# ---------------------------------------------------------------------------
# 利益計算ロジック（要件の計算式を厳守）
# ---------------------------------------------------------------------------

def calculate_profit(selling_price, fee_rate, shipping_cost, purchase_price):
    """利益・利益率を計算する。

    利益 = 想定売価 × (1 - 手数料率/100) - 送料 - 仕入れ価格
    利益率(%) = 利益 / 想定売価 × 100 (想定売価が0以下の場合は0とする)
    """
    profit = selling_price * (1 - fee_rate / 100) - shipping_cost - purchase_price
    if selling_price and selling_price > 0:
        profit_margin = profit / selling_price * 100
    else:
        profit_margin = 0.0
    return profit, profit_margin


# ---------------------------------------------------------------------------
# バリデーション
# ---------------------------------------------------------------------------

def _parse_float(value):
    """文字列をfloatに変換する。変換できない場合はNoneを返す。"""
    if value is None:
        return None
    value = str(value).strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def validate_product_data(form):
    """商品登録フォームの入力値を検証する。

    戻り値: (errors: dict, cleaned: dict or None)
    どれか一つでもエラーがあれば cleaned は None にする。
    """
    errors = {}

    jan_code = (form.get("jan_code") or "").strip()
    name = (form.get("name") or "").strip()

    purchase_price = _parse_float(form.get("purchase_price"))
    selling_price = _parse_float(form.get("selling_price"))
    fee_rate = _parse_float(form.get("fee_rate"))
    shipping_cost = _parse_float(form.get("shipping_cost"))

    if not jan_code:
        errors["jan_code"] = "JANコード（バーコード）を入力してください。"
    elif not jan_code.isdigit():
        errors["jan_code"] = "JANコードは数字のみで入力してください。"
    elif len(jan_code) not in config.VALID_JAN_LENGTHS:
        errors["jan_code"] = "JANコードは8桁または13桁の数字で入力してください。"

    if not name:
        errors["name"] = "商品名を入力してください。"

    if purchase_price is None:
        errors["purchase_price"] = "仕入れ価格を数値で入力してください。"
    elif purchase_price < 0:
        errors["purchase_price"] = "仕入れ価格に負の値は入力できません。"

    if selling_price is None:
        errors["selling_price"] = "想定売価を数値で入力してください。"
    elif selling_price <= 0:
        errors["selling_price"] = "想定売価は0より大きい値を入力してください。"

    if fee_rate is None:
        errors["fee_rate"] = "手数料率を数値で入力してください。"
    elif fee_rate < config.FEE_RATE_MIN or fee_rate > config.FEE_RATE_MAX:
        errors["fee_rate"] = (
            f"手数料率は{config.FEE_RATE_MIN}〜{config.FEE_RATE_MAX}の範囲で入力してください。"
        )

    if shipping_cost is None:
        errors["shipping_cost"] = "送料を数値で入力してください。"
    elif shipping_cost < 0:
        errors["shipping_cost"] = "送料に負の値は入力できません。"

    if errors:
        return errors, None

    cleaned = {
        "jan_code": jan_code,
        "name": name,
        "purchase_price": purchase_price,
        "selling_price": selling_price,
        "fee_rate": fee_rate,
        "shipping_cost": shipping_cost,
    }
    return errors, cleaned


def validate_settings_data(form):
    """設定画面フォームの入力値を検証する。"""
    errors = {}

    default_fee_rate = _parse_float(form.get("default_fee_rate"))
    default_shipping_cost = _parse_float(form.get("default_shipping_cost"))
    kobutsu_license_number = (form.get("kobutsu_license_number") or "").strip()

    if default_fee_rate is None:
        errors["default_fee_rate"] = "デフォルト手数料率を数値で入力してください。"
    elif default_fee_rate < config.FEE_RATE_MIN or default_fee_rate > config.FEE_RATE_MAX:
        errors["default_fee_rate"] = (
            f"デフォルト手数料率は{config.FEE_RATE_MIN}〜{config.FEE_RATE_MAX}の範囲で入力してください。"
        )

    if default_shipping_cost is None:
        errors["default_shipping_cost"] = "デフォルト送料を数値で入力してください。"
    elif default_shipping_cost < 0:
        errors["default_shipping_cost"] = "デフォルト送料に負の値は入力できません。"

    if errors:
        return errors, None

    cleaned = {
        "default_fee_rate": default_fee_rate,
        "default_shipping_cost": default_shipping_cost,
        # 古物商許可番号は任意入力
        "kobutsu_license_number": kobutsu_license_number,
    }
    return errors, cleaned


# ---------------------------------------------------------------------------
# 横断価格比較機能（楽天市場API・Yahoo!ショッピングAPI）関連のヘルパー
# ---------------------------------------------------------------------------

def _price_comparison_context():
    """商品登録・利益計算画面（index.html）で使う価格比較関連の描画コンテキスト。

    楽天市場APIはサーバー側で有効/無効を判定して渡す。Yahoo!ショッピングAPIは
    ブラウザ側から直接呼び出す構成のため、Client IDと呼び出し先URLのみを
    テンプレート経由でJSへ渡す（未設定ならJS側で機能を無効化しリンク提示に
    フォールバックする）。
    """
    comparison_source = get_price_comparison_source()
    return {
        "price_comparison_disclaimer_text": config.PRICE_COMPARISON_DISCLAIMER_TEXT,
        "rakuten_enabled": comparison_source.is_available(),
        "yahoo_client_id": os.environ.get("YAHOO_CLIENT_ID") or "",
        "yahoo_api_url": config.YAHOO_SHOPPING_API_URL,
        "yahoo_search_results": config.YAHOO_SEARCH_RESULTS,
    }


# ---------------------------------------------------------------------------
# ルーティング
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    settings = get_settings()
    price_source = get_price_source()
    search_links = price_source.get_search_links("")
    return render_template(
        "index.html",
        settings=settings,
        search_links=search_links,
        ec_sites=config.EC_SEARCH_SITES,
        disclaimer_text=config.DISCLAIMER_TEXT,
        kobutsu_notice_text=config.KOBUTSU_NOTICE_TEXT,
        errors={},
        form_values={},
        **_price_comparison_context(),
    )


@app.route("/products", methods=["GET"])
def product_list():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM products ORDER BY datetime(created_at) DESC, id DESC"
    ).fetchall()
    return render_template("list.html", products=rows)


@app.route("/products", methods=["POST"])
def product_create():
    errors, cleaned = validate_product_data(request.form)
    settings = get_settings()

    if errors:
        price_source = get_price_source()
        search_links = price_source.get_search_links(request.form.get("jan_code", ""))
        return render_template(
            "index.html",
            settings=settings,
            search_links=search_links,
            ec_sites=config.EC_SEARCH_SITES,
            disclaimer_text=config.DISCLAIMER_TEXT,
            kobutsu_notice_text=config.KOBUTSU_NOTICE_TEXT,
            errors=errors,
            form_values=request.form,
            **_price_comparison_context(),
        ), 400

    profit, profit_margin = calculate_profit(
        cleaned["selling_price"],
        cleaned["fee_rate"],
        cleaned["shipping_cost"],
        cleaned["purchase_price"],
    )

    db = get_db()
    db.execute(
        """
        INSERT INTO products
            (jan_code, name, purchase_price, selling_price, fee_rate,
             shipping_cost, profit, profit_margin, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cleaned["jan_code"],
            cleaned["name"],
            cleaned["purchase_price"],
            cleaned["selling_price"],
            cleaned["fee_rate"],
            cleaned["shipping_cost"],
            profit,
            profit_margin,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    db.commit()
    flash("商品を登録しました。", "success")
    return redirect(url_for("product_list"))


@app.route("/products/<int:product_id>/delete", methods=["POST"])
def product_delete(product_id):
    db = get_db()
    db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()
    flash("商品を削除しました。", "success")
    return redirect(url_for("product_list"))


@app.route("/settings", methods=["GET"])
def settings_view():
    settings = get_settings()
    return render_template(
        "settings.html",
        settings=settings,
        errors={},
        disclaimer_text=config.DISCLAIMER_TEXT,
        kobutsu_notice_text=config.KOBUTSU_NOTICE_TEXT,
    )


@app.route("/settings", methods=["POST"])
def settings_update():
    errors, cleaned = validate_settings_data(request.form)
    if errors:
        merged_settings = {
            "default_fee_rate": request.form.get("default_fee_rate", ""),
            "default_shipping_cost": request.form.get("default_shipping_cost", ""),
            "kobutsu_license_number": request.form.get("kobutsu_license_number", ""),
        }
        return render_template(
            "settings.html",
            settings=merged_settings,
            errors=errors,
            disclaimer_text=config.DISCLAIMER_TEXT,
            kobutsu_notice_text=config.KOBUTSU_NOTICE_TEXT,
        ), 400

    db = get_db()
    db.execute(
        """
        UPDATE settings
        SET default_fee_rate = ?, default_shipping_cost = ?, kobutsu_license_number = ?
        WHERE id = 1
        """,
        (
            cleaned["default_fee_rate"],
            cleaned["default_shipping_cost"],
            cleaned["kobutsu_license_number"] or None,
        ),
    )
    db.commit()
    flash("設定を更新しました。", "success")
    return redirect(url_for("settings_view"))


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    """商品登録画面での即時計算用API。

    サーバー側で利益計算式を評価し、結果をJSONで返す。
    入力値が不正な場合はエラーメッセージを返す（保存は行わない）。
    """
    data = request.get_json(silent=True) or request.form

    purchase_price = _parse_float(data.get("purchase_price"))
    selling_price = _parse_float(data.get("selling_price"))
    fee_rate = _parse_float(data.get("fee_rate"))
    shipping_cost = _parse_float(data.get("shipping_cost"))

    errors = {}
    if purchase_price is None or purchase_price < 0:
        errors["purchase_price"] = "仕入れ価格が不正です。"
    if selling_price is None or selling_price <= 0:
        errors["selling_price"] = "想定売価が不正です。"
    if fee_rate is None or fee_rate < config.FEE_RATE_MIN or fee_rate > config.FEE_RATE_MAX:
        errors["fee_rate"] = "手数料率が不正です。"
    if shipping_cost is None or shipping_cost < 0:
        errors["shipping_cost"] = "送料が不正です。"

    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    profit, profit_margin = calculate_profit(
        selling_price, fee_rate, shipping_cost, purchase_price
    )
    return jsonify(
        {
            "ok": True,
            "profit": round(profit, 2),
            "profit_margin": round(profit_margin, 2),
        }
    )


# WSGI経由（PythonAnywhere等）でapp.pyがimportされる場合、
# `if __name__ == "__main__":` は実行されないため、DB初期化は
# モジュール読み込み時に行う（CREATE TABLE IF NOT EXISTSなので
# 複数回呼ばれても問題ない）。baby-albumデプロイ時に確認済みのパターン。
init_db()


@app.route("/api/prices", methods=["GET"])
def api_prices():
    """横断価格比較機能: 楽天市場APIの現在販売価格一覧を返すAPI。

    Yahoo!ショッピングAPIはPythonAnywhere無料プランのホワイトリストに
    shopping.yahooapis.jp が含まれないため、ブラウザ側（JS）から直接
    呼び出す構成とし、本エンドポイントでは扱わない。
    RAKUTEN_APP_ID未設定の環境では503を返し、機能ボタン以外のアプリ本体
    には影響しない。取得失敗時（一部サイト失敗を含む）は502を返し、
    フロント側で再取得を促す表示につなげる。
    """
    jan_code = (request.args.get("jan") or "").strip()
    if not jan_code:
        return jsonify({"ok": False, "error": "JANコードを指定してください。"}), 400

    comparison_source = get_price_comparison_source()
    if not comparison_source.is_available():
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "価格比較機能は未設定です（サーバーにRAKUTEN_APP_IDの設定が必要）。",
                    "disabled": True,
                }
            ),
            503,
        )

    try:
        prices = comparison_source.fetch_prices(jan_code)
    except PriceFetchError as exc:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": str(exc) or "楽天市場の価格取得に失敗しました。時間をおいて再取得してください。",
                }
            ),
            502,
        )

    summary = summarize_prices(prices)
    return jsonify(
        {
            "ok": True,
            "rakuten": {
                "prices": [p.to_dict() for p in prices],
                "lowest": summary["lowest"],
                "median": summary["median"],
                "count": summary["count"],
            },
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.route("/api/identify", methods=["POST"])
def api_identify():
    """写真からの商品判別API（補助機能）。

    multipart/form-data の `photo` フィールドで画像を受け取り、
    商品名候補（最大3件）をJSONで返す。判別1回ごとにClaude APIの
    課金が発生する。ANTHROPIC_API_KEY未設定の環境では503を返す
    （アプリ本体の機能には影響しない）。
    """
    identifier = get_product_identifier()
    if not identifier.is_available():
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "画像判別機能は未設定です（サーバーにANTHROPIC_API_KEYの設定が必要）。",
                }
            ),
            503,
        )

    photo = request.files.get("photo")
    if photo is None or photo.filename == "":
        return jsonify({"ok": False, "error": "写真が選択されていません。"}), 400

    media_type = photo.mimetype
    if media_type not in config.IDENTIFY_ALLOWED_MEDIA_TYPES:
        return (
            jsonify({"ok": False, "error": "対応していない画像形式です（jpg/png/webp/gif）。"}),
            400,
        )

    image_bytes = photo.read(config.IDENTIFY_MAX_IMAGE_BYTES + 1)
    if len(image_bytes) > config.IDENTIFY_MAX_IMAGE_BYTES:
        return jsonify({"ok": False, "error": "画像サイズが大きすぎます（5MBまで）。"}), 400
    if not image_bytes:
        return jsonify({"ok": False, "error": "画像が空です。"}), 400

    try:
        candidates = identifier.identify(image_bytes, media_type)
    except Exception:
        return (
            jsonify({"ok": False, "error": "判別に失敗しました。時間をおいて再度お試しください。"}),
            502,
        )

    return jsonify({"ok": True, "candidates": candidates})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
