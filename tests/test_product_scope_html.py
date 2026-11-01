"""Saved product qualifications must remain visible in standalone report HTML."""
import html
import json
import unittest
from dataclasses import asdict

from agents.strategy_agent import StrategyAgent
from models.domain import FeatureComparison, ProductAnalysis, StrategyReport


class ProductScopeHtmlTests(unittest.TestCase):
    def render_saved_product(self, summary, rivals=("A", "B", "C")):
        product = ProductAnalysis(
            feature_matrix=[FeatureComparison("蛋白含量", {"Target": "✅", **{
                name: "✅" for name in rivals}})],
            summary=summary,
        )
        # Reconstruct a persisted snapshot: rendering cannot depend on transient metadata.
        saved = json.loads(json.dumps(asdict(product), ensure_ascii=False))
        saved["feature_matrix"] = [FeatureComparison(**row) for row in saved["feature_matrix"]]
        report = StrategyReport("Target", competitor_count=len(rivals),
                                product_analysis_summary="仅比较采集范围中的具体规格")
        return StrategyAgent().format_html_report(report, product_analysis=ProductAnalysis(**saved))

    def test_saved_subset_qualifications_are_visible_beside_product_matrix(self):
        qualifier_a = "仅适用于2025年在中国销售的500g无糖SKU。"
        qualifier_bc = "仅适用于2024年欧洲市场的1kg原味SKU。"
        markup = self.render_saved_product(
            "分片恢复合并：我方Target与3家竞品（A、B、C），未知0/4格。"
            "\n局部比较（仅包含 A）：" + qualifier_a +
            "\n局部比较（仅包含 B、C）：" + qualifier_bc)
        self.assertIn("比较范围与限定", markup)
        self.assertIn("适用竞品：A", markup)
        self.assertIn("适用竞品：B、C", markup)
        self.assertIn(qualifier_a, markup)
        self.assertIn(qualifier_bc, markup)
        matrix_start = markup.index("功能对比矩阵（总览）")
        matrix_end = markup.index("</table>", matrix_start)
        self.assertLess(matrix_start, markup.index(qualifier_a))
        self.assertLess(markup.index(qualifier_a), matrix_end)
        self.assertNotIn("分片恢复合并", markup)

    def test_subset_names_and_qualification_text_are_html_escaped(self):
        rival = '<img src=x onerror="alert(1)">'
        qualifier = '<script>alert("SKU")</script> & 2025年中国500g无糖SKU'
        markup = self.render_saved_product(
            "分片恢复合并：内部覆盖摘要。\n局部比较（仅包含 " + rival + "）：" + qualifier,
            rivals=(rival,))
        self.assertIn("适用竞品：" + html.escape(rival), markup)
        self.assertIn(html.escape(qualifier), markup)
        self.assertNotIn(rival, markup)
        self.assertNotIn('<script>alert("SKU")</script>', markup)

    def test_primary_summary_qualification_is_kept_with_the_complete_input_subset(self):
        qualifier = "仅比较2025年中国销售的500g无糖规格，不代表全品牌产品。"
        markup = self.render_saved_product(qualifier)
        self.assertIn("适用竞品：A、B、C", markup)
        self.assertIn(qualifier, markup)

    def test_qualification_notes_do_not_expose_recovery_process_as_product_copy(self):
        qualifier = "仅2025年中国500g规格。"
        markup = self.render_saved_product(
            "分片恢复合并：我方Target与2家竞品，未知1/3格。"
            "\n局部比较（仅包含 A）：" + qualifier +
            "；模型输出截断，降级保留已解析内容，缺失数据标为⚪。"
            "【保留原批次判断：A；其余以恢复结果为准】"
            "\n局部比较（仅包含 B）：规则降级：资料不足，保留分析维度；未完成模型对比。",
            rivals=("A", "B"))
        self.assertIn(qualifier, markup)
        self.assertIn("本条限定适用于：A", markup)
        self.assertIn("资料不足", markup)
        for internal in ("分片恢复", "模型输出截断", "规则降级", "保留原批次判断", "其余以恢复结果为准"):
            self.assertNotIn(internal, markup)


if __name__ == "__main__":
    unittest.main()
