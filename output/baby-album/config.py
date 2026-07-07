# -*- coding: utf-8 -*-
"""
サイト固有の設定を一元管理するモジュール。
赤ちゃんの名前・サイトタイトル・キャッチコピー・テーマカラーなど、
サイトの見た目/文言に関わる情報はすべてここに集約する。
app.py / templates からはこのモジュールの定数を import して参照する。
"""

# ==== 赤ちゃん/サイト情報 ====
BABY_NAME = "ひまり"
SITE_TITLE = f"{BABY_NAME}ちゃん誕生おめでとうアルバム"
SITE_CATCHPHRASE = "みんなの写真とメッセージで、誕生をお祝いしよう！"

# ==== テーマカラー（パステルイエロー × ミント） ====
THEME_COLOR_PRIMARY = "#FFF6B7"      # パステルイエロー（背景系）
THEME_COLOR_SECONDARY = "#B8F2E6"    # パステルミント（アクセント系）
THEME_COLOR_ACCENT = "#FFD97D"       # 濃いめイエロー（ボタン等）
THEME_COLOR_TEXT = "#4A4A4A"         # 基本文字色

# ==== アップロード関連設定 ====
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif"}
MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8MB

# ==== DB設定 ====
DATABASE_PATH = "album.db"

# ==== その他 ====
MAX_NAME_LENGTH = 50
MAX_MESSAGE_LENGTH = 1000
