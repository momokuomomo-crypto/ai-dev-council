"""pytestによる自動テスト。

カバー範囲:
1. 利益計算式（正常系・手数料率/送料パターン）
2. 商品登録 -> 一覧 -> 削除の一連の流れ
3. 異常値（負の値・空欄・不正JANコード等）でエラーとなり保存されないこと
4. 設定画面での変更が登録画面の初期値に反映されること
5. ECサイトへの検索リンクが要件通りの形式であり、自動取得（スクレイピング）を
   行っていないこと
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module  # noqa: E402
from adapters.price_source import ManualInputPriceSource  # noqa: E402


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test_sedori.db"
    app_module.app.config["DATABASE_PATH"] = str(db_path)
    app_module.app.config["TESTING"] = True
    app_module.init_db(str(db_path))

    with app_module.app.test_client() as test_client:
        yield test_client


def create_product(client, **overrides):
    payload = {
        "jan_code": "4901234567894",
        "name": "テスト商品",
        "purchase_price": "1000",
        "selling_price": "2000",
        "fee_rate": "10",
        "shipping_cost": "100",
    }
    payload.update(overrides)
    return client.post("/products", data=payload, follow_redirects=False)


# ---------------------------------------------------------------------------
# 1. 利益計算式のテスト
# ---------------------------------------------------------------------------

class TestCalculateProfit:
    def test_basic_case(self):
        # 利益 = 2000 * (1 - 10/100) - 100 - 1000 = 1800 - 100 - 1000 = 700
        profit, margin = app_module.calculate_profit(
            selling_price=2000, fee_rate=10, shipping_cost=100, purchase_price=1000
        )
        assert profit == pytest.approx(700.0)
        assert margin == pytest.approx(700.0 / 2000 * 100)

    def test_zero_fee_and_shipping(self):
        profit, margin = app_module.calculate_profit(
            selling_price=1500, fee_rate=0, shipping_cost=0, purchase_price=500
        )
        assert profit == pytest.approx(1000.0)
        assert margin == pytest.approx(1000.0 / 1500 * 100)

    def test_high_fee_rate(self):
        profit, margin = app_module.calculate_profit(
            selling_price=3000, fee_rate=50, shipping_cost=200, purchase_price=800
        )
        # 3000 * 0.5 - 200 - 800 = 1500 - 200 - 800 = 500
        assert profit == pytest.approx(500.0)
        assert margin == pytest.approx(500.0 / 3000 * 100)

    def test_negative_profit_case(self):
        # 仕入れ・送料・手数料が高く赤字になるケースも正しく計算できること
        profit, margin = app_module.calculate_profit(
            selling_price=1000, fee_rate=20, shipping_cost=300, purchase_price=900
        )
        # 1000*0.8 - 300 - 900 = 800 - 300 - 900 = -400
        assert profit == pytest.approx(-400.0)
        assert margin == pytest.approx(-400.0 / 1000 * 100)

    def test_hundred_percent_fee_rate(self):
        profit, margin = app_module.calculate_profit(
            selling_price=1000, fee_rate=100, shipping_cost=0, purchase_price=100
        )
        # 1000*0 - 0 - 100 = -100
        assert profit == pytest.approx(-100.0)
        assert margin == pytest.approx(-10.0)

    def test_decimal_values(self):
        profit, margin = app_module.calculate_profit(
            selling_price=1980.5, fee_rate=12.5, shipping_cost=150.25, purchase_price=999.75
        )
        expected_profit = 1980.5 * (1 - 12.5 / 100) - 150.25 - 999.75
        assert profit == pytest.approx(expected_profit)
        assert margin == pytest.approx(expected_profit / 1980.5 * 100)


# ---------------------------------------------------------------------------
# 2. 商品登録 -> 一覧 -> 削除の流れ
# ---------------------------------------------------------------------------

class TestProductFlow:
    def test_index_page_loads(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "商品登録".encode("utf-8") in res.data or "商品登録・利益計算".encode("utf-8") in res.data

    def test_create_product_success_redirects_to_list(self, client):
        res = create_product(client)
        assert res.status_code == 302
        assert res.headers["Location"].endswith("/products")

    def test_created_product_appears_in_list(self, client):
        create_product(client, name="ユニークテスト商品", jan_code="4912345678904")
        res = client.get("/products")
        assert res.status_code == 200
        assert "ユニークテスト商品".encode("utf-8") in res.data
        assert b"4912345678904" in res.data

    def test_created_product_has_correct_profit_stored(self, client):
        create_product(
            client,
            purchase_price="1000",
            selling_price="2000",
            fee_rate="10",
            shipping_cost="100",
        )
        with app_module.app.app_context():
            conn = app_module.get_db()
            row = conn.execute("SELECT * FROM products").fetchone()
        assert row is not None
        assert row["profit"] == pytest.approx(700.0)
        assert row["profit_margin"] == pytest.approx(35.0)

    def test_delete_product_removes_it_from_list(self, client):
        create_product(client, name="削除対象商品", jan_code="4900000000000")
        with app_module.app.app_context():
            conn = app_module.get_db()
            row = conn.execute(
                "SELECT id FROM products WHERE name = ?", ("削除対象商品",)
            ).fetchone()
        product_id = row["id"]

        res = client.post(f"/products/{product_id}/delete", follow_redirects=False)
        assert res.status_code == 302

        list_res = client.get("/products")
        assert "削除対象商品".encode("utf-8") not in list_res.data

    def test_empty_list_shows_message(self, client):
        res = client.get("/products")
        assert "まだ登録された商品がありません".encode("utf-8") in res.data


# ---------------------------------------------------------------------------
# 3. 異常系（負の値・空欄・不正JAN等）のテスト
# ---------------------------------------------------------------------------

class TestValidationErrors:
    def _count_products(self):
        with app_module.app.app_context():
            conn = app_module.get_db()
            return conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]

    def test_negative_purchase_price_rejected(self, client):
        res = create_product(client, purchase_price="-500")
        assert res.status_code == 400
        assert self._count_products() == 0
        assert "負の値".encode("utf-8") in res.data or "エラー".encode("utf-8") in res.data

    def test_negative_shipping_cost_rejected(self, client):
        res = create_product(client, shipping_cost="-10")
        assert res.status_code == 400
        assert self._count_products() == 0

    def test_zero_or_negative_selling_price_rejected(self, client):
        res = create_product(client, selling_price="0")
        assert res.status_code == 400
        assert self._count_products() == 0

    def test_empty_name_rejected(self, client):
        res = create_product(client, name="")
        assert res.status_code == 400
        assert self._count_products() == 0

    def test_empty_jan_code_rejected(self, client):
        res = create_product(client, jan_code="")
        assert res.status_code == 400
        assert self._count_products() == 0

    def test_non_numeric_jan_code_rejected(self, client):
        res = create_product(client, jan_code="ABCDEFGHIJKLM")
        assert res.status_code == 400
        assert self._count_products() == 0

    def test_wrong_length_jan_code_rejected(self, client):
        res = create_product(client, jan_code="12345")
        assert res.status_code == 400
        assert self._count_products() == 0

    def test_fee_rate_over_100_rejected(self, client):
        res = create_product(client, fee_rate="150")
        assert res.status_code == 400
        assert self._count_products() == 0

    def test_fee_rate_negative_rejected(self, client):
        res = create_product(client, fee_rate="-5")
        assert res.status_code == 400
        assert self._count_products() == 0

    def test_non_numeric_price_rejected(self, client):
        res = create_product(client, purchase_price="abc")
        assert res.status_code == 400
        assert self._count_products() == 0

    def test_valid_boundary_jan_8_digits_accepted(self, client):
        res = create_product(client, jan_code="12345678")
        assert res.status_code == 302
        assert self._count_products() == 1

    def test_valid_boundary_jan_13_digits_accepted(self, client):
        res = create_product(client, jan_code="1234567890123")
        assert res.status_code == 302
        assert self._count_products() == 1

    def test_api_calculate_rejects_negative_values(self, client):
        res = client.post(
            "/api/calculate",
            json={
                "purchase_price": "-1",
                "selling_price": "1000",
                "fee_rate": "10",
                "shipping_cost": "0",
            },
        )
        assert res.status_code == 400
        data = res.get_json()
        assert data["ok"] is False
        assert "purchase_price" in data["errors"]

    def test_api_calculate_valid_returns_profit(self, client):
        res = client.post(
            "/api/calculate",
            json={
                "purchase_price": "1000",
                "selling_price": "2000",
                "fee_rate": "10",
                "shipping_cost": "100",
            },
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["ok"] is True
        assert data["profit"] == pytest.approx(700.0)
        assert data["profit_margin"] == pytest.approx(35.0)


# ---------------------------------------------------------------------------
# 4. 設定画面変更 -> 登録画面の初期値への反映
# ---------------------------------------------------------------------------

class TestSettingsReflection:
    def test_settings_page_loads(self, client):
        res = client.get("/settings")
        assert res.status_code == 200
        assert "デフォルト手数料率".encode("utf-8") in res.data

    def test_settings_update_changes_index_defaults(self, client):
        res = client.post(
            "/settings",
            data={
                "default_fee_rate": "15.5",
                "default_shipping_cost": "300",
                "kobutsu_license_number": "東京都公安委員会 第123456789012号",
            },
            follow_redirects=False,
        )
        assert res.status_code == 302

        index_res = client.get("/")
        assert b'value="15.5"' in index_res.data
        assert b'value="300.0"' in index_res.data or b'value="300"' in index_res.data

    def test_settings_reflected_on_settings_page(self, client):
        client.post(
            "/settings",
            data={
                "default_fee_rate": "8",
                "default_shipping_cost": "50",
                "kobutsu_license_number": "",
            },
        )
        res = client.get("/settings")
        assert b'value="8.0"' in res.data

    def test_settings_negative_fee_rate_rejected(self, client):
        res = client.post(
            "/settings",
            data={
                "default_fee_rate": "-1",
                "default_shipping_cost": "0",
                "kobutsu_license_number": "",
            },
        )
        assert res.status_code == 400

    def test_settings_fee_rate_over_100_rejected(self, client):
        res = client.post(
            "/settings",
            data={
                "default_fee_rate": "200",
                "default_shipping_cost": "0",
                "kobutsu_license_number": "",
            },
        )
        assert res.status_code == 400

    def test_settings_negative_shipping_cost_rejected(self, client):
        res = client.post(
            "/settings",
            data={
                "default_fee_rate": "10",
                "default_shipping_cost": "-1",
                "kobutsu_license_number": "",
            },
        )
        assert res.status_code == 400

    def test_disclaimer_and_kobutsu_notice_shown_on_settings(self, client):
        res = client.get("/settings")
        assert "免責事項".encode("utf-8") in res.data
        assert "古物営業法".encode("utf-8") in res.data

    def test_disclaimer_shown_on_index(self, client):
        res = client.get("/")
        assert "古物営業法".encode("utf-8") in res.data


# ---------------------------------------------------------------------------
# 5. ECサイト検索リンクのテスト（自動取得を行っていないことの確認含む）
# ---------------------------------------------------------------------------

class TestEcSearchLinks:
    def test_manual_price_source_never_fetches_price(self):
        source = ManualInputPriceSource()
        # 自動価格取得は一切行わず、常に None（未対応）を返すこと
        assert source.fetch_price("4901234567894") is None

    def test_search_links_format(self):
        source = ManualInputPriceSource()
        links = source.get_search_links("4901234567894")
        by_key = {link["key"]: link["url"] for link in links}

        assert by_key["amazon"] == "https://www.amazon.co.jp/s?k=4901234567894"
        assert by_key["mercari"] == "https://jp.mercari.com/search?keyword=4901234567894"
        assert by_key["yahoo"] == "https://shopping.yahoo.co.jp/search?p=4901234567894"
        assert by_key["rakuten"] == "https://search.rakuten.co.jp/search/mall/4901234567894/"

    def test_index_page_contains_ec_search_links(self, client):
        res = client.get("/")
        assert b"amazon.co.jp/s?k=" in res.data
        assert b"jp.mercari.com/search" in res.data
        assert b"shopping.yahoo.co.jp/search" in res.data
        assert b"search.rakuten.co.jp/search/mall" in res.data

    def test_no_scraping_module_imported(self):
        # requests/BeautifulSoup等のスクレイピング用ライブラリに依存していないこと
        # （MVPでは検索リンク提示のみで、自動取得・スクレイピングを行わない）
        import app as app_mod
        import adapters.price_source as price_source_mod

        forbidden_modules = ("requests", "bs4", "selenium", "scrapy")
        for mod in forbidden_modules:
            assert mod not in dir(app_mod)
            assert mod not in dir(price_source_mod)


# ---------------------------------------------------------------------------
# 6. 写真からの商品判別API（/api/identify）のテスト（実APIは呼ばない）
# ---------------------------------------------------------------------------

import io
from unittest import mock

from adapters import product_identifier as pid_module


class _FakeIdentifier(pid_module.ProductIdentifier):
    def __init__(self, candidates=None, available=True, error=None):
        self._candidates = candidates or []
        self._available = available
        self._error = error

    def is_available(self):
        return self._available

    def identify(self, image_bytes, media_type):
        if self._error:
            raise self._error
        return self._candidates


def _photo(data=b"\x89PNG fake image bytes", name="item.png", mimetype="image/png"):
    return {"photo": (io.BytesIO(data), name, mimetype)}


class TestApiIdentify:
    def test_returns_candidates_from_identifier(self, client):
        fake = _FakeIdentifier(
            candidates=[
                {"name": "サンプルおもちゃ レッド", "note": "メーカーA"},
                {"name": "サンプルおもちゃ", "note": ""},
            ]
        )
        with mock.patch.object(app_module, "get_product_identifier", return_value=fake):
            res = client.post(
                "/api/identify", data=_photo(), content_type="multipart/form-data"
            )
        assert res.status_code == 200
        data = res.get_json()
        assert data["ok"] is True
        assert len(data["candidates"]) == 2
        assert data["candidates"][0]["name"] == "サンプルおもちゃ レッド"

    def test_returns_503_when_api_key_missing(self, client):
        fake = _FakeIdentifier(available=False)
        with mock.patch.object(app_module, "get_product_identifier", return_value=fake):
            res = client.post(
                "/api/identify", data=_photo(), content_type="multipart/form-data"
            )
        assert res.status_code == 503
        assert res.get_json()["ok"] is False

    def test_returns_400_when_no_photo(self, client):
        fake = _FakeIdentifier()
        with mock.patch.object(app_module, "get_product_identifier", return_value=fake):
            res = client.post("/api/identify", data={}, content_type="multipart/form-data")
        assert res.status_code == 400

    def test_returns_400_for_unsupported_media_type(self, client):
        fake = _FakeIdentifier()
        with mock.patch.object(app_module, "get_product_identifier", return_value=fake):
            res = client.post(
                "/api/identify",
                data=_photo(name="doc.pdf", mimetype="application/pdf"),
                content_type="multipart/form-data",
            )
        assert res.status_code == 400

    def test_returns_502_when_identify_fails(self, client):
        fake = _FakeIdentifier(error=RuntimeError("API error"))
        with mock.patch.object(app_module, "get_product_identifier", return_value=fake):
            res = client.post(
                "/api/identify", data=_photo(), content_type="multipart/form-data"
            )
        assert res.status_code == 502


class TestParseCandidates:
    def test_parses_plain_json_array(self):
        text = '[{"name": "商品A", "note": "型番X"}, {"name": "商品B"}]'
        result = pid_module._parse_candidates(text)
        assert result == [
            {"name": "商品A", "note": "型番X"},
            {"name": "商品B", "note": ""},
        ]

    def test_extracts_json_from_surrounding_text(self):
        text = '以下が候補です。\n[{"name": "商品A", "note": ""}]\n以上です。'
        result = pid_module._parse_candidates(text)
        assert len(result) == 1
        assert result[0]["name"] == "商品A"

    def test_caps_at_three_candidates(self):
        text = (
            '[{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}]'
        )
        assert len(pid_module._parse_candidates(text)) == 3

    def test_returns_empty_for_garbage(self):
        assert pid_module._parse_candidates("判別できませんでした") == []
        assert pid_module._parse_candidates("") == []

    def test_default_identifier_disabled_without_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        identifier = pid_module.get_product_identifier()
        assert isinstance(identifier, pid_module.DisabledIdentifier)
        assert identifier.is_available() is False


# ---------------------------------------------------------------------------
# 7. 横断価格比較機能（楽天市場API・Yahoo!ショッピングAPI）
#
# 楽天市場APIはサーバーサイド（Flask、adapters/price_source.pyの楽天
# アダプター）で取得する構成。Yahoo!ショッピングAPIはPythonAnywhere無料
# プランのホワイトリストに含まれないためブラウザ側から直接呼び出す構成と
# なっており、サーバー側のテスト対象外（/api/pricesは楽天のみを扱う）。
# 実APIは一切呼ばず、アダプターをモックする。
# ---------------------------------------------------------------------------

import adapters.price_source as price_source_mod  # noqa: E402


class _FakeComparisonSource(price_source_mod.PriceSource):
    def __init__(self, prices=None, available=True, error=None):
        self._prices = prices or []
        self._available = available
        self._error = error

    def is_available(self):
        return self._available

    def fetch_price(self, jan_code):
        return self._prices[0] if self._prices else None

    def get_search_links(self, jan_code):
        return []

    def fetch_prices(self, jan_code):
        if self._error:
            raise self._error
        return self._prices


class TestSummarizePrices:
    def test_empty_list_returns_none(self):
        summary = price_source_mod.summarize_prices([])
        assert summary == {"lowest": None, "median": None, "count": 0}

    def test_odd_count_median_is_middle_value(self):
        prices = [
            price_source_mod.PriceInfo(price=300, source_name="楽天市場"),
            price_source_mod.PriceInfo(price=100, source_name="楽天市場"),
            price_source_mod.PriceInfo(price=200, source_name="楽天市場"),
        ]
        summary = price_source_mod.summarize_prices(prices)
        assert summary["lowest"] == 100
        assert summary["median"] == 200
        assert summary["count"] == 3

    def test_even_count_median_is_average_of_middle_two(self):
        prices = [
            price_source_mod.PriceInfo(price=400, source_name="楽天市場"),
            price_source_mod.PriceInfo(price=100, source_name="楽天市場"),
            price_source_mod.PriceInfo(price=200, source_name="楽天市場"),
            price_source_mod.PriceInfo(price=300, source_name="楽天市場"),
        ]
        summary = price_source_mod.summarize_prices(prices)
        assert summary["lowest"] == 100
        assert summary["median"] == 250  # (200 + 300) / 2


class TestPriceInfo:
    def test_to_dict_includes_item_name_and_url(self):
        info = price_source_mod.PriceInfo(
            price=1234.0, source_name="楽天市場", item_name="サンプル商品", url="https://example.com/item"
        )
        assert info.to_dict() == {
            "price": 1234.0,
            "source_name": "楽天市場",
            "item_name": "サンプル商品",
            "url": "https://example.com/item",
        }

    def test_to_dict_defaults_are_empty_strings(self):
        info = price_source_mod.PriceInfo(price=500, source_name="楽天市場")
        assert info.to_dict()["item_name"] == ""
        assert info.to_dict()["url"] == ""


class TestRakutenThrottle:
    def test_wait_sleeps_when_called_within_min_interval(self):
        # 直前呼び出しから1秒未満で呼ばれた場合は、不足分だけ待機すること
        # （毎秒1回程度のスロットリング）。time/sleepは注入して実時間を待たない。
        clock = {"now": 0.0}
        sleeps = []

        def fake_time():
            return clock["now"]

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += seconds

        throttle = price_source_mod.RakutenThrottle(
            min_interval=1.0, time_func=fake_time, sleep_func=fake_sleep
        )
        throttle.wait()  # 1回目: 待機なし
        clock["now"] += 0.2  # 0.2秒後に2回目を呼ぶ
        throttle.wait()

        assert sleeps == [pytest.approx(0.8)]

    def test_wait_does_not_sleep_when_interval_already_elapsed(self):
        clock = {"now": 0.0}
        sleeps = []

        def fake_time():
            return clock["now"]

        def fake_sleep(seconds):
            sleeps.append(seconds)

        throttle = price_source_mod.RakutenThrottle(
            min_interval=1.0, time_func=fake_time, sleep_func=fake_sleep
        )
        throttle.wait()
        clock["now"] += 2.0  # 十分に間隔が空いている
        throttle.wait()

        assert sleeps == []


class TestGetPriceComparisonSource:
    def test_returns_disabled_source_without_app_id(self, monkeypatch):
        monkeypatch.delenv("RAKUTEN_APP_ID", raising=False)
        source = price_source_mod.get_price_comparison_source()
        assert isinstance(source, price_source_mod.DisabledPriceComparisonSource)
        assert source.is_available() is False

    def test_returns_rakuten_source_with_app_id(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APP_ID", "dummy-app-id")
        source = price_source_mod.get_price_comparison_source()
        assert isinstance(source, price_source_mod.RakutenPriceSource)
        assert source.is_available() is True

    def test_disabled_source_app_body_still_works(self, monkeypatch):
        # RAKUTEN_APP_ID未設定でもアプリ本体（検索リンク生成）は動作すること
        monkeypatch.delenv("RAKUTEN_APP_ID", raising=False)
        source = price_source_mod.get_price_comparison_source()
        assert source.fetch_price("4901234567894") is None
        assert source.get_search_links("4901234567894") != []


class TestRakutenPriceSourceFetchPrices:
    def _fake_opener(self, payload_bytes, should_raise=None):
        def opener(url, timeout=None):
            if should_raise:
                raise should_raise

            class _Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *exc_info):
                    return False

                def read(self):
                    return payload_bytes

            return _Resp()

        return opener

    def test_fetch_prices_parses_items(self):
        import json as _json

        payload = _json.dumps(
            {
                "Items": [
                    {"itemName": "商品A", "itemPrice": 1500, "itemUrl": "https://item.rakuten.co.jp/a/"},
                    {"itemName": "商品B", "itemPrice": 1200, "itemUrl": "https://item.rakuten.co.jp/b/"},
                ]
            }
        ).encode("utf-8")
        no_sleep_throttle = price_source_mod.RakutenThrottle(
            min_interval=0.0, time_func=lambda: 0.0, sleep_func=lambda s: None
        )
        source = price_source_mod.RakutenPriceSource(
            app_id="dummy", throttle=no_sleep_throttle, opener=self._fake_opener(payload)
        )
        prices = source.fetch_prices("4901234567894")
        assert len(prices) == 2
        assert {p.price for p in prices} == {1500.0, 1200.0}
        cheapest = source.fetch_price("4901234567894")
        assert cheapest.price == 1200.0

    def test_fetch_prices_raises_on_network_error(self):
        no_sleep_throttle = price_source_mod.RakutenThrottle(
            min_interval=0.0, time_func=lambda: 0.0, sleep_func=lambda s: None
        )
        source = price_source_mod.RakutenPriceSource(
            app_id="dummy",
            throttle=no_sleep_throttle,
            opener=self._fake_opener(b"", should_raise=OSError("network down")),
        )
        with pytest.raises(price_source_mod.PriceFetchError):
            source.fetch_prices("4901234567894")

    def test_fetch_prices_raises_when_app_id_missing(self):
        source = price_source_mod.RakutenPriceSource(app_id=None)
        with pytest.raises(price_source_mod.PriceFetchError):
            source.fetch_prices("4901234567894")


class TestApiPrices:
    def test_returns_prices_lowest_and_median(self, client):
        fake = _FakeComparisonSource(
            prices=[
                price_source_mod.PriceInfo(price=1500, source_name="楽天市場", item_name="商品A"),
                price_source_mod.PriceInfo(price=1200, source_name="楽天市場", item_name="商品B"),
            ]
        )
        with mock.patch.object(app_module, "get_price_comparison_source", return_value=fake):
            res = client.get("/api/prices?jan=4901234567894")
        assert res.status_code == 200
        data = res.get_json()
        assert data["ok"] is True
        assert data["rakuten"]["lowest"] == 1200
        assert data["rakuten"]["median"] == 1350  # (1200+1500)/2
        assert data["rakuten"]["count"] == 2
        assert "fetched_at" in data

    def test_returns_503_when_disabled(self, client):
        fake = _FakeComparisonSource(available=False)
        with mock.patch.object(app_module, "get_price_comparison_source", return_value=fake):
            res = client.get("/api/prices?jan=4901234567894")
        assert res.status_code == 503
        assert res.get_json()["ok"] is False

    def test_returns_400_when_jan_missing(self, client):
        res = client.get("/api/prices")
        assert res.status_code == 400
        assert res.get_json()["ok"] is False

    def test_returns_502_and_error_message_on_fetch_failure(self, client):
        fake = _FakeComparisonSource(error=price_source_mod.PriceFetchError("楽天市場APIの呼び出しに失敗しました。"))
        with mock.patch.object(app_module, "get_price_comparison_source", return_value=fake):
            res = client.get("/api/prices?jan=4901234567894")
        assert res.status_code == 502
        data = res.get_json()
        assert data["ok"] is False
        assert "楽天市場" in data["error"]

    def test_no_products_found_returns_empty_summary(self, client):
        fake = _FakeComparisonSource(prices=[])
        with mock.patch.object(app_module, "get_price_comparison_source", return_value=fake):
            res = client.get("/api/prices?jan=4901234567894")
        assert res.status_code == 200
        data = res.get_json()
        assert data["rakuten"]["lowest"] is None
        assert data["rakuten"]["median"] is None
        assert data["rakuten"]["count"] == 0


class TestIndexPricingComparisonUi:
    def test_index_shows_disabled_messages_without_api_keys(self, client, monkeypatch):
        monkeypatch.delenv("RAKUTEN_APP_ID", raising=False)
        monkeypatch.delenv("YAHOO_CLIENT_ID", raising=False)
        res = client.get("/")
        assert res.status_code == 200
        assert "価格比較".encode("utf-8") in res.data
        assert b"window.RAKUTEN_ENABLED = false;" in res.data
        assert b'window.YAHOO_CLIENT_ID = "";' in res.data

    def test_index_enables_rakuten_when_app_id_set(self, client, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APP_ID", "dummy-app-id")
        monkeypatch.delenv("YAHOO_CLIENT_ID", raising=False)
        res = client.get("/")
        assert res.status_code == 200
        assert b"window.RAKUTEN_ENABLED = true;" in res.data

    def test_index_passes_yahoo_client_id_to_js_when_set(self, client, monkeypatch):
        monkeypatch.delenv("RAKUTEN_APP_ID", raising=False)
        monkeypatch.setenv("YAHOO_CLIENT_ID", "dummy-client-id")
        res = client.get("/")
        assert res.status_code == 200
        assert b'window.YAHOO_CLIENT_ID = "dummy-client-id";' in res.data

    def test_price_comparison_disclaimer_shown_on_index(self, client):
        res = client.get("/")
        assert "取得時点における現在の販売価格".encode("utf-8") in res.data

    def test_app_body_works_without_price_comparison_api_keys(self, client, monkeypatch):
        # RAKUTEN_APP_ID/YAHOO_CLIENT_ID未設定でも、バーコード・利益計算・
        # 登録・一覧などアプリ本体は従来通り動作すること。
        monkeypatch.delenv("RAKUTEN_APP_ID", raising=False)
        monkeypatch.delenv("YAHOO_CLIENT_ID", raising=False)
        res = create_product(client)
        assert res.status_code == 302
        list_res = client.get("/products")
        assert list_res.status_code == 200


class TestNoScrapingModuleForPriceComparison:
    def test_price_source_module_uses_only_stdlib_http(self):
        # requests等のスクレイピング用ライブラリに依存していないこと
        # （urllib標準ライブラリのみでAPI呼び出しを行う）。
        forbidden_modules = ("requests", "bs4", "selenium", "scrapy")
        for mod in forbidden_modules:
            assert mod not in dir(price_source_mod)
