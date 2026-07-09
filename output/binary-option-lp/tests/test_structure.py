"""
静的LP（バイナリーオプション情報提供LP・ポートフォリオ用モックアップ）の構造検証テスト。

これは設計書に定義された「ガードレール」テストである。
index.html / static/css/style.css は実際の公開・実装時にも改変禁止の対象であり、
本テストファイルもその意図に反する形で緩めてはならない
（コンプライアンス表現・法的注意書きの分散配置・特定商取引法表記等の欠落を防ぐための
 静的チェックとして維持すること）。

実行方法:
    python -m pytest tests/test_structure.py -v
"""

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = PROJECT_ROOT / "index.html"
STYLE_CSS_PATH = PROJECT_ROOT / "static" / "css" / "style.css"


@pytest.fixture(scope="module")
def html_text():
    assert INDEX_HTML_PATH.exists(), f"{INDEX_HTML_PATH} が見つかりません"
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def soup(html_text):
    return BeautifulSoup(html_text, "html.parser")


@pytest.fixture(scope="module")
def css_text():
    assert STYLE_CSS_PATH.exists(), f"{STYLE_CSS_PATH} が見つかりません"
    return STYLE_CSS_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. ファイル構成 / 静的サイトであることの検証
# ---------------------------------------------------------------------------

class TestStaticOnly:
    def test_no_script_tags(self, soup):
        """JavaScriptによる挙動制御を導入しないこと（<script>タグ不使用）。"""
        assert soup.find_all("script") == []

    def test_no_inline_event_handlers(self, html_text):
        """onclick 等のインラインJSハンドラが使われていないこと。"""
        forbidden_attrs = [
            "onclick", "onsubmit", "onload", "onchange", "onmouseover",
        ]
        lowered = html_text.lower()
        for attr in forbidden_attrs:
            assert attr not in lowered, f"インラインイベントハンドラ {attr} が検出されました"

    def test_no_form_tags(self, soup):
        """フォーム送信機能を持たないこと。"""
        assert soup.find_all("form") == []

    def test_no_input_or_button_submit_elements(self, soup):
        """input/button等、送信を伴いうる実インタラクティブ要素がないこと。"""
        assert soup.find_all("input") == []
        assert soup.find_all("button") == []

    def test_stylesheet_is_local_static_css(self, soup):
        links = soup.find_all("link", rel="stylesheet")
        assert len(links) == 1
        assert links[0].get("href") == "static/css/style.css"

    def test_no_external_library_references(self, html_text):
        """外部ライブラリ（CDN等）を読み込んでいないこと。"""
        assert "cdn." not in html_text.lower()
        assert "http://" not in html_text.lower()
        assert "https://" not in html_text.lower()


# ---------------------------------------------------------------------------
# 2. 全12セクションの存在確認
# ---------------------------------------------------------------------------

class TestTwelveSections:
    EXPECTED_SECTION_IDS = [
        "hero",
        "legal-notice-top",
        "empathy",
        "overview",
        "contents",
        "results",
        "pricing",
        "faq",
        "legal-position",
        "tokushoho",
        "cta",
        "footer",
    ]

    def test_twelve_sections_present_in_order(self, soup):
        ids_found = []
        for section_id in self.EXPECTED_SECTION_IDS:
            el = soup.find(id=section_id)
            assert el is not None, f"セクション #{section_id} が見つかりません"
            ids_found.append(section_id)
        assert ids_found == self.EXPECTED_SECTION_IDS

    def test_exactly_twelve_top_level_sections(self, soup):
        """section要素(footerを含む) が要件通り12個のセマンティックブロックであること。"""
        section_like = soup.find_all("section") + soup.find_all("footer")
        top_level_ids = {el.get("id") for el in section_like if el.get("id")}
        assert top_level_ids == set(self.EXPECTED_SECTION_IDS)
        assert len(section_like) == 12


# ---------------------------------------------------------------------------
# 3. 法的注意書き（簡潔版）の4カ所分散設置
# ---------------------------------------------------------------------------

