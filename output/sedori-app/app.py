"""せどり仕入れ判断支援アプリ（MVP） Flaskメインアプリケーション。

ルーティング、DB操作、利益計算、APIハンドラをまとめて実装する。
"""

import sqlite3
from datetime import datetime, timezone

from flask import Flask, flash, g, jsonify, redirect, render_template, request, url_for

import config
from adapters.price_source import get_price_source

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


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
