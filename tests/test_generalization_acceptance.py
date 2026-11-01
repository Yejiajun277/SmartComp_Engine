"""Acceptance must reject the real failed-review/high-score regression."""
import unittest
from unittest.mock import patch

from scripts.validate_competitor_generalization import audit


class GeneralizationAcceptanceTests(unittest.TestCase):
    def fixture(self, failed_phase=None):
        phases = ("collection", "product", "pricing", "market", "strategy")
        entities = ("Target", "A", "B", "C")
        product_dims = ["清洁性能", "续航表现", "过滤能力", "使用便捷"]
        price_dims = ["购机报价", "配件费用", "维护费用", "质保条件"]
        def rows(names):
            return [dict(feature=name, values=dict.fromkeys(entities, "资料不足")) for name in names]
        return {
            "/api/tasks/test": dict(status="completed", skip_qa=False, use_rule_engine=False,
                                    max_competitors=3, llm_provider="mimo"),
            "/api/tasks/test/artifacts/collection": dict.fromkeys(entities[1:], {}),
            "/api/tasks/test/artifacts/dimension": {
                "product_sub_dimensions": [dict(name=n) for n in product_dims],
                "pricing_sub_dimensions": [dict(name=n) for n in price_dims]},
            "/api/tasks/test/artifacts/product": {"feature_matrix": rows(product_dims)},
            "/api/tasks/test/artifacts/pricing": {"dimension_comparison": rows(price_dims)},
            "/api/tasks/test/artifacts/qa": {"checks": [dict(
                phase=p, passed=True, score=97, issues=[],
                hallucination_status="failed" if p == failed_phase else "passed") for p in phases]},
            "/api/tasks/test/report": dict(product_name="Target", citation_index={"citations": {"source": {}}}),
            "/api/tasks/test/report.html": "<p>" + " ".join(product_dims + price_dims)
                + '</p><a href="#cite-source">[1]</a><p id="cite-source">Source</p>',
        }

    def test_complete_review_can_pass_structural_acceptance(self):
        fixture = self.fixture()
        with patch("scripts.validate_competitor_generalization.request", side_effect=lambda base, path: fixture[path]):
            self.assertTrue(audit("http://example.test", "test")["pass"])

    def test_unfinished_model_review_is_rejected_even_when_task_says_97_passed(self):
        for phase in ("collection", "product", "pricing", "market", "strategy"):
            with self.subTest(phase=phase):
                fixture = self.fixture(phase)
                with patch("scripts.validate_competitor_generalization.request", side_effect=lambda base, path: fixture[path]):
                    result = audit("http://example.test", "test")
                self.assertFalse(result["pass"])
                self.assertTrue(any(phase in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