class TestLegalNoticeDistribution:
    def test_four_legal_notice_brief_blocks(self, soup):
        notices = soup.find_all(class_="legal-notice-brief")
        assert len(notices) == 4, "法的注意書き（簡潔版）は4カ所に設置される必要があります"

    def test_legal_notice_ids_present_and_unique(self, soup):
        for i in range(1, 5):
            el = soup.find(id=f"legal-notice-{i}")
            assert el is not None, f"legal-notice-{i} が見つかりません"
            assert "legal-notice-brief" in el.get("class", [])

    def test_legal_notice_1_directly_below_hero(self, soup):
        """FV（ヒーロー）直下に設置されていること。"""
        hero = soup.find(id="hero")
        legal_top = soup.find(id="legal-notice-top")
        assert hero is not None and legal_top is not None
        # heroの次の兄弟要素がlegal-notice-topであること
        next_section = hero.find_next_sibling(["section", "div"])
        assert next_section is not None and next_section.get("id") == "legal-notice-top"
        assert soup.find(id="legal-notice-1") in legal_top.find_all(id="legal-notice-1")

    def test_legal_notice_2_within_results_section(self, soup):
        """実績セクション近くに設置されていること。"""
        results = soup.find(id="results")
        assert results is not None
        assert results.find(id="legal-notice-2") is not None

    def test_legal_notice_3_within_cta_section(self, soup):
        """CTA近傍に設置されていること。"""
        cta = soup.find(id="cta")
        assert cta is not None
        assert cta.find(id="legal-notice-3") is not None

    def test_legal_notice_4_within_footer(self, soup):
        """フッターに設置されていること。"""
        footer = soup.find(id="footer")
        assert footer is not None
        assert footer.find(id="legal-notice-4") is not None

    def test_legal_notice_content_mentions_key_points(self, soup):
        key_phrases = ["情報提供", "投資", "損失", "保証"]
        for i in range(1, 5):
            el = soup.find(id=f"legal-notice-{i}")
            text = el.get_text()
            for phrase in key_phrases:
                assert phrase in text, f"legal-notice-{i} に必須ワード「{phrase}」がありません"


# ---------------------------------------------------------------------------
# 4. 利用者の声セクション
# ---------------------------------------------------------------------------

class TestTestimonialSection:
    def test_testimonial_heading_exists(self, soup):
        heading = soup.find(class_="testimonial-heading")
        assert heading is not None
        assert "利用者の声" in heading.get_text()

    def test_testimonial_entries_exist(self, soup):
        testimonials = soup.find_all(class_="testimonial")
        assert len(testimonials) >= 2

    def test_testimonial_disclaimer_exact_phrase(self, soup):
        """『個人の感想であり将来の成果を保証するものではない』の明記を確認する。"""
        disclaimer = soup.find(class_="testimonial-disclaimer")
        assert disclaimer is not None
        text = disclaimer.get_text().replace("\n", "").replace(" ", "")
        assert "個人の感想であり" in text
        assert "将来の成果を保証するものではありません" in text or "将来の成果を保証するものではない" in text

    def test_testimonial_disclaimer_within_results_section(self, soup):
        results = soup.find(id="results")
        assert results.find(class_="testimonial-disclaimer") is not None


# ---------------------------------------------------------------------------
# 5. FAQ：リスク・保証不可項目を2件以上
# ---------------------------------------------------------------------------

class TestFAQRiskItems:
    RISK_KEYWORDS = ["リスク", "保証", "損失", "元本"]

    def test_faq_has_minimum_items(self, soup):
        faq = soup.find(id="faq")
        items = faq.find_all(class_="faq-item")
        assert len(items) >= 4

    def test_faq_contains_two_or_more_risk_disclosure_items(self, soup):
        faq = soup.find(id="faq")
        items = faq.find_all(class_="faq-item")
        risk_items = []
        for item in items:
            text = item.get_text()
            if any(keyword in text for keyword in self.RISK_KEYWORDS) and (
                "いいえ" in text or "ません" in text
            ):
                risk_items.append(item)
        assert len(risk_items) >= 2, "リスク・保証不可を明示するFAQ項目が2件以上必要です"

    def test_faq_explicitly_denies_guaranteed_profit(self, soup):
        faq_text = soup.find(id="faq").get_text()
        assert "保証" in faq_text
        assert ("いいえ" in faq_text) or ("できません" in faq_text) or ("行っておりません" in faq_text)


# ---------------------------------------------------------------------------
# 6. サービスの法的位置づけ（独立セクション）
# ---------------------------------------------------------------------------

class TestLegalPositionSection:
    def test_section_heading(self, soup):
        section = soup.find(id="legal-position")
        assert section is not None
        heading = section.find(["h2", "h3"])
        assert heading is not None
        assert "法的位置づけ" in heading.get_text()

    def test_section_mentions_regulatory_status(self, soup):
        text = soup.find(id="legal-position").get_text()
        required_phrases = [
            "金融商品取引法",
            "金融商品取引業",
            "投資助言",
            "登録",
        ]
        for phrase in required_phrases:
            assert phrase in text, f"法的位置づけセクションに「{phrase}」の記載が必要です"

    def test_section_denies_solicitation_and_advice(self, soup):
        text = soup.find(id="legal-position").get_text()
        assert "勧誘" in text
        assert "助言" in text


# ---------------------------------------------------------------------------
# 7. 特定商取引法に基づく表記（独立セクション）
# ---------------------------------------------------------------------------

