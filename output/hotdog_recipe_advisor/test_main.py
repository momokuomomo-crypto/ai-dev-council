"""ホットドッグレシピ提案ツールのユニットテスト。

以下の観点をカバーする:
  1. 質問ごとのユーザー入力シミュレーション（正常系・異常系）
  2. 好みタグに基づき期待通りのレシピ提案結果となるか
  3. データ（パン・ソース・トッピング等）の整合性
"""

import random

import pytest

import hotdog_recipes as hd
from hotdog_recipes import generate_recipe, pick_one, pick_toppings
from questions import QUESTIONS, QASession, ask_questions
from main import format_recipe, main


def make_input(sequence):
    """あらかじめ用意した回答列を順番に返すinput関数の代わりを作る。"""
    it = iter(sequence)

    def _input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError("入力がこれ以上ありません（テスト用ダミー入力の枯渇）")

    return _input


def make_collector():
    """print呼び出しを蓄積して後から検証できるようにするヘルパー。"""
    lines = []

    def _print(*args, **kwargs):
        lines.append(" ".join(str(a) for a in args))

    return _print, lines


# ---------------------------------------------------------------------------
# 1. データ整合性のテスト
# ---------------------------------------------------------------------------

class TestData:
    @pytest.mark.parametrize(
        "collection_name",
        ["BUNS", "SAUSAGES", "SAUCES", "TOPPINGS"],
    )
    def test_collections_are_non_empty(self, collection_name):
        collection = getattr(hd, collection_name)
        assert len(collection) > 0

    @pytest.mark.parametrize(
        "collection_name",
        ["BUNS", "SAUSAGES", "SAUCES", "TOPPINGS"],
    )
    def test_items_have_required_fields(self, collection_name):
        collection = getattr(hd, collection_name)
        for item in collection:
            assert isinstance(item["name"], str) and item["name"]
            assert isinstance(item["tags"], set)
            assert isinstance(item["desc"], str) and item["desc"]

    @pytest.mark.parametrize(
        "collection_name",
        ["BUNS", "SAUSAGES", "SAUCES", "TOPPINGS"],
    )
    def test_names_are_unique(self, collection_name):
        collection = getattr(hd, collection_name)
        names = [item["name"] for item in collection]
        assert len(names) == len(set(names))

    def test_topping_pool_has_at_least_two_items(self):
        # pick_toppings が重複なく2つ選べるよう、最低2種類は必要。
        assert len(hd.TOPPINGS) >= 2


# ---------------------------------------------------------------------------
# 2. レシピ選定ロジックのテスト
# ---------------------------------------------------------------------------

class TestGenerateRecipe:
    def test_recipe_has_all_required_parts(self):
        recipe = generate_recipe(set(), rng=random.Random(1))
        assert recipe["bun"] in hd.BUNS
        assert recipe["sausage"] in hd.SAUSAGES
        assert recipe["sauce"] in hd.SAUCES
        assert len(recipe["toppings"]) == 2

    def test_toppings_are_distinct(self):
        for seed in range(20):
            recipe = generate_recipe({"spicy"}, rng=random.Random(seed))
            names = [t["name"] for t in recipe["toppings"]]
            assert len(names) == len(set(names))

    def test_empty_preferences_still_produce_valid_recipe(self):
        recipe = generate_recipe(None, rng=random.Random(42))
        assert recipe["bun"] is not None
        assert recipe["sausage"] is not None
        assert recipe["sauce"] is not None

    def test_unique_matching_tag_is_always_selected(self):
        # ブリオッシュバンズだけが "luxury" タグを持つため、
        # luxury志向のときは乱数の種に関わらず必ず選ばれるはず。
        for seed in range(10):
            recipe = generate_recipe({"luxury"}, rng=random.Random(seed))
            assert recipe["bun"]["name"] == "ブリオッシュバンズ"

    def test_healthy_preference_selects_matching_sausage(self):
        # ハーブチキンソーセージだけが "healthy" タグを持つ。
        for seed in range(10):
            recipe = generate_recipe({"healthy"}, rng=random.Random(seed))
            assert recipe["sausage"]["name"] == "ハーブチキンソーセージ"

    def test_spicy_preference_selects_matching_sauce(self):
        # チリソースだけが "spicy" タグを持つ。
        for seed in range(10):
            recipe = generate_recipe({"spicy"}, rng=random.Random(seed))
            assert recipe["sauce"]["name"] == "チリソース"

    def test_pick_one_returns_none_for_empty_items(self):
        assert pick_one([], {"spicy"}, random.Random(0)) is None

    def test_pick_toppings_respects_count(self):
        toppings = pick_toppings({"rich"}, random.Random(3), count=3)
        assert len(toppings) == 3

    def test_pick_toppings_handles_small_pool(self):
        small_pool = hd.TOPPINGS[:1]
        toppings = pick_toppings({"rich"}, random.Random(0), count=2, items=small_pool)
        assert len(toppings) == 1

    def test_randomness_produces_variation_across_seeds(self):
        # 好みタグが一致しない(=全候補が同スコア)場合、シードを変えると
        # 結果にバリエーションが出ることを確認する。
        bun_names = set()
        for seed in range(15):
            recipe = generate_recipe(set(), rng=random.Random(seed))
            bun_names.add(recipe["bun"]["name"])
        assert len(bun_names) > 1


