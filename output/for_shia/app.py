# -*- coding: utf-8 -*-
"""
赤ちゃん誕生祝いアルバムサイト本体。
ルーティング・DB制御・ファイルアップロード・バリデーション・ギャラリー表示・
設定読込など、全ロジックをここに集約するシンプルなFlaskアプリ。
"""
import os
import sqlite3
import uuid
from datetime import datetime

from flask import (
    Flask,
    g,
    render_template,
    request,
    redirect,
    url_for,
    send_from_directory,
)

import config

app = Flask(__name__)

# config.py の値を app.config に取り込み、以降は app.config 経由で参照する
# （テスト時に app.config を書き換えることで、DBパスやアップロード先を差し替え可能にする）
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
app.config["ALLOWED_EXTENSIONS"] = config.ALLOWED_EXTENSIONS
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
app.config["DATABASE_PATH"] = config.DATABASE_PATH
app.config["MAX_NAME_LENGTH"] = config.MAX_NAME_LENGTH
app.config["MAX_MESSAGE_LENGTH"] = config.MAX_MESSAGE_LENGTH

# WSGI経由（PythonAnywhere等）でapp.pyがimportされる場合、
# `if __name__ == "__main__":` は実行されないため、DB初期化・
# アップロードフォルダ作成はモジュール読み込み時に行う
# （CREATE TABLE IF NOT EXISTS / os.makedirs(exist_ok=True)なので
# 複数回呼ばれても問題ない）。


# ---------------------------------------------------------------------------
# DB関連
# ---------------------------------------------------------------------------
def get_db():
    """リクエストコンテキストごとのDBコネクションを取得する。"""
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """postsテーブルを作成する（存在しない場合のみ）。"""
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                message TEXT NOT NULL,
                filename TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def ensure_upload_folder():
    folder = app.config["UPLOAD_FOLDER"]
    if not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)


# モジュール読み込み時に一度実行しておく（WSGI経由でも確実に初期化するため）
init_db()
ensure_upload_folder()


# ---------------------------------------------------------------------------
# バリデーション関連
# ---------------------------------------------------------------------------
def allowed_file(filename):
    """拡張子が許可されている画像種別かどうかを判定する。"""
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in app.config["ALLOWED_EXTENSIONS"]


def validate_post(name, message, file):
    """
    投稿内容を検証し、エラーメッセージのリストを返す。
    空リストの場合はバリデーションOK。
    """
    errors = []

    if not name or not name.strip():
        errors.append("お名前を入力してください。")
    elif len(name.strip()) > app.config["MAX_NAME_LENGTH"]:
        errors.append(f"お名前は{app.config['MAX_NAME_LENGTH']}文字以内で入力してください。")

    if not message or not message.strip():
        errors.append("お祝いメッセージを入力してください。")
    elif len(message.strip()) > app.config["MAX_MESSAGE_LENGTH"]:
        errors.append(f"メッセージは{app.config['MAX_MESSAGE_LENGTH']}文字以内で入力してください。")

    if file is None or file.filename == "":
        errors.append("写真を選択してください。")
    elif not allowed_file(file.filename):
        errors.append("写真はjpg/jpeg/png/gif形式のファイルのみアップロードできます。")

    return errors


def make_unique_filename(original_filename):
    """投稿タイムスタンプ＋ランダムIDを付加し、衝突を避けたファイル名を生成する。"""
    ext = original_filename.rsplit(".", 1)[1].lower()
    timestamp_part = datetime.now().strftime("%Y%m%d%H%M%S%f")
    random_part = uuid.uuid4().hex[:8]
    return f"{timestamp_part}_{random_part}.{ext}"


# ---------------------------------------------------------------------------
# ルーティング
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    db = get_db()
    posts = db.execute(
        "SELECT id, name, message, filename, timestamp FROM posts ORDER BY id DESC"
    ).fetchall()
    return render_template("index.html", posts=posts, errors=[], form_data={}, config=config)


@app.route("/post", methods=["POST"])
def create_post():
    name = request.form.get("name", "")
    message = request.form.get("message", "")
    file = request.files.get("photo")

    errors = validate_post(name, message, file)

    if errors:
        db = get_db()
        posts = db.execute(
            "SELECT id, name, message, filename, timestamp FROM posts ORDER BY id DESC"
        ).fetchall()
        form_data = {"name": name, "message": message}
        return render_template(
            "index.html", posts=posts, errors=errors, form_data=form_data, config=config
        ), 400

    ensure_upload_folder()
    saved_filename = make_unique_filename(file.filename)
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], saved_filename))

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db = get_db()
    db.execute(
        "INSERT INTO posts (name, message, filename, timestamp) VALUES (?, ?, ?, ?)",
        (name.strip(), message.strip(), saved_filename, timestamp),
    )
    db.commit()

    return redirect(url_for("index"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


if __name__ == "__main__":
    init_db()
    ensure_upload_folder()
    app.run(debug=True)
