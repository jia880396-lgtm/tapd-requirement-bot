"""模块技能存储与运行时接线

把"需求可靠性打分 / 重复需求识别 / 需求分类 / PRD 分析"四个流程内化为 4 个 Skill。
每个 Skill 有多份版本（skill_versions），其中一份为生效版本（status=active）。
推理时通过 get_active_skill 读取生效版本；所有读取带进程内缓存，版本变更即失效。

设计要点（与 docs/skill_optimization_design.md 对应）：
- 上线即"行为不变"：seed_skills_if_needed 用现有代码常量初始化 4 个 active 版本，
  内容与写死的 .py 一致；pull 失败时各模块回退到原硬编码路径。
- 结构化规则（尤其分类树/术语/跨模块规则）外置为 rules_json，对准确率杠杆最大。
"""
import json
import time
import logging
from typing import Optional

from app.database import get_session_local

logger = logging.getLogger(__name__)

MODULE_KEYS = ["reliability", "duplicate", "classification", "prd"]

_MODULE_NAMES = {
    "reliability": "需求可靠性打分",
    "duplicate": "重复需求识别",
    "classification": "需求分类",
    "prd": "PRD 分析",
}

_MODULE_DESCRIPTIONS = {
    "reliability": "对单条用户需求做可靠性打分，输出总分、四维度分、是否通过、补充问题。",
    "duplicate": "对比历史需求库识别重复需求，输出是否重复、相似度、重复类型。",
    "classification": "将需求分类到旺店通 ERP 模块体系（一级/二级分类）。",
    "prd": "对比用户原始需求与 PRD，输出完整度评分与补充建议。",
}

# 进程内缓存：module_key -> (data_dict, version_id, timestamp)
_cache = {}
_CACHE_TTL = 60  # 秒


def _now() -> float:
    return time.time()


def _safe_json_loads(s, default):
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


def _get_db():
    SessionLocal = get_session_local()
    return SessionLocal()


def get_active_skill(module_key: str) -> Optional[dict]:
    """返回 module_key 的生效 Skill 版本内容。

    Returns:
        {
            "skill_id", "version_id", "version_no",
            "prompt_text", "rules"(dict), "params"(dict), "kb_context"
        } 或 None（无生效版本时）。
    """
    cached = _cache.get(module_key)
    if cached:
        data, version_id, ts = cached
        if _now() - ts < _CACHE_TTL:
            return data

    db = _get_db()
    try:
        from app.database import Skill, SkillVersion
        skill = db.query(Skill).filter(Skill.module_key == module_key).first()
        if not skill or not skill.active_version_id:
            return None
        ver = db.query(SkillVersion).filter(SkillVersion.id == skill.active_version_id).first()
        if not ver:
            return None
        data = {
            "skill_id": skill.id,
            "version_id": ver.id,
            "version_no": ver.version_no,
            "prompt_text": ver.prompt_text or "",
            "rules": _safe_json_loads(ver.rules_json, {}),
            "params": _safe_json_loads(ver.params_json, {}),
            "kb_context": ver.kb_context or "",
        }
        _cache[module_key] = (data, ver.id, _now())
        return data
    except Exception as e:
        logger.warning(f"[skill_store] get_active_skill({module_key}) 失败，回退到硬编码: {e}")
        return None
    finally:
        db.close()


def invalidate_skill(module_key: str) -> None:
    """版本变更后失效缓存（单进程内即时生效）。"""
    _cache.pop(module_key, None)