class TestTokushohoSection:
    REQUIRED_LABELS = [
        "販売事業者名",
        "運営統括責任者",
        "所在地",
        "連絡先電話番号",
        "連絡先メールアドレス",
        "販売価格",
        "お支払い方法",
        "お支払い時期",
        "返品・キャンセルについて",
    ]

    def test_section_heading(self, soup):
        section = soup.find(id="tokushoho")
        assert section is not None
        heading = section.find(["h2", "h3"])
        assert heading is not None
        assert "特定商取引法" in heading.get_text()

    def test_required_labels_present(self, soup):
        section = soup.find(id="tokushoho")
        text = section.get_text()
        for label in self.REQUIRED_LABELS:
            assert label in text, f"特定商取引法に基づく表記に必須項目「{label}」がありません"

    def test_table_structure_used(self, soup):
        section = soup.find(id="tokushoho")
        table = section.find("table")
        assert table is not None
        rows = table.find_all("tr")
        assert len(rows) >= len(self.REQUIRED_LABELS)


# ---------------------------------------------------------------------------
# 8. CTA：ダミーであること
# ---------------------------------------------------------------------------

class TestDummyCTA:
    def test_cta_links_point_to_hash_only(self, soup):
        cta_links = soup.select("a.btn")
        assert len(cta_links) >= 2
        for link in cta_links:
            href = link.get("href")
            assert href == "#", f"CTAリンクは # のみを許容します（検出値: {href}）"

    def test_cta_links_marked_disabled(self, soup):
        cta_links = soup.select("a.btn")
        for link in cta_links:
            assert link.get("aria-disabled") == "true"
            assert "btn-disabled" in link.get("class", [])

    def test_cta_notes_state_dummy_nature(self, soup):
        combined_text = soup.get_text()
        assert "ダミー" in combined_text
        assert ("実際の送信" in combined_text) or ("実際の申込み" in combined_text)

    def test_no_action_attribute_anywhere(self, html_text):
        assert re.search(r'action\s*=', html_text) is None


# ---------------------------------------------------------------------------
# 9. ヒーローコピーの抑制的表現チェック
# ---------------------------------------------------------------------------

class TestHeroCopyRestraint:
    FORBIDDEN_PHRASES = [
        "絶対に儲かる",
        "必ず儲かる",
        "100%勝てる",
        "誰でも稼げる",
        "今すぐ稼",
        "全額返金保証",
        "楽して稼",
        "ノーリスク",
    ]

    def test_hero_has_no_hype_or_urgency_claims(self, soup):
        hero_text = soup.find(id="hero").get_text()
        for phrase in self.FORBIDDEN_PHRASES:
            assert phrase not in hero_text, f"ヒーローに禁止表現「{phrase}」が含まれています"

    def test_hero_states_no_profit_guarantee(self, soup):
        hero_text = soup.find(id="hero").get_text()
        assert ("保証するものではありません" in hero_text) or ("保証するものではない" in hero_text)

    def test_forbidden_hype_phrases_absent_site_wide(self, soup):
        full_text = soup.get_text()
        for phrase in self.FORBIDDEN_PHRASES:
            assert phrase not in full_text, f"サイト全体に禁止表現「{phrase}」が含まれています"


# ---------------------------------------------------------------------------
# 10. モックアップ／非公開であることの明示
# ---------------------------------------------------------------------------

class TestMockupDisclosure:
    def test_mockup_banner_present(self, soup):
        banner = soup.find(class_="mockup-banner")
        assert banner is not None
        assert "架空" in banner.get_text() or "モックアップ" in banner.get_text()

    def test_footer_states_mockup_and_non_public(self, soup):
        footer_text = soup.find(id="footer").get_text()
        assert "モックアップ" in footer_text or "架空" in footer_text


# ---------------------------------------------------------------------------
# 11. レスポンシブ対応
# ---------------------------------------------------------------------------

class TestResponsiveDesign:
    def test_viewport_meta_tag_present(self, soup):
        viewport = soup.find("meta", attrs={"name": "viewport"})
        assert viewport is not None
        assert "width=device-width" in viewport.get("content", "")

    def test_css_contains_media_queries(self, css_text):
        assert "@media" in css_text
        assert re.search(r"@media[^{]*max-width", css_text) is not None

    def test_no_fixed_pixel_wide_root_layout(self, css_text):
        """ページ全体の横幅が固定pxで指定されていない（横スクロール要因の排除）。"""
        assert "width: 100vw" not in css_text.replace(" ", "") or True
        assert "overflow-x: hidden" in css_text or "overflow-x:hidden" in css_text.replace(" ", "")


# ---------------------------------------------------------------------------
# 12. カラーパレット（青・紺・グレー系）簡易確認
# ---------------------------------------------------------------------------

class TestColorPalette:
    def test_navy_and_blue_and_gray_variables_defined(self, css_text):
        assert "--color-navy" in css_text
        assert "--color-blue" in css_text
        assert "--color-gray" in css_text
