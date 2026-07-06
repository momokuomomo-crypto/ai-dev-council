"""
LLMの構造化出力が稀に壊れるケースへの対処。

観測された不具合：必須キーの一部が応答から欠落し、代わりに別のキーの
値へ、本来他のキーに入るはずだった内容がJSON文字列として丸ごと
埋め込まれることがある（例：{"consensus": "[...], \\"disagreements\\": [...]"}
のように、consensusの値の中に他のキーの中身までテキストとして
混入する）。これが起きると、後続処理が必須キー不在でクラッシュする。

本モジュールはこのケースを検出し、可能であれば復元する。復元できない
場合は明確なエラーを送出する（サイレントに不完全なデータを返さない）。
"""

import json
from typing import Dict, List


def repair_stuffed_json(data: Dict[str, object], required_keys: List[str]) -> Dict[str, object]:
    """
    dataにrequired_keysが全て揃っていればそのまま返す。

    不足している場合、文字列型の値を持つキーについて、
    `{"<そのキー>": <値>}` という形でJSONとして再解釈できないか試みる。
    再解釈した結果にrequired_keysが全て揃っていれば、それを返す。

    どのキーでも復元できない場合はRuntimeErrorを送出する。
    """
    missing = [key for key in required_keys if key not in data]
    if not missing:
        return data

    for key, value in list(data.items()):
        if not isinstance(value, str):
            continue
        try:
            candidate = json.loads("{" + json.dumps(key) + ": " + value)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(candidate, dict) and all(k in candidate for k in required_keys):
            return candidate

    raise RuntimeError(
        "応答に必須キーが不足しており、自動修復もできませんでした。"
        f"不足キー: {missing}。LLM APIが構造化出力を誤って生成した可能性があります。"
        "再実行してください。"
    )
