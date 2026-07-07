"""ホットドッグレシピ提案のためのQ&A対話フロー定義。

質問内容・選択肢・分岐ロジック（＝各選択肢が持つ好みタグ）をここに集約する。
入出力関数(input/print)を差し替え可能にしているため、自動テストからも
実際のCLIと同じロジックを検証できる。
"""

# 各質問は key（回答の識別子。将来ロジックを拡張する際の参照用）、
# text（質問文）、options（選択肢のリスト）から成る。
# 各選択肢は label（表示用ラベル）と tags（選んだ場合に加算される好みタグ）を持つ。
QUESTIONS = [
    {
        "key": "spicy",
        "text": "Q1. 辛いものは好きですか？",
        "options": [
            {"label": "辛党だ", "tags": {"spicy"}},
            {"label": "普通", "tags": set()},
            {"label": "苦手", "tags": {"mild"}},
        ],
    },
    {
        "key": "richness",
        "text": "Q2. 今日はこってり系とあっさり系、どちらの気分ですか？",
        "options": [
            {"label": "こってり系がいい", "tags": {"rich"}},
            {"label": "あっさり系がいい", "tags": {"light"}},
            {"label": "どちらでもいい", "tags": set()},
        ],
    },
    {
        "key": "mood",
        "text": "Q3. 今日の気分に近いものはどれですか？",
        "options": [
            {"label": "定番で安心したい", "tags": {"classic"}},
            {"label": "ちょっと贅沢したい", "tags": {"luxury"}},
            {"label": "新しい味に挑戦したい", "tags": {"adventurous"}},
            {"label": "ヘルシーに済ませたい", "tags": {"healthy"}},
        ],
    },
    {
        "key": "cheese",
        "text": "Q4. チーズは好きですか？",
        "options": [
            {"label": "はい", "tags": {"cheese"}},
            {"label": "いいえ", "tags": set()},
        ],
    },
    {
        "key": "style",
        "text": "Q5. 好みの味の系統はどれに近いですか？",
        "options": [
            {"label": "がっつり洋風", "tags": {"rich"}},
            {"label": "メキシカン・エスニック", "tags": {"mexican", "spicy"}},
            {"label": "あっさり和風だし", "tags": {"light", "healthy"}},
            {"label": "おまかせ", "tags": set()},
        ],
    },
]


class QASession:
    """入出力関数を差し替え可能にした対話セッション。

    input_func/print_funcを差し替えることで、実際のCLI入力を使わずに
    テストからも同じ質問フローを駆動できる。
    """

    def __init__(self, input_func=input, print_func=print):
        self.input_func = input_func
        self.print_func = print_func

    def ask_all(self):
        """全質問を順番にユーザーへ提示し、選択されたタグの和集合と
        質問ごとの回答ラベル一覧のタプルを返す。
        """
        collected_tags = set()
        choice_labels = []
        for question in QUESTIONS:
            option = self._ask_one(question)
            collected_tags |= option["tags"]
            choice_labels.append((question["text"], option["label"]))
        return collected_tags, choice_labels

    def _ask_one(self, question):
        self.print_func(question["text"])
        for idx, option in enumerate(question["options"], start=1):
            self.print_func(f"  {idx}. {option['label']}")
        while True:
            raw = self.input_func("番号を選んでください: ")
            raw = (raw or "").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(question["options"]):
                return question["options"][int(raw) - 1]
            self.print_func(
                f"入力が正しくありません。1〜{len(question['options'])}の番号で入力してください。"
            )


def ask_questions(input_func=input, print_func=print):
    """QASessionを組み立てて全質問を実行するショートカット関数。"""
    session = QASession(input_func=input_func, print_func=print_func)
    return session.ask_all()
