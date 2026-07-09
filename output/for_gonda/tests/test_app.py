# -*- coding: utf-8 -*-
"""
app.py に対する pytest ユニットテスト。
投稿フォームの正常系/異常系、ギャラリー表示順、ファイル名衝突回避、
アップロードフォルダ・DBとの連携を検証する。
"""
import io
import os
import sys
import sqlite3

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module  # noqa: E402


def make_image_bytes():
    """テスト用の最小PNGバイナリ（1x1透明ピクセル）を返す。"""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


@pytest.fixture
def client(tmp_path):
    """
    一時的なDBファイル・アップロードフォルダを使うテスト用クライアントを用意する。
    """
    db_path = tmp_path / "test_album.db"
    upload_folder = tmp_path / "uploads"
    upload_folder.mkdir()

    app_module.app.config["DATABASE_PATH"] = str(db_path)
    app_module.app.config["UPLOAD_FOLDER"] = str(upload_folder)
    app_module.app.config["TESTING"] = True

    app_module.init_db()
    app_module.ensure_upload_folder()

    with app_module.app.test_client() as test_client:
        yield test_client


def post_entry(client, name="山田太郎", message="おめでとう！", filename="photo.png", file_bytes=None, content_type=None):
    data = {
        "name": name,
        "message": message,
    }
    if filename is not None:
        data["photo"] = (
            io.BytesIO(file_bytes if file_bytes is not None else make_image_bytes()),
            filename,
        )
    return client.post("/post", data=data, content_type="multipart/form-data")


# ---------------------------------------------------------------------------
# 正常系
# ---------------------------------------------------------------------------
def test_index_get_empty_gallery(client):
    """投稿が無い状態でトップページが表示できること。"""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "まだ投稿がありません".encode("utf-8") in resp.data


def test_successful_post_creates_entry_and_redirects(client):
    """必須項目が揃っていれば投稿が成功し、トップにリダイレクトされること。"""
    resp = post_entry(client)
    assert resp.status_code == 302
    assert resp.headers["Location"] in ("/", "http://localhost/")

    resp2 = client.get("/")
    assert resp2.status_code == 200
    body = resp2.data.decode("utf-8")
    assert "山田太郎" in body
    assert "おめでとう！" in body


def test_gallery_sorted_newest_first(client):
    """複数投稿がある場合、新着順（新しい投稿が先頭）で表示されること。"""
    post_entry(client, name="Aさん", message="最初の投稿")
    post_entry(client, name="Bさん", message="次の投稿")
    post_entry(client, name="Cさん", message="最後の投稿")

    resp = client.get("/")
    body = resp.data.decode("utf-8")

    pos_a = body.find("Aさん")
    pos_b = body.find("Bさん")
    pos_c = body.find("Cさん")

    assert pos_c < pos_b < pos_a  # 一番新しい投稿(Cさん)が最初に出現する


def test_uploaded_file_saved_in_upload_folder(client):
    """アップロードされた画像がuploadsフォルダに実際に保存されること。"""
    post_entry(client, name="保存テスト", message="ファイル保存確認")

    upload_folder = app_module.app.config["UPLOAD_FOLDER"]
    files = os.listdir(upload_folder)
    assert len(files) == 1
    assert files[0].endswith(".png")


def test_filename_collision_avoided(client):
    """同名ファイルを複数回アップロードしてもファイル名が衝突しないこと。"""
    post_entry(client, name="Xさん", message="1回目", filename="same.png")
    post_entry(client, name="Yさん", message="2回目", filename="same.png")

    upload_folder = app_module.app.config["UPLOAD_FOLDER"]
    files = os.listdir(upload_folder)
    assert len(files) == 2
    assert files[0] != files[1]


def test_db_record_contains_expected_fields(client):
    """DBに投稿者名・メッセージ・ファイル名・投稿日時が正しく記録されること。"""
    post_entry(client, name="DB確認さん", message="DBに記録されるはず")

    conn = sqlite3.connect(app_module.app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM posts ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    assert row["name"] == "DB確認さん"
    assert row["message"] == "DBに記録されるはず"
    assert row["filename"].endswith(".png")
    assert row["timestamp"] is not None and row["timestamp"] != ""


# ---------------------------------------------------------------------------
# 異常系
# ---------------------------------------------------------------------------
def test_post_missing_name_shows_error(client):
    """名前未入力の場合はエラーが表示され、投稿が保存されないこと。"""
    resp = post_entry(client, name="")
    assert resp.status_code == 400
    assert "お名前を入力してください".encode("utf-8") in resp.data

    conn = sqlite3.connect(app_module.app.config["DATABASE_PATH"])
    count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    conn.close()
    assert count == 0


def test_post_missing_message_shows_error(client):
    """メッセージ未入力の場合はエラーが表示され、投稿が保存されないこと。"""
    resp = post_entry(client, message="")
    assert resp.status_code == 400
    assert "お祝いメッセージを入力してください".encode("utf-8") in resp.data


def test_post_missing_file_shows_error(client):
    """写真未選択の場合はエラーが表示され、投稿が保存されないこと。"""
    resp = post_entry(client, filename=None)
    assert resp.status_code == 400
    assert "写真を選択してください".encode("utf-8") in resp.data


def test_post_non_image_file_shows_error(client):
    """画像以外の拡張子ファイルをアップロードした場合はエラーになること。"""
    resp = post_entry(client, filename="virus.exe", file_bytes=b"not an image")
    assert resp.status_code == 400
    assert "jpg/jpeg/png/gif".encode("utf-8") in resp.data

    upload_folder = app_module.app.config["UPLOAD_FOLDER"]
    assert os.listdir(upload_folder) == []


def test_post_all_fields_empty_shows_multiple_errors(client):
    """全項目未入力の場合、複数のエラーメッセージがまとめて表示されること。"""
    resp = post_entry(client, name="", message="", filename=None)
    assert resp.status_code == 400
    body = resp.data.decode("utf-8")
    assert "お名前を入力してください" in body
    assert "お祝いメッセージを入力してください" in body
    assert "写真を選択してください" in body


# ---------------------------------------------------------------------------
# 設定値反映確認
# ---------------------------------------------------------------------------
def test_config_values_reflected_in_page(client):
    """config.py の設定値（サイトタイトル・キャッチコピー）がページに反映されること。"""
    import config

    resp = client.get("/")
    body = resp.data.decode("utf-8")
    assert config.SITE_TITLE in body
    assert config.SITE_CATCHPHRASE in body


def test_allowed_extensions_from_config(client):
    """許可されている拡張子（jpg/jpeg/png/gif）はすべて投稿可能なこと。"""
    for ext in ["jpg", "jpeg", "png", "gif"]:
        resp = post_entry(client, name=f"{ext}さん", message=f"{ext}のテスト", filename=f"photo.{ext}")
        assert resp.status_code == 302, f"{ext} was rejected unexpectedly"