def get_skill_versions(skill_id: int, db=None) -> list:
    """返回某 Skill 的版本历史（按版本号倒序）。"""
    own = db is None
    if own:
        db = _get_db()
    try:
        from app.database import SkillVersion
        rows = (
            db.query(SkillVersion)
            .filter(SkillVersion.skill_id == skill_id)
            .order_by(SkillVersion.version_no.desc())
            .all()
        )
        return [
            {
                "id": v.id,
                "version_no": v.version_no,
                "status": v.status,
                "parent_version_id": v.parent_version_id,
                "prompt_text": v.prompt_text,
                "rules_json": v.rules_json,
                "params_json": v.params_json,
                "kb_context": v.kb_context,
                "optimizer_note": v.optimizer_note,
                "created_by": v.created_by,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in rows
        ]
    finally:
        if own:
            db.close()


def build_skill_dict_from_version(version) -> dict:
    """把一条 SkillVersion ORM 对象转成 get_active_skill 同款 dict（供评测覆盖指定版本）。"""
    return {
        "skill_id": version.skill_id,
        "version_id": version.id,
        "version_no": version.version_no,
        "prompt_text": version.prompt_text or "",
        "rules": _safe_json_loads(version.rules_json, {}),
        "params": _safe_json_loads(version.params_json, {}),
        "kb_context": version.kb_context or "",
    }


# ----------------------------------------------------------------------------
# 文本构建辅助（分类模块把结构化规则渲染为 prompt 文本）
# ----------------------------------------------------------------------------
def build_category_tree_text(tree: dict, descriptions: dict = None) -> str:
    """渲染分类树文本。descriptions 形如 CATEGORY_DESCRIPTIONS：
    - 值为 dict：{"_self": "...", "l2": "..."}
    - 值为 str：直接作为 l1 描述
    """
    lines = []
    for l1, l2_list in (tree or {}).items():
        l1_desc = ""
        if descriptions:
            d = descriptions.get(l1)
            if isinstance(d, dict):
                l1_desc = d.get("_self", "")
            elif isinstance(d, str):
                l1_desc = d
        header = f"### {l1}（{l1_desc}）" if l1_desc else f"### {l1}"
        lines.append(header)
        for l2 in (l2_list or []):
            l2_desc = ""
            if isinstance(descriptions.get(l1), dict):
                l2_desc = (descriptions.get(l1) or {}).get(l2, "")
            lines.append(f"  - {l2}：{l2_desc}")
    return "\n".join(lines)


def build_term_mapping_text(term_mapping) -> str:
    """term_mapping 支持两种形态：
    - dict: term -> [meaning, module]
    - list: [[term, meaning, module], ...]
    """
    lines = []
    if isinstance(term_mapping, dict):
        for term, v in term_mapping.items():
            meaning = v[0] if isinstance(v, (list, tuple)) else v
            module = v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else None
            mod_str = f" -> {module}" if module else ""
            lines.append(f"- {term}：{meaning}{mod_str}")
    elif isinstance(term_mapping, list):
        for item in term_mapping:
            if not isinstance(item, (list, tuple)):
                continue
            term = item[0]
            meaning = item[1] if len(item) > 1 else ""
            module = item[2] if len(item) > 2 else None
            mod_str = f" -> {module}" if module else ""
            lines.append(f"- {term}：{meaning}{mod_str}")
    return "\n".join(lines)


def build_rules_text(rules_list) -> str:
    if isinstance(rules_list, list):
        return "\n".join(f"{i + 1}. {r}" for i, r in enumerate(rules_list))
    return str(rules_list or "")


# ----------------------------------------------------------------------------
# 案例库 few-shot 示例构建（Phase 2 注入用）
# 加短 TTL 进程缓存：批量分类/打分时每条需求都会调用，避免反复打 DB。
# ----------------------------------------------------------------------------
_fewshot_cache = {}  # skill_id -> (text, ts)
_FEWSHOT_TTL = 120


def _format_fewshot_case(c, label: str, max_len: int) -> str:
    """格式化单条 few-shot 样例为文本块。

    label 标明该样例是正面还是反面校准示例；ai_result_json 存在时额外展示
    AI 原始评分（用于"误判修正"场景），不存在时仅展示正确评分（用于"参考样例"场景）。
    """
    try:
        ai = json.loads(c.ai_result_json) if c.ai_result_json else None
    except Exception:
        ai = None
    try:
        human = json.loads(c.human_result_json) if c.human_result_json else {}
    except Exception:
        human = {}
    desc = (c.requirement_desc or "")[:max_len]
    parts = [
        f"【{label}】",
        f"需求标题：{(c.requirement_title or '')[:max_len]}",
        f"需求描述：{desc}",
    ]
    if ai is not None:
        parts.append(f"AI 原始评分：{json.dumps(ai, ensure_ascii=False)[:max_len]}")
    parts.append(f"正确评分：{json.dumps(human, ensure_ascii=False)[:max_len]}")
    parts.append(f"判定原因：{(c.mismatch_reason or '')[:300]}")
    return "\n".join(parts)


def build_fewshot_examples(skill_id: int, k: int = 3, max_len: int = 600) -> str:
    """取案例库样本，格式化为 few-shot 文本（截断防 prompt 膨胀）。

    支持两类校准样例：
    - is_mismatch=True：反面示例（描述模糊/信息不全的需求，应给低分）
    - is_mismatch=False：正面示例（描述清晰/信息齐全的需求，应给高分）

    每类取最近 k 条；仅当案例库存在样本时才返回非空，否则返回空串
    （调用方据此跳过注入）。带 120s 进程缓存，避免批量推理反复查 DB。
    """
    cached = _fewshot_cache.get(skill_id)
    if cached:
        text, ts = cached
        if _now() - ts < _FEWSHOT_TTL:
            return text

    db = _get_db()
    try:
        from app.database import SkillCase
        # 反面示例（应低分）：is_mismatch=True
        neg_cases = (
            db.query(SkillCase)
            .filter(SkillCase.skill_id == skill_id, SkillCase.is_mismatch == True)  # noqa: E712
            .order_by(SkillCase.created_at.desc())
            .limit(k)
            .all()
        )
        # 正面示例（应高分）：is_mismatch=False
        pos_cases = (
            db.query(SkillCase)
            .filter(SkillCase.skill_id == skill_id, SkillCase.is_mismatch == False)  # noqa: E712
            .order_by(SkillCase.created_at.desc())
            .limit(k)
            .all()
        )
        if not neg_cases and not pos_cases:
            _fewshot_cache[skill_id] = ("", _now())
            return ""
        blocks = []
        for c in neg_cases:
            blocks.append(_format_fewshot_case(c, "反面示例（此类模糊需求应给低分）", max_len))
        for c in pos_cases:
            blocks.append(_format_fewshot_case(c, "正面示例（此类清晰需求应给高分）", max_len))
        text = "\n\n".join(blocks)
        _fewshot_cache[skill_id] = (text, _now())
        return text
    finally:
        db.close()


# ----------------------------------------------------------------------------
# 首次启动初始化：用现有代码常量播种 4 个 active 版本（行为不变）
# ----------------------------------------------------------------------------
def seed_skills_if_needed() -> None:
    db = _get_db()
    try:
        from app.database import Skill, SkillVersion

        if db.query(Skill).count() > 0:
            logger.info("[skill_store] 已存在 Skill，跳过初始化")
            return

        from app.prompts import (
            RELIABILITY_PROMPT, DUPLICATE_DETECTION_PROMPT, PRD_ANALYSIS_PROMPT,
        )
        from app.classification_kb import (
            CATEGORY_TREE, CATEGORY_DESCRIPTIONS, TERM_MAPPING, CROSS_MODULE_RULES,
        )

        seeds = []

        # 1) 可靠性打分
        # 阈值/问题数/聚焦/松紧度均有用户级配置（user_business_settings），
        # seed 不写死 params，避免系统默认值覆盖用户个性化配置。
        seeds.append({
            "module_key": "reliability",
            "prompt_text": RELIABILITY_PROMPT,
            "rules_json": {},
            "params_json": {},
            "kb_context": "",
        })

        # 2) 重复识别
        seeds.append({
            "module_key": "duplicate",
            "prompt_text": DUPLICATE_DETECTION_PROMPT,
            "rules_json": {},
            "params_json": {"similarity_threshold": 0.8},
            "kb_context": "",
        })

        # 3) 需求分类（结构化规则外置）
        term_mapping_list = [[t, m, mod] for t, (m, mod) in TERM_MAPPING.items()]
        seeds.append({
            "module_key": "classification",
            "prompt_text": _CLASSIFICATION_SYSTEM_TEMPLATE,
            "rules_json": {
                "category_tree": CATEGORY_TREE,
                "category_descriptions": CATEGORY_DESCRIPTIONS,
                "term_mapping": term_mapping_list,
                "cross_module_rules": CROSS_MODULE_RULES,
            },
            "params_json": {"temperature": 0.1},
            "kb_context": "",
        })

        # 4) PRD 分析
        # 松紧度/权重/及格线均有用户级配置（user_business_settings），
        # seed 不写死 params，避免系统默认值覆盖用户个性化配置。
        seeds.append({
            "module_key": "prd",
            "prompt_text": PRD_ANALYSIS_PROMPT,
            "rules_json": {},
            "params_json": {},
            "kb_context": "",
        })

        for s in seeds:
            skill = Skill(
                module_key=s["module_key"],
                name=_MODULE_NAMES.get(s["module_key"], s["module_key"]),
                description=_MODULE_DESCRIPTIONS.get(s["module_key"], ""),
            )
            db.add(skill)
            db.flush()  # 取 skill.id
            ver = SkillVersion(
                skill_id=skill.id,
                version_no=1,
                prompt_text=s["prompt_text"],
                rules_json=json.dumps(s["rules_json"], ensure_ascii=False),
                params_json=json.dumps(s["params_json"], ensure_ascii=False),
                kb_context=s["kb_context"],
                status="active",
                created_by="seed",
            )
            db.add(ver)
            db.flush()
            skill.active_version_id = ver.id

        db.commit()
        logger.info("[skill_store] 已初始化 4 个模块 Skill（active v1）")
    except Exception as e:
        db.rollback()
        logger.error(f"[skill_store] 初始化 Skill 失败（不影响现有逻辑，仍走硬编码）: {e}")
    finally:
        db.close()


# 分类系统 prompt 模板（与 classifier.py 中常量保持一致，供播种与渲染共用）
_CLASSIFICATION_SYSTEM_TEMPLATE = """你是一个旺店通ERP系统的需求分类专家。你的任务是根据需求标题和描述，将需求分类到正确的模块。

## 重要约束
1. category_l1 必须严格从上述一级分类名称中选择。
2. **category_l2 必填规则**：一级分类存在二级分类列表时，必须从中选择最贴近的二级分类，**不得留空**；仅当一级分类本身没有二级分类列表时才允许填空字符串。
3. 信息不足、跨模块冲突或无法在现有分类树中可靠判断时，仍输出最接近的合法分类，但 confidence 必须为 low，并在 reason 中说明不确定原因。
4. 不得仅因标题出现平台名称就归『对接』：只有诉求本身是授权、接口、同步、下载、平台接入等对接问题时才归对接；若平台名称只是业务发生场景，应按订单/商品/售后等实际功能模块分类。

## 模块定义（背景知识）

{kb_context}

## 模块分类体系
{category_tree}

## 专业术语映射表
{term_mapping}

## 跨模块优先级规则
{rules}

## 输出要求

请严格按照以下JSON格式输出，不要输出其他任何内容：
```json
{{
  "category_l1": "一级分类名称",
  "category_l2": "二级分类名称（一级有二级列表时必填，不得留空）",
  "confidence": "high/medium/low",
  "reason": "一句话说明分类依据"
}}
```
"""
