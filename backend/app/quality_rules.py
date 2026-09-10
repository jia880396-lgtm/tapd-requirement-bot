"""四个 AI 判断模块共用的确定性质量规则。

规则层只处理可复现的事实：清洗输入、识别模板占位符、校验模型返回分数与枚举值。
它不替代 LLM 的业务判断，而是为 LLM 提供可解释的预检证据，并在写库前阻断无效结果。
"""
from __future__ import annotations

import html
import re
from typing import Any


_TEMPLATE_PATTERNS = {
    "customer_placeholder": ("客户群名+对接人", "客户账号 + 对接人", "客户电话"),
    "scenario_placeholder": ("客户处理…，会…操作", "客户处理...，会...操作", "描述业务场景"),
    "effect_placeholder": ("希望可以优化", "描述期望效果", "希望优化体验", "希望更智能"),
}


def clean_plain_text(value: str | None, limit: int | None = None) -> str:
    """统一清洗 TAPD 富文本，保留可读文本并压缩空白。"""
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z#0-9]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if limit else text


def inspect_requirement_text(title: str | None, description: str | None) -> dict[str, Any]:
    """检测需求文本中的确定性缺陷，供可靠性打分前预检使用。"""
    clean_title = clean_plain_text(title)
    clean_description = clean_plain_text(description)
    lower = clean_description.lower()
    flags: list[str] = []
    evidence: list[str] = []

    if not clean_description:
        flags.append("empty_description")
        evidence.append("需求描述为空")
    if len(clean_description) < 16:
        flags.append("too_short")
        evidence.append("有效描述少于 16 个字符")

    for flag, patterns in _TEMPLATE_PATTERNS.items():
        matched = next((p for p in patterns if p.lower() in lower), None)
        if matched:
            flags.append(flag)
            evidence.append(f"检测到未替换模板文字：{matched}")

    # ---- 增强检测（方案 A） ----
    # 检查客户信息缺失或非真实账号
    customer_section = re.search(r'【\s*客户信息\s*[】:]\s*(.+?)(?=\n?【|$)', clean_description, re.DOTALL)
    if customer_section:
        customer_content = customer_section.group(1).strip()
        if not customer_content or customer_content in ('无', '暂无', '-', '/'):
            flags.append('no_customer_info')
            evidence.append('客户信息为空')
        elif not re.search(r'[A-Za-z0-9]{3,}|\d{2,}', customer_content):
            # 客户信息有文字但不含账号特征（字母数字混合/纯数字账号），视为非真实客户标识
            flags.append('no_customer_info')
            evidence.append(f'客户信息非真实账号：{customer_content[:30]}')
    elif '客户' not in clean_description[:100] and '租户' not in clean_description[:100]:
        # 描述开头未提及任何客户/租户信息
        flags.append('no_customer_info')
        evidence.append('描述中未提及客户或租户信息')

    # 检查是否缺少具体单号/文档号
    has_order_number = bool(re.search(
        r'[A-Za-z]{2,}[_-]?\d{6,}|\d{10,}', clean_description))
    if not has_order_number:
        flags.append('no_order_number')
        evidence.append('未包含具体单号或文档号')

    # 检查是否缺少量化数据（数字+单位）
    has_quantity = bool(re.search(r'\d+\s*[条个件单客户小时分钟天%]', clean_description))
    if not has_quantity:
        flags.append('no_quantity')
        evidence.append('未包含量化数据（如影响客户数、订单量等）')

    # 检查【希望实现的效果】是否过于模糊
    effect_section = re.search(r'【\s*希望实现的效果\s*[】:]\s*(.+?)(?=\n?【|$)', clean_description, re.DOTALL)
    if effect_section:
        effect_content = effect_section.group(1).strip()
        if len(effect_content) < 20 or re.search(r'希望(优化|更智能|改善|提升)(一下|体验|一些)?[。.]?$', effect_content):
            flags.append('vague_effect')
            evidence.append(f'希望实现的效果过于简略（{len(effect_content)}字）')

    # 检查【需求价值】是否缺失或模糊
    value_section = re.search(r'【\s*需求价值\s*[】:]\s*(.+?)(?=\n?【|$)', clean_description, re.DOTALL)
    if value_section:
        value_content = value_section.group(1).strip()
        if not value_content or value_content in ('无', '暂无', '-', '/') or len(value_content) < 8:
            flags.append('vague_value')
            evidence.append('需求价值为空或过于简略')

    # 检查是否缺少图片（无截图的需求应在完整度和清晰度上受限）
    # 此字段由调用方在 inspect 后补充 image_paths，inspect 本身不访问数据库
    # 实际的 no_images flag 由 inspect_requirement_text 的调用方追加

    return {
        "title": clean_title,
        "description": clean_description,
        "flags": flags,
        "evidence": evidence,
        "has_hard_defect": bool({"empty_description", "customer_placeholder", "scenario_placeholder", "no_customer_info"} & set(flags)),
    }


