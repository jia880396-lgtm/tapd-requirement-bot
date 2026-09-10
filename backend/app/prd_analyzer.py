"""PRD 有效性打分模块

对比用户原始需求和产品经理填写的 PRD，给出完整度打分和补充建议。
"""
import json
from typing import Optional

from sqlalchemy.orm import Session

from app.database import PrdAnalysisJob
from app.llm_client import deepseek_client, LLMClientError
from app.jobs import append_process_log
from app.user_settings import get_active_setting
from app.quality_rules import inspect_prd_text, normalize_dimension_scores, weighted_prd_caps


_PRD_WEIGHT_KEYS = {
    "requirement_coverage": "prd_weight_coverage",
    "functional_detail": "prd_weight_functional",
    "interaction_completeness": "prd_weight_interaction",
    "acceptance_criteria": "prd_weight_acceptance",
}


def _format_prd_precheck(precheck: dict) -> str:
    labels = {
        "has_original_requirement": "用户原始需求", "has_background": "背景/初步方案",
        "has_scenario": "场景分析", "has_value": "功能价值", "has_function_path": "功能路径",
        "has_adjustment": "调整点", "has_exception_or_boundary": "异常/边界/校验",
        "has_acceptance": "验收标准", "has_test_data": "测试数据", "has_monitoring": "数据监控/埋点",
    }
    return "；".join(f"{labels[key]}：{'已检测到' if value else '未检测到'}" for key, value in precheck["checks"].items())


def _merge_prd_suggestions(model_suggestions: list, precheck: dict) -> list:
    """即使总分合格，也为确定性缺失项保留低优先级可选建议。"""
    suggestions = [s for s in (model_suggestions or []) if isinstance(s, dict)]
    existing = " ".join(str(s.get("suggestion", "")) for s in suggestions)
    suggestion_map = [
        ("has_original_requirement", "功能", "请补充或关联用户原始需求，便于确认 PRD 覆盖范围。"),
        ("has_function_path", "功能", "请补充功能路径（模块—界面—功能），明确改动入口。"),
        ("has_exception_or_boundary", "交互", "请补充异常流程、边界条件或数据校验规则。"),
        ("has_acceptance", "验收", "请补充可测试的验收标准与预期结果。"),
        ("has_test_data", "验收", "建议补充测试数据或典型样例，便于验收复现。"),
    ]
    for key, category, text in suggestion_map:
        if not precheck["checks"].get(key) and text not in existing:
            suggestions.append({"category": category, "priority": "medium", "suggestion": text})
    return suggestions


async def analyze_prd_for_record(
    db: Session,
    job_id: str,
    record_id: int,
) -> dict:
    """对单条 PRD 进行分析

    Returns:
        {completeness_score, coverage, dimensions, suggestions, reason}
    """
    record = db.query(PrdAnalysisJob).filter(PrdAnalysisJob.id == record_id).first()
    if not record:
        return {}

    # PRD 为空的记录（"待补充PRD"状态）不调用 LLM，避免无效分析
    if not (record.prd_content or "").strip():
        append_process_log(
            db, job_id, "prd_analysis",
            f"PRD {record.story_id} 内容为空，跳过分析（待补充PRD）",
            story_id=record.story_id,
            level="warning",
        )
        return {"skipped": True, "reason": "PRD 内容为空"}

    try:
        # 原始需求为空时仍允许给出结构性建议，但会限制覆盖度上限，并在详情中明确告警。
        precheck = inspect_prd_text(record.prd_content, record.original_requirement)
        # 截图 AI 识别文字按需拼接（PRD 分析无图片直入，依赖此文字理解截图信息）
        img_text = (record.image_descriptions or "").strip()
        if img_text:
            if precheck["original_requirement"]:
                precheck["original_requirement"] = (
                    precheck["original_requirement"].strip()
                    + "\n\n【需求截图内容（AI识别）】\n" + img_text
                )
            else:
                precheck["prd_content"] = (
                    precheck["prd_content"].strip()
                    + "\n\n【需求截图内容（AI识别）】\n" + img_text
                )
        weights = {key: float(get_active_setting(setting_key)) for key, setting_key in _PRD_WEIGHT_KEYS.items()}
        caps = weighted_prd_caps(weights, precheck)
        result = await deepseek_client.analyze_prd(
            prd_content=precheck["prd_content"],
            original_requirement=precheck["original_requirement"],
            quality_precheck=_format_prd_precheck(precheck),
        )

        # 以合法维度分重算总分；模型总分仅作参考，避免分数与权重不一致或超限。
        normalized, completeness_score, warnings = normalize_dimension_scores(result.get("dimensions", {}), caps)
        result["dimensions"] = normalized
        result["completeness_score"] = completeness_score
        suggestions = _merge_prd_suggestions(result.get("suggestions", []), precheck)
        coverage = result.get("coverage", {}) if isinstance(result.get("coverage", {}), dict) else {}
        coverage["precheck"] = precheck["checks"]
        coverage["normalization_warnings"] = warnings
        coverage["score_caps"] = caps

        record.completeness_score = completeness_score
        record.coverage_detail = json.dumps(coverage, ensure_ascii=False)
        record.suggestions = json.dumps(suggestions, ensure_ascii=False)
        record.status = "analyzed"
        db.commit()

        append_process_log(
            db, job_id, "prd_analysis",
            f"PRD {record.story_id} 分析完成：{completeness_score}/100" + ("；原始需求缺失，覆盖度已受限" if not precheck["checks"]["has_original_requirement"] else ""),
            story_id=record.story_id,
            level="success" if completeness_score >= float(get_active_setting("prd_pass_threshold")) else "warning",
        )
        return result

    except LLMClientError as e:
        append_process_log(
            db, job_id, "prd_analysis",
            f"PRD {record.story_id} 分析失败：{e}",
            story_id=record.story_id,
            level="error",
        )
        raise
    except Exception as e:
        append_process_log(
            db, job_id, "prd_analysis",
            f"PRD {record.story_id} 分析异常：{e}",
            story_id=record.story_id,
            level="error",
        )
        raise
