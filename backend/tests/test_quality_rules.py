# -*- coding: utf-8 -*-
import unittest

from app.quality_rules import (
    inspect_requirement_text,
    requirement_precheck_score,
    inspect_prd_text,
    normalize_dimension_scores,
    weighted_prd_caps,
)
from app.classifier import _validate_category_result
from app.duplicate_detector import select_duplicate_candidates
from app.database import UserRequirementJob


class QualityRulesTests(unittest.TestCase):
    def test_requirement_template_placeholder_caps_score(self):
        precheck = inspect_requirement_text(
            "订单优化",
            "【客户信息】客户群名+对接人 【业务场景】客户处理…，会…操作 【希望实现的效果】希望可以优化",
        )
        rules = requirement_precheck_score(precheck)
        self.assertTrue(precheck["has_hard_defect"])
        self.assertLessEqual(rules["caps"]["completeness"], 10)
        self.assertLessEqual(rules["caps"]["clarity"], 15)

    def test_prd_precheck_and_dimension_normalization(self):
        precheck = inspect_prd_text("功能描述：新增一个按钮", "")
        weights = {
            "requirement_coverage": 30,
            "functional_detail": 25,
            "interaction_completeness": 20,
            "acceptance_criteria": 25,
        }
        caps = weighted_prd_caps(weights, precheck)
        normalized, total, _ = normalize_dimension_scores(
            {"requirement_coverage": 30, "functional_detail": 25, "interaction_completeness": 20, "acceptance_criteria": 25},
            caps,
        )
        self.assertLess(normalized["requirement_coverage"], 30)
        self.assertLess(normalized["acceptance_criteria"], 25)
        self.assertEqual(total, sum(normalized.values()))

    def test_classification_low_confidence_keeps_category(self):
        """低置信度不再转人工复核：保留分类结果并标注 low，供人工按置信度筛选。"""
        result = _validate_category_result({
            "category_l1": "订单", "category_l2": "订单信息", "confidence": "low", "reason": "信息不足",
        })
        self.assertEqual(result["category_l1"], "订单")
        self.assertEqual(result["category_l2"], "订单信息")
        self.assertEqual(result["confidence"], "low")

    def test_classification_illegal_l2_cleared_and_forced_low(self):
        """二级分类不合法：置空二级、保留一级，强制 low 置信度。"""
        result = _validate_category_result({
            "category_l1": "订单", "category_l2": "库存同步", "confidence": "high", "reason": "错误二级",
        })
        self.assertEqual(result["category_l1"], "订单")
        self.assertEqual(result["category_l2"], "")
        self.assertEqual(result["confidence"], "low")

    def test_classification_illegal_l1_fallback_by_title(self):
        """一级分类不合法：按标题关键词兜底归类，强制 low 置信度。"""
        result = _validate_category_result({
            "category_l1": "不存在的分类", "category_l2": "", "confidence": "high", "reason": "",
        }, title="订单审核优化")
        self.assertEqual(result["category_l1"], "订单")
        self.assertEqual(result["confidence"], "low")
        self.assertIn("已兜底", result["reason"])

    def test_duplicate_candidates_exclude_duplicate_records(self):
        current = UserRequirementJob(story_id="100", title="订单审核支持批量备注", description="订单审核页面批量添加备注")
        related = UserRequirementJob(story_id="101", title="订单审核批量备注", description="希望在订单审核中批量填写备注")
        duplicate = UserRequirementJob(story_id="102", title="订单审核批量备注", description="历史重复记录", is_duplicate=True)
        candidates = select_duplicate_candidates(current, [related, duplicate])
        self.assertEqual([item.story_id for item in candidates], ["101"])


if __name__ == "__main__":
    unittest.main()