def requirement_precheck_score(precheck: dict[str, Any]) -> dict[str, Any]:
    """将确定性事实转换为四维评分上限和建议扣分，而非凭感觉直接判分。"""
    flags = set(precheck.get("flags", []))
    caps = {"completeness": 30, "clarity": 30, "feasibility": 20, "business_value": 20}
    deductions = {key: 0 for key in caps}

    if "empty_description" in flags:
        caps.update({"completeness": 5, "clarity": 5, "feasibility": 5, "business_value": 5})
    if "customer_placeholder" in flags:
        caps["completeness"] = min(caps["completeness"], 10)
    if "scenario_placeholder" in flags:
        caps["completeness"] = min(caps["completeness"], 15)
        caps["clarity"] = min(caps["clarity"], 15)
    if "effect_placeholder" in flags:
        caps["clarity"] = min(caps["clarity"], 20)
        caps["feasibility"] = min(caps["feasibility"], 15)
    if "too_short" in flags:
        caps["clarity"] = min(caps["clarity"], 15)
        caps["feasibility"] = min(caps["feasibility"], 12)
    if "no_customer_info" in flags:
        # 客户账号对客户反馈需求不是关键信息，仅作小幅限制
        caps["completeness"] = min(caps["completeness"], 22)
    if "no_order_number" in flags:
        # 具体单号对新功能需求不是必要信息，仅作轻微限制
        caps["completeness"] = min(caps["completeness"], 25)
    if "no_quantity" in flags:
        caps["business_value"] = min(caps["business_value"], 15)
    if "vague_effect" in flags:
        caps["clarity"] = min(caps["clarity"], 15)
    if "vague_value" in flags:
        caps["business_value"] = min(caps["business_value"], 10)

    # 实际扣分（在 cap 限制基础上额外降低）
    if "no_order_number" in flags:
        deductions["completeness"] += 2
    if "no_quantity" in flags:
        deductions["business_value"] += 3
    if "vague_effect" in flags:
        deductions["clarity"] += 3
    if "vague_value" in flags:
        deductions["business_value"] += 5
    if "description_short_50" if "description_short_50" in flags else len(precheck.get("description", "")) < 50:
        deductions["completeness"] += 2
        deductions["clarity"] += 2
    if "no_customer_info" in flags:
        deductions["completeness"] += 2
    if "no_images" in flags:
        # 无图小幅扣分：图片是加分项，无图不应惩罚过重
        deductions["completeness"] += 1
        deductions["clarity"] += 1
    if "has_images" in flags:
        # 有图加分：截图提供了可视化证据，给完整度和清晰度加分
        caps["completeness"] = min(caps["completeness"] + 2, 32)
        caps["clarity"] = min(caps["clarity"] + 2, 32)

    return {"caps": caps, "deductions": deductions}


def convert_score_100_to_10(score_100: float) -> int:
    """将100分制转换为10分制（向下取整，0-10范围）

    映射规则（去尾法）：
    - 0-9   → 0（保留0分表示"未打分/极差"）
    - 10-19 → 1
    - ...
    - 90-99 → 9
    - 100   → 10

    例如：59/100 → 5/10，60/100 → 6/10。

    实际效果等价于 int(score / 10)，clamp 到 [0, 10]。
    """
    if score_100 is None:
        return 0
    score = max(0.0, min(100.0, float(score_100)))
    result = int(score / 10)
    return min(10, max(0, result))


