# -*- coding: utf-8 -*-
"""
固定回数API呼び出しステージ（設計・設計レビュー・設計改訂・実装レビュー）の
概算コストを算出するモジュール。

Claude Agent SDKによる実装ステージ（claude_coding_agent.py）はターン数
依存で費用が変動するため対象外（confirm_agent_run側で別途、変動費用で
ある旨を警告するのみで、事前見積もりは行わない）。

トークン数は正確なトークナイザーを使わず、文字数からの概算による
ヒューリスティックである点に注意（実際の課金額とは数十%程度ずれうる、
安全側に倒した「上限寄り」の概算）。また単価（pricing_usd_per_1m_tokens）
は各社の公式ページで随時変わるため、config.yaml側で手動更新が必要。
"""
from typing import Dict, List, Tuple

# 1トークンあたりの概算文字数（日本語混じりの文章を想定した目安）。
_CHARS_PER_TOKEN = 2.5

# 各ステージ1回あたりの出力トークン数の目安
# （構造化出力のフィールド量から見積もった固定的な概算）。
_BASE_OUTPUT_TOKENS = {
    "design": 1200,
    "design_review": 800,
    "code_review": 800,
}
# 各ステージ1回あたりの、タスク説明・コンテキスト以外の入力トークン数の
# 目安（システムプロンプト・スキーマ定義・レビュー対象の設計/コード等）。
_BASE_INPUT_TOKENS = {
    "design": 600,
    "design_review": 1000,  # 設計ドキュメント全文を含む
    "code_review": 3000,  # 生成コード全文を含むため最も大きくなりやすい
}


def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


def _build_call_list(max_rounds: int, max_implementation_rounds: int) -> List[Tuple[str, str]]:
    """(provider, stage)のリストを、早期承認による短縮を考慮しない
    「最大」見積もり相当で組み立てる（_estimate_fixed_call_countと
    同じ回数の数え方に合わせる）。"""
    calls: List[Tuple[str, str]] = [("openai", "design")]
    for _ in range(max_rounds):
        calls.append(("claude", "design_review"))
        calls.append(("gemini", "design_review"))
    for _ in range(max(0, max_rounds - 1)):
        calls.append(("openai", "design"))  # 設計改訂も設計と同程度の規模とみなす
    for _ in range(max_implementation_rounds):
        calls.append(("gemini", "code_review"))
        calls.append(("openai", "code_review"))
    return calls


def estimate_fixed_stage_cost(
    task: str,
    context: str,
    max_rounds: int,
    max_implementation_rounds: int,
    pricing: Dict[str, Dict[str, float]],
) -> Dict[str, object]:
    """
    設計(OpenAI 1回) + 設計レビュー(Claude+Gemini、最大max_rounds回) +
    設計改訂(OpenAI、最大max_rounds-1回) + 実装レビュー(Gemini+OpenAI、
    最大max_implementation_rounds回) の概算コスト（USD）を算出する。

    pricingは `{"claude": {"input": 単価, "output": 単価}, ...}`
    （1Mトークンあたりのドル単価）の形式。プロバイダーが見つからない場合は
    0円として扱う（設定漏れでクラッシュさせないため）。
    """
    task_tokens = _estimate_tokens(task)
    context_tokens = _estimate_tokens(context)

    total_usd = 0.0
    breakdown_usd: Dict[str, float] = {}
    for provider, stage in _build_call_list(max_rounds, max_implementation_rounds):
        input_tokens = _BASE_INPUT_TOKENS[stage] + task_tokens + context_tokens
        output_tokens = _BASE_OUTPUT_TOKENS[stage]
        rate = pricing.get(provider, {})
        cost = (
            input_tokens * rate.get("input", 0.0) / 1_000_000
            + output_tokens * rate.get("output", 0.0) / 1_000_000
        )
        total_usd += cost
        breakdown_usd[provider] = breakdown_usd.get(provider, 0.0) + cost

    return {
        "total_usd": round(total_usd, 4),
        "breakdown_usd": {k: round(v, 4) for k, v in breakdown_usd.items()},
        "call_count": len(_build_call_list(max_rounds, max_implementation_rounds)),
    }


def format_estimate_line(estimate: Dict[str, object]) -> str:
    """confirm_api_callsの確認文言に埋め込む1行を組み立てる。"""
    breakdown_text = " / ".join(
        f"{provider}: ${cost:.2f}" for provider, cost in estimate["breakdown_usd"].items()
    )
    return f"概算コスト（目安、実際とは数十%ずれうる）: 約${estimate['total_usd']:.2f}（内訳: {breakdown_text}）"
