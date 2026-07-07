"""ホットドッグの美味しい作り方を提案する対話型CLIツール。

いくつかの質問に答えると、その回答（好み）に基づいて
パン・ソーセージ・ソース・トッピングの組み合わせレシピを提案する。
標準ライブラリのみで動作する。

使い方:
    python main.py
"""

from hotdog_recipes import generate_recipe
from questions import ask_questions


def format_recipe(recipe):
    """レシピ(dict)を人間が読みやすい文字列に整形する。"""
    bun = recipe["bun"]
    sausage = recipe["sausage"]
    sauce = recipe["sauce"]
    toppings = recipe["toppings"]

    lines = []
    lines.append("=" * 44)
    lines.append("あなたへのおすすめホットドッグレシピ")
    lines.append("=" * 44)
    lines.append(f"■ パン　　　: {bun['name']}")
    lines.append(f"　　　　　　　{bun['desc']}")
    lines.append(f"■ ソーセージ: {sausage['name']}")
    lines.append(f"　　　　　　　{sausage['desc']}")
    lines.append(f"■ ソース　　: {sauce['name']}")
    lines.append(f"　　　　　　　{sauce['desc']}")
    lines.append("■ トッピング:")
    for topping in toppings:
        lines.append(f"　　・{topping['name']} - {topping['desc']}")
    lines.append("-" * 44)
    lines.append("【材料リスト】")
    lines.append(f"  ・パン　　　: {bun['name']}")
    lines.append(f"  ・ソーセージ: {sausage['name']}")
    lines.append(f"  ・ソース　　: {sauce['name']}")
    for topping in toppings:
        lines.append(f"  ・トッピング: {topping['name']}")
    lines.append("=" * 44)
    return "\n".join(lines)


def main(input_func=input, print_func=print, rng=None):
    """対話フローを実行し、レシピを提示するエントリポイント。

    input_func/print_func/rngはテスト容易性のために差し替え可能にしている。
    通常のCLI実行では標準のinput/print/randomがそのまま使われる。
    """
    print_func("ようこそ！あなたにぴったりのホットドッグレシピを提案します。")
    print_func("いくつか質問に答えてください（番号を入力してEnterを押してください）。\n")

    tags, choices = ask_questions(input_func=input_func, print_func=print_func)

    recipe = generate_recipe(tags, rng=rng)

    print_func("")
    print_func(format_recipe(recipe))
    return recipe


if __name__ == "__main__":
    main()