# ---------------------------------------------------------------------------
# 2b. 質問対話フローのテスト（正常系・異常系）
# ---------------------------------------------------------------------------

class TestQuestions:
    def test_ask_all_with_valid_inputs(self):
        # QUESTIONSは5問。すべて1番を選ぶシナリオ。
        input_func = make_input(["1", "1", "1", "1", "1"])
        print_func, _ = make_collector()
        session = QASession(input_func=input_func, print_func=print_func)
        tags, choices = session.ask_all()

        assert tags == {"spicy", "rich", "classic", "cheese"}
        assert len(choices) == len(QUESTIONS)
        assert choices[0] == ("Q1. 辛いものは好きですか？", "辛党だ")

    def test_ask_all_accumulates_multiple_style_tags(self):
        # Q5で「メキシカン・エスニック」(mexican, spicy)を選ぶケース。
        input_func = make_input(["2", "2", "4", "2", "2"])
        print_func, _ = make_collector()
        session = QASession(input_func=input_func, print_func=print_func)
        tags, _ = session.ask_all()

        # Q1=普通(なし), Q2=あっさり(light), Q3=ヘルシー(healthy),
        # Q4=いいえ(なし), Q5=メキシカン(mexican, spicy)
        assert tags == {"light", "healthy", "mexican", "spicy"}

    def test_invalid_then_valid_input_reprompts(self):
        # 1問目で不正な入力(範囲外・非数値)をした後、正しい値を入れる。
        input_func = make_input(["abc", "99", "0", "1", "1", "1", "1", "1"])
        print_func, printed_lines = make_collector()
        session = QASession(input_func=input_func, print_func=print_func)
        tags, choices = session.ask_all()

        assert choices[0] == ("Q1. 辛いものは好きですか？", "辛党だ")
        error_messages = [line for line in printed_lines if "正しくありません" in line]
        assert len(error_messages) == 3

    def test_empty_string_input_is_rejected(self):
        input_func = make_input(["", "  ", "2", "1", "1", "1", "1"])
        print_func, printed_lines = make_collector()
        session = QASession(input_func=input_func, print_func=print_func)
        tags, choices = session.ask_all()

        assert choices[0][1] == "普通"
        error_messages = [line for line in printed_lines if "正しくありません" in line]
        assert len(error_messages) == 2

    def test_exhausted_input_raises_eof(self):
        # 想定回答数より少ない入力しか無い場合はEOFErrorが送出される
        # （呼び出し側=main.pyでは異常終了として扱われる想定）。
        input_func = make_input(["1"])
        print_func, _ = make_collector()
        session = QASession(input_func=input_func, print_func=print_func)
        with pytest.raises(EOFError):
            session.ask_all()

    def test_ask_questions_shortcut_function(self):
        input_func = make_input(["1", "1", "1", "1", "1"])
        print_func, _ = make_collector()
        tags, choices = ask_questions(input_func=input_func, print_func=print_func)
        assert isinstance(tags, set)
        assert len(choices) == len(QUESTIONS)


# ---------------------------------------------------------------------------
# 3. main() 統合テスト・出力フォーマットのテスト
# ---------------------------------------------------------------------------

class TestMainIntegration:
    def test_main_end_to_end_produces_recipe_and_output(self):
        input_func = make_input(["1", "1", "1", "1", "1"])
        print_func, printed_lines = make_collector()

        recipe = main(input_func=input_func, print_func=print_func, rng=random.Random(7))

        assert recipe["bun"] in hd.BUNS
        assert recipe["sausage"] in hd.SAUSAGES
        assert recipe["sauce"] in hd.SAUCES
        assert len(recipe["toppings"]) == 2

        full_output = "\n".join(printed_lines)
        assert "おすすめホットドッグレシピ" in full_output
        assert recipe["bun"]["name"] in full_output
        assert recipe["sausage"]["name"] in full_output
        assert recipe["sauce"]["name"] in full_output
        for topping in recipe["toppings"]:
            assert topping["name"] in full_output

    def test_main_with_invalid_intermediate_input_still_completes(self):
        input_func = make_input(["9", "x", "1", "1", "1", "1", "1"])
        print_func, printed_lines = make_collector()

        recipe = main(input_func=input_func, print_func=print_func, rng=random.Random(1))
        assert recipe is not None
        full_output = "\n".join(printed_lines)
        assert "正しくありません" in full_output

    def test_main_raises_when_input_exhausted(self):
        input_func = make_input(["1", "1"])  # 5問中2問分しか回答がない
        print_func, _ = make_collector()
        with pytest.raises(EOFError):
            main(input_func=input_func, print_func=print_func, rng=random.Random(0))


class TestFormatRecipe:
    def test_format_recipe_includes_material_list(self):
        recipe = generate_recipe({"cheese"}, rng=random.Random(5))
        text = format_recipe(recipe)

        assert "材料リスト" in text
        assert recipe["bun"]["name"] in text
        assert recipe["sausage"]["name"] in text
        assert recipe["sauce"]["name"] in text
        for topping in recipe["toppings"]:
            assert topping["name"] in text