def generate_concise_reason(
    flags: list[str],
    total_score: float,
    evidence: list[str] | None = None,
    max_length: int = 10,
) -> str:
    """根据预检 flags 和总分生成精简的 AI 打分理由（默认 ≤10 字）

    通过（≥60）按分数段区分，列出内容问题（2-3 字短标签，逗号分隔）：
    - 90+  → "信息详尽"
    - 70-89 → "较完整" + 具体问题
    - 60-69 → "基本达标" + 具体问题
    未达标（<60）直接列出多个具体问题。
    """
    # 2-3 字短标签，仅需求内容反馈；短标签使 10 字内可容纳 2-3 个问题
    flag_labels = {
        "empty_description": "空描述",
        "too_short": "描述短",
        "customer_placeholder": "缺客户",
        "scenario_placeholder": "缺场景",
        "effect_placeholder": "缺效果",
        "no_customer_info": "缺客户",
        "no_images": "无截图",
        "vague_effect": "效果模糊",
        "vague_value": "价值模糊",
    }

    negative_flags = [f for f in flags if not f.startswith("has_")]

    if total_score is None:
        return "未打分"

    # ── 通过：按分数段区分 ──
    if total_score >= 90:
        return "信息详尽"

    if total_score >= 70:
        prefix = "较完整"
    elif total_score >= 60:
        prefix = "基本达标"
    else:
        prefix = ""

    # 贪心追加问题标签，逗号分隔
    parts = [prefix] if prefix else []
    current_len = len(prefix)
    for f in negative_flags:
        label = flag_labels.get(f, "")
        if not label:
            continue
        added_len = len(label) if not parts else len(label) + 1  # 1 = ","
        if current_len + added_len > max_length:
            break
        parts.append(label)
        current_len += added_len

    if len(parts) > (1 if prefix else 0):
        return ",".join(parts)
    if prefix:
        return prefix
    return "描述不充分"


def inspect_prd_text(prd_content: str | None, original_requirement: str | None) -> dict[str, Any]:
    """对 PRD 做可复现的结构化预检。"""
    prd = clean_plain_text(prd_content)
    original = clean_plain_text(original_requirement)
    checks = {
        "has_original_requirement": bool(original),
        "has_background": bool(re.search(r"背景|初步方案|方案描述", prd)),
        "has_scenario": bool(re.search(r"场景|现有流程|使用流程", prd)),
        "has_value": bool(re.search(r"价值|收益|提效|省钱|影响", prd)),
        "has_function_path": bool(re.search(r"功能路径|模块.{0,12}(页面|界面|功能)|路径", prd)),
        "has_adjustment": bool(re.search(r"调整点|改造|新增|修改|优化", prd)),
        "has_exception_or_boundary": bool(re.search(r"异常|边界|失败|限制|校验|权限", prd)),
        "has_acceptance": bool(re.search(r"验收标准|验收|断言|预期结果", prd)),
        "has_test_data": bool(re.search(r"测试数据|样例|示例数据|单号|账号", prd)),
        "has_monitoring": bool(re.search(r"埋点|监控|指标|数据监控", prd)),
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {"prd_content": prd, "original_requirement": original, "checks": checks, "missing": missing}


def normalize_dimension_scores(
    raw_dimensions: dict[str, Any] | None,
    limits: dict[str, float],
    deductions: dict[str, float] | None = None,
) -> tuple[dict[str, float], float, list[str]]:
    """将 LLM 各维度分数安全转换并限制在合法权重内，返回重算总分。"""
    raw_dimensions = raw_dimensions or {}
    normalized: dict[str, float] = {}
    warnings: list[str] = []
    deductions = deductions or {}
    for key, max_score in limits.items():
        raw = raw_dimensions.get(key, 0)
        if isinstance(raw, dict):
            raw = raw.get("score", 0)
        try:
            score = float(raw)
        except (TypeError, ValueError):
            score = 0.0
            warnings.append(f"{key} 非法，已按 0 处理")
        bounded = max(0.0, min(score, float(max_score)))
        deduction = float(deductions.get(key, 0))
        if deduction > 0:
            bounded = max(0.0, bounded - deduction)
            warnings.append(f"{key} 预检扣分 -{deduction}")
        if bounded != score:
            warnings.append(f"{key} 原始分 {score}，最终 {bounded}（上限 {max_score}）")
        normalized[key] = round(bounded, 1)
    return normalized, round(sum(normalized.values()), 1), warnings


def weighted_prd_caps(weights: dict[str, float], precheck: dict[str, Any]) -> dict[str, float]:
    """根据确定性结构缺失限制 PRD 单项分数上限，防止无内容却获得高分。"""
    checks = precheck.get("checks", {})
    caps = dict(weights)
    if not checks.get("has_original_requirement"):
        caps["requirement_coverage"] = min(caps["requirement_coverage"], weights["requirement_coverage"] * 0.5)
    if not checks.get("has_function_path"):
        caps["functional_detail"] = min(caps["functional_detail"], weights["functional_detail"] * 0.6)
    if not checks.get("has_adjustment"):
        caps["functional_detail"] = min(caps["functional_detail"], weights["functional_detail"] * 0.75)
    if not checks.get("has_exception_or_boundary"):
        caps["interaction_completeness"] = min(caps["interaction_completeness"], weights["interaction_completeness"] * 0.65)
    if not checks.get("has_acceptance"):
        caps["acceptance_criteria"] = min(caps["acceptance_criteria"], weights["acceptance_criteria"] * 0.4)
    return caps
