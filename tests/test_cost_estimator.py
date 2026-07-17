import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council import cost_estimator

_PRICING = {
    "claude": {"input": 3.00, "output": 15.00},
    "openai": {"input": 2.00, "output": 8.00},
    "gemini": {"input": 0.30, "output": 2.50},
}


class TestEstimateFixedStageCost(unittest.TestCase):
    def test_total_is_positive_and_matches_call_count_formula(self):
        estimate = cost_estimator.estimate_fixed_stage_cost(
            "タスク説明", "", max_rounds=1, max_implementation_rounds=1, pricing=_PRICING
        )
        # design(1) + design_review(2) + code_review(2) = 5
        self.assertEqual(estimate["call_count"], 5)
        self.assertGreater(estimate["total_usd"], 0)

    def test_more_rounds_costs_more(self):
        low = cost_estimator.estimate_fixed_stage_cost(
            "タスク", "", max_rounds=1, max_implementation_rounds=1, pricing=_PRICING
        )
        high = cost_estimator.estimate_fixed_stage_cost(
            "タスク", "", max_rounds=3, max_implementation_rounds=3, pricing=_PRICING
        )
        self.assertGreater(high["total_usd"], low["total_usd"])

    def test_longer_context_costs_more(self):
        short = cost_estimator.estimate_fixed_stage_cost(
            "タスク", "", max_rounds=1, max_implementation_rounds=1, pricing=_PRICING
        )
        long_context = cost_estimator.estimate_fixed_stage_cost(
            "タスク", "x" * 50_000, max_rounds=1, max_implementation_rounds=1, pricing=_PRICING
        )
        self.assertGreater(long_context["total_usd"], short["total_usd"])

    def test_missing_provider_pricing_treated_as_zero_not_crash(self):
        estimate = cost_estimator.estimate_fixed_stage_cost(
            "タスク", "", max_rounds=1, max_implementation_rounds=1, pricing={}
        )
        self.assertEqual(estimate["total_usd"], 0.0)

    def test_breakdown_includes_all_three_providers(self):
        estimate = cost_estimator.estimate_fixed_stage_cost(
            "タスク", "", max_rounds=1, max_implementation_rounds=1, pricing=_PRICING
        )
        self.assertEqual(set(estimate["breakdown_usd"].keys()), {"claude", "openai", "gemini"})


class TestFormatEstimateLine(unittest.TestCase):
    def test_includes_total_and_per_provider_breakdown(self):
        estimate = cost_estimator.estimate_fixed_stage_cost(
            "タスク", "", max_rounds=1, max_implementation_rounds=1, pricing=_PRICING
        )
        line = cost_estimator.format_estimate_line(estimate)
        self.assertIn("概算コスト", line)
        self.assertIn("claude", line)
        self.assertIn("openai", line)
        self.assertIn("gemini", line)


if __name__ == "__main__":
    unittest.main()
