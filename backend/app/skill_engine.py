"""Skill 评测引擎与优化器

- run_evaluation：在案例库上对比"生效版本 vs 指定草稿版本"的准确率（temperature=0 保证可复现）。
- run_optimization：基于误判案例，调用 LLM 产出一份 draft 版本的 Skill（强制 JSON 输出 + 校验）。

两条链路都依赖 DeepSeek 可用；缺 Key 时返回清晰错误，不污染数据。
"""
import asyncio
import json
import logging
from datetime import datetime
from sqlalchemy import func

from app.config import settings
from app.user_settings import get_active_setting
from app.database import get_session_local
from app.skill_store import build_skill_dict_from_version
from app.llm_client import deepseek_client, _parse_json_content, LLMClientError

logger = logging.getLogger(__name__)

# 各模块最大 prompt/规则长度（优化器产出超长直接拒绝，防 prompt 膨胀）
_MAX_PROMPT = 8000
_MAX_RULES = 20000
_MAX_PARAMS = 5000

_OPTIMIZER_SYSTEM = (
    "你是需求处理系统的 Skill 优化专家。你的任务是：根据下面给出的『误判案例』，"
    "修订该模块的提示词与结构化规则，使模型在同类案例上给出与人工一致的结果。\n"
    "严格要求：只输出一个 JSON 对象，不要输出任何解释性文字。\n"
    "JSON 字段：\n"
    "  prompt_text: 修订后的主提示词（保留 {placeholder}）\n"
    "  rules_json: 修订后的结构化规则对象\n"
    "  params_json: 修订后的参数对象\n"
    "  changes: 改动点列表（字符串数组）\n"
    "  rationale: 为什么这样改能减少误判（一段中文）\n"
    "不要引入非法分类；如需新增分类，请在 changes 中显式标注『建议新增分类 X（待人工确认）』。"
)

_MODULE_NOTES = {
    "reliability": "params_json 可含：reliability_threshold(数值), question_max_count(整数), question_focus(enum: problem_scenario|all), scoring_strictness(enum: loose|standard|strict)。",
    "duplicate": "params_json 可含：similarity_threshold(0~1 数值，重复判定硬阈值)。",
    "classification": "rules_json 必须含：category_tree(一级->二级列表), category_descriptions(描述), term_mapping(列表), cross_module_rules(列表)。category_tree 的一级键必须保持为既有集合的子集，禁止静默引入非法一级分类。",
    "prd": "params_json 可含：prd_strictness(enum), prd_weight_coverage/functional/interaction/acceptance(数值权重), prd_pass_threshold(数值)。",
}


# ----------------------------------------------------------------------------
# 并发执行工具：评测与 A/B 对比需对多条数据逐一调用 LLM，
# 串行耗时远超 HTTP 请求超时（前端 60s），故并发执行并限流（保守 4 并发）。
# ----------------------------------------------------------------------------
class _TaskError:
    """并发任务内异常的统一包装（gather 不抛异常，结果按输入顺序返回）。"""

    def __init__(self, message: str):
        self.message = message


async def _run_concurrent(items: list, fn, limit: int = 4) -> list:
    """对 items 并发执行 fn(item)，单条异常包装为 _TaskError，不中断整体。"""
    if not items:
        return []
    sem = asyncio.Semaphore(limit)

    async def bounded(item):
        async with sem:
            try:
                return await fn(item)
            except Exception as e:  # noqa: BLE001 — 单条失败不应拖垮整批
                return _TaskError(str(e)[:200])

    return await asyncio.gather(*(bounded(item) for item in items))


def _prod_hard_defect(record) -> bool:
    """从历史打分详情的预检 flags 还原生产当时的硬缺陷判定。

    与 quality_rules.inspect_requirement_text 的 has_hard_defect 口径一致；
    历史记录未存 flags 时返回 False（按分数近似比较）。
    """
    try:
        detail = json.loads(record.reliability_detail or "{}")
        flags = set((detail.get("precheck") or {}).get("flags") or [])
        return bool({"empty_description", "customer_placeholder", "scenario_placeholder"} & flags)
    except Exception:
        return False


# ----------------------------------------------------------------------------
# 单条案例评测（按模块分派）
# ----------------------------------------------------------------------------
async def _eval_one(module_key: str, case, skill_override):
    """对单条案例用指定 Skill 版本跑一次推理并对比人工结果。返回 {ok, ai, human, detail}。"""
    human = {}
    try:
        human = json.loads(case.human_result_json) if case.human_result_json else {}
    except Exception:
        human = {}

    if module_key == "classification":
        from app.classifier import _classify_with_llm
        result = await _classify_with_llm(
            case.requirement_title, case.requirement_desc, skill=skill_override, temperature=0
        )
        ai_l1 = result.get("category_l1")
        ai_l2 = result.get("category_l2", "")
        human_l1 = human.get("category_l1")
        human_l2 = human.get("category_l2", "")
        exact = (ai_l1 == human_l1 and ai_l2 == human_l2)
        l1_ok = (ai_l1 == human_l1)
        return {"ok": exact, "l1_ok": l1_ok, "ai": {"category_l1": ai_l1, "category_l2": ai_l2}, "human": human}

    if module_key == "reliability":
        result = await deepseek_client.score_reliability(
            case.requirement_title, case.requirement_desc, skill=skill_override, temperature=0
        )
        dims = result.get("dimensions", {})
        total = sum(d.get("score", 0) for d in dims.values() if isinstance(d, dict))
        ai_pass = total >= float(get_active_setting("reliability_threshold"))
        human_pass = bool(human.get("pass"))
        return {"ok": ai_pass == human_pass, "ai": {"pass": ai_pass, "total": total}, "human": human}

    if module_key == "prd":
        result = await deepseek_client.analyze_prd(
            case.requirement_desc, case.requirement_title, skill=skill_override, temperature=0
        )
        score = result.get("completeness_score", 0)
        ai_pass = score >= float(get_active_setting("prd_pass_threshold"))
        human_pass = bool(human.get("pass"))
        return {"ok": ai_pass == human_pass, "ai": {"pass": ai_pass, "score": score}, "human": human}

    if module_key == "duplicate":
        ai_meta = {}
        try:
            ai_meta = json.loads(case.ai_result_json) if case.ai_result_json else {}
        except Exception:
            ai_meta = {}
        historical = ai_meta.get("historical_requirements", "")
        if not historical:
            return {"ok": None, "skipped": True, "reason": "缺少历史需求文本，无法评测重复识别", "human": human}
        result = await deepseek_client.detect_duplicate(
            case.requirement_title, case.requirement_desc, historical, skill=skill_override, temperature=0
        )
        ai_dup = bool(result.get("is_duplicate"))
        human_dup = bool(human.get("is_duplicate"))
        return {"ok": ai_dup == human_dup, "ai": {"is_duplicate": ai_dup}, "human": human}

    return {"ok": None, "skipped": True, "reason": f"未知模块 {module_key}"}


async def _evaluate_cases(module_key: str, cases, skill_override):
    evaluated, correct, l1_correct = 0, 0, 0
    per_case = []

    async def _eval_one_safe(case):
        try:
            return await _eval_one(module_key, case, skill_override)
        except LLMClientError as e:
            return _TaskError(f"LLM 调用失败: {e}")
        except Exception as e:  # noqa: BLE001
            return _TaskError(str(e)[:200])

    results = await _run_concurrent(list(cases), _eval_one_safe)
    for case, r in zip(cases, results):
        if isinstance(r, _TaskError):
            per_case.append({"case_id": case.id, "error": r.message})
            continue
        if r.get("skipped"):
            per_case.append({"case_id": case.id, "skipped": True, "reason": r.get("reason")})
            continue
        evaluated += 1
        if r.get("ok"):
            correct += 1
        if module_key == "classification" and r.get("l1_ok"):
            l1_correct += 1
        per_case.append({
            "case_id": case.id,
            "ok": r.get("ok"),
            "ai": r.get("ai"),
            "human": r.get("human"),
        })
    accuracy = round(correct / evaluated, 4) if evaluated else None
    l1_accuracy = round(l1_correct / evaluated, 4) if (module_key == "classification" and evaluated) else None
    return {
        "evaluated": evaluated,
        "correct": correct,
        "accuracy": accuracy,
        "l1_accuracy": l1_accuracy,
        "per_case": per_case,
    }


# ----------------------------------------------------------------------------
# 评测入口
# ----------------------------------------------------------------------------
async def run_evaluation(module_key: str, draft_version_id=None, db=None):
    """对 module_key 跑评测：生效版本 vs（可选）草稿版本。返回对比结果。"""
    own = db is None
    if own:
        db = get_session_local()()
    try:
        from app.database import Skill, SkillVersion, SkillCase
        skill = db.query(Skill).filter(Skill.module_key == module_key).first()
        if not skill:
            return {"error": f"未找到模块 Skill: {module_key}"}
        active_ver = db.query(SkillVersion).filter(SkillVersion.id == skill.active_version_id).first()
        draft_ver = None
        if draft_version_id:
            draft_ver = db.query(SkillVersion).filter(SkillVersion.id == draft_version_id).first()
            if not draft_ver:
                return {"error": f"未找到草稿版本: {draft_version_id}"}
        cases = db.query(SkillCase).filter(SkillCase.skill_id == skill.id).all()

        active_result = await _evaluate_cases(
            module_key, cases, build_skill_dict_from_version(active_ver) if active_ver else None
        )
        draft_result = None
        if draft_ver:
            draft_result = await _evaluate_cases(module_key, cases, build_skill_dict_from_version(draft_ver))

        delta = None
        if draft_result and active_result.get("accuracy") is not None and draft_result.get("accuracy") is not None:
            delta = round(draft_result["accuracy"] - active_result["accuracy"], 4)

        return {
            "module_key": module_key,
            "total_cases": len(cases),
            "active": active_result,
            "draft": draft_result,
            "delta": delta,
        }
    finally:
        if own:
            db.close()


# ----------------------------------------------------------------------------
# 优化器
# ----------------------------------------------------------------------------
def _format_cases_for_optimizer(cases) -> str:
    blocks = []
    for c in cases:
        ai, human = "{}", "{}"
        try:
            ai = c.ai_result_json if c.ai_result_json else "{}"
            human = c.human_result_json if c.human_result_json else "{}"
        except Exception:
            pass
        blocks.append(
            "【案例】\n"
            f"需求标题：{(c.requirement_title or '')[:400]}\n"
            f"AI 结果：{ai[:800]}\n"
            f"人工正确结果：{human[:800]}\n"
            f"误判原因：{(c.mismatch_reason or '')[:300]}"
        )
    return "\n\n".join(blocks)


def _build_optimizer_prompt(module_key: str, current: dict, case_text: str) -> str:
    return (
        f"## 模块：{module_key}\n"
        f"{_MODULE_NOTES.get(module_key, '')}\n\n"
        f"## 当前 Skill（生效版本）\n"
        f"prompt_text:\n{current['prompt_text']}\n\n"
        f"rules_json:\n{json.dumps(current['rules_json'], ensure_ascii=False)}\n\n"
        f"params_json:\n{json.dumps(current['params_json'], ensure_ascii=False)}\n\n"
        f"## 误判案例（AI 结果 != 人工正确结果）\n{case_text}\n\n"
        f"## 请输出修订后的 Skill JSON"
    )


def _validate_optimizer_output(module_key: str, current: dict, parsed: dict) -> dict:
    """校验优化器输出：必填字段、长度上限、分类合法性。非法则抛 ValueError。"""
    prompt_text = parsed.get("prompt_text")
    rules_json = parsed.get("rules_json")
    params_json = parsed.get("params_json")
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ValueError("优化器未返回有效的 prompt_text")
    if not isinstance(rules_json, dict):
        raise ValueError("rules_json 必须为对象")
    if not isinstance(params_json, dict):
        raise ValueError("params_json 必须为对象")
    if len(prompt_text) > _MAX_PROMPT:
        raise ValueError(f"prompt_text 超过长度上限 {_MAX_PROMPT}")
    if len(json.dumps(rules_json, ensure_ascii=False)) > _MAX_RULES:
        raise ValueError(f"rules_json 超过长度上限 {_MAX_RULES}")
    if len(json.dumps(params_json, ensure_ascii=False)) > _MAX_PARAMS:
        raise ValueError(f"params_json 超过长度上限 {_MAX_PARAMS}")

    if module_key == "classification":
        current_l1 = set((current.get("rules_json") or {}).get("category_tree", {}).keys())
        new_l1 = set((rules_json or {}).get("category_tree", {}).keys())
        illegal = new_l1 - current_l1
        if illegal:
            raise ValueError(f"优化器引入了非法一级分类（不在既有集合内）：{', '.join(illegal)}。如需新增，请在 changes 中标注待人工确认。")
    return {"prompt_text": prompt_text, "rules_json": rules_json, "params_json": params_json}


async def run_optimization(module_key: str, db=None, created_by: str = "optimizer", max_cases: int = 50):
    """基于误判案例产出一份 draft 版本的 Skill。返回 {version_id, version_no, changes, rationale}。"""
    own = db is None
    if own:
        db = get_session_local()()
    try:
        from app.database import Skill, SkillVersion, SkillCase
        skill = db.query(Skill).filter(Skill.module_key == module_key).first()
        if not skill:
            raise ValueError(f"未找到模块 Skill: {module_key}")
        active_ver = db.query(SkillVersion).filter(SkillVersion.id == skill.active_version_id).first()

        cases = (
            db.query(SkillCase)
            .filter(SkillCase.skill_id == skill.id, SkillCase.is_mismatch == True)  # noqa: E712
            .order_by(SkillCase.created_at.desc())
            .limit(max_cases)
            .all()
        )
        if len(cases) < 3:
            raise ValueError(f"误判案例不足（当前 {len(cases)} 条，至少需 3 条）才能优化；请先积累案例库。")

        current = {
            "prompt_text": active_ver.prompt_text if active_ver else "",
            "rules_json": json.loads(active_ver.rules_json) if active_ver and active_ver.rules_json else {},
            "params_json": json.loads(active_ver.params_json) if active_ver and active_ver.params_json else {},
        }
        case_text = _format_cases_for_optimizer(cases)
        optimizer_prompt = _build_optimizer_prompt(module_key, current, case_text)

        content = await deepseek_client.chat(
            optimizer_prompt, system=_OPTIMIZER_SYSTEM, temperature=0.2
        )
        parsed = _parse_json_content(content)
        validated = _validate_optimizer_output(module_key, current, parsed)

        max_no = db.query(func.max(SkillVersion.version_no)).filter(SkillVersion.skill_id == skill.id).scalar() or 0
        draft = SkillVersion(
            skill_id=skill.id,
            version_no=max_no + 1,
            prompt_text=validated["prompt_text"],
            rules_json=json.dumps(validated["rules_json"], ensure_ascii=False),
            params_json=json.dumps(validated["params_json"], ensure_ascii=False),
            kb_context=active_ver.kb_context if active_ver else "",
            status="draft",
            parent_version_id=active_ver.id if active_ver else None,
            optimizer_note=parsed.get("rationale", ""),
            created_by=created_by,
        )
        db.add(draft)
        db.commit()
        return {
            "version_id": draft.id,
            "version_no": draft.version_no,
            "changes": parsed.get("changes", []),
            "rationale": parsed.get("rationale", ""),
        }
    finally:
        if own:
            db.close()


# ----------------------------------------------------------------------------
# Phase 4：周期化工作流（定期复盘 / A-B 影子对比）
# ----------------------------------------------------------------------------
async def run_periodic_review(module_key: str, db=None, created_by: str = "scheduler"):
    """定期复盘：统计上次复盘以来新增的误判案例，足够则跑优化+评测，写复盘日志。

    关键安全约束：复盘只产出草稿版本 + 记录评测对比，**绝不自动激活**；是否采纳由管理员在界面决定。
    """
    own = db is None
    if own:
        db = get_session_local()()
    try:
        from app.database import Skill, SkillCase, SkillReviewLog
        skill = db.query(Skill).filter(Skill.module_key == module_key).first()
        if not skill:
            return {"status": "error", "reason": f"未找到模块 Skill: {module_key}"}

        # 上次复盘时间（取最近一条复盘日志）
        last = (
            db.query(func.max(SkillReviewLog.run_at))
            .filter(SkillReviewLog.skill_id == skill.id)
            .scalar()
        )
        q = db.query(SkillCase).filter(SkillCase.skill_id == skill.id, SkillCase.is_mismatch == True)  # noqa: E712
        if last:
            q = q.filter(SkillCase.created_at > last)
        new_case_count = q.count()
        total_cases = db.query(SkillCase).filter(SkillCase.skill_id == skill.id).count()

        if new_case_count < 3:
            _write_review_log(
                db, skill.id, module_key, new_case_count, total_cases,
                None, None, None, None, "none",
                "新增误判案例不足 3 条，跳过优化。", created_by,
            )
            return {
                "status": "skipped", "module_key": module_key,
                "new_case_count": new_case_count, "total_cases": total_cases,
                "reason": "新增误判案例不足 3 条",
            }

        # 1) 跑优化器（产出草稿）
        try:
            opt = await run_optimization(module_key, db=db, created_by="auto-review", max_cases=50)
            draft_version_id = opt.get("version_id")
            draft_no = opt.get("version_no")
        except Exception as e:
            _write_review_log(
                db, skill.id, module_key, new_case_count, total_cases,
                None, None, None, None, "none",
                f"优化器失败: {e}", created_by,
            )
            return {
                "status": "error", "module_key": module_key,
                "new_case_count": new_case_count, "reason": f"优化器失败: {e}",
            }

        # 2) 评测 生效版本 vs 草稿
        eval_res = await run_evaluation(module_key, draft_version_id=draft_version_id, db=db)
        active_acc = (eval_res.get("active") or {}).get("accuracy")
        draft_acc = (eval_res.get("draft") or {}).get("accuracy")
        delta = eval_res.get("delta")

        # 3) 建议（仅建议，不自动执行）
        if draft_acc is not None and active_acc is not None:
            if delta and delta > 0 and draft_acc >= 0.5:
                recommendation = "adopt"
            elif delta and delta > 0:
                recommendation = "review"
            else:
                recommendation = "skip"
        else:
            recommendation = "none"

        note = f"基于 {new_case_count} 条新增误判案例优化，产出草稿 v{draft_no}。"
        _write_review_log(
            db, skill.id, module_key, new_case_count, total_cases,
            draft_version_id, active_acc, draft_acc, delta, recommendation, note, created_by,
        )
        return {
            "status": "reviewed", "module_key": module_key,
            "new_case_count": new_case_count, "draft_version_id": draft_version_id,
            "active_accuracy": active_acc, "draft_accuracy": draft_acc,
            "delta": delta, "recommendation": recommendation,
        }
    finally:
        if own:
            db.close()


def _write_review_log(db, skill_id, module_key, new_case_count, total_cases,
                       draft_version_id, active_acc, draft_acc, delta, recommendation, note, created_by):
    from app.database import SkillReviewLog
    log = SkillReviewLog(
        skill_id=skill_id, module_key=module_key, run_at=datetime.now(),
        new_case_count=new_case_count, total_cases=total_cases,
        draft_version_id=draft_version_id,
        active_accuracy=active_acc, draft_accuracy=draft_acc, delta=delta,
        recommendation=recommendation, note=note, created_by=created_by,
    )
    db.add(log)
    db.commit()


async def run_ab_compare(module_key: str, candidate_version_id: int, sample_size: int = 20, db=None):
    """A/B 影子对比：在近期线上数据上对比 生效版本 vs 候选版本 的"决策变化率"（只读，不写回生产）。

    把候选（草稿）版本重跑在最近一批线上数据上，与其生产结果比对，量化"若采纳候选会改变多少决策"，
    作为人工是否采纳的依据。重复识别模块暂不支持（需历史库比对，成本高）。
    """
    own = db is None
    if own:
        db = get_session_local()()
    try:
        from app.database import Skill, SkillVersion
        from app.skill_store import build_skill_dict_from_version
        skill = db.query(Skill).filter(Skill.module_key == module_key).first()
        if not skill or not skill.active_version_id:
            return {"error": f"未找到模块 Skill 或生效版本: {module_key}"}
        candidate_ver = db.query(SkillVersion).filter(SkillVersion.id == candidate_version_id).first()
        if not candidate_ver:
            return {"error": f"未找到候选版本: {candidate_version_id}"}
        # 防御：候选模板必须含该模块的输出结构标记，否则渲染不出结果
        # （如选中内容为占位文本的历史测试版本，会表现为候选分数全 0）
        _required_markers = {
            "reliability": ("dimensions", "评分维度"),
            "prd": ("completeness_score", "评分结构"),
            "classification": ("category_l1", "分类输出结构"),
        }
        if module_key in _required_markers:
            marker, label = _required_markers[module_key]
            if marker not in (candidate_ver.prompt_text or ""):
                return {"error": f"候选版本 v{candidate_ver.version_no} 的提示词缺少{label}（{marker}），可能是无效测试版本，请选择其他版本。"}
        active_override = build_skill_dict_from_version(
            db.query(SkillVersion).filter(SkillVersion.id == skill.active_version_id).first()
        )
        candidate_override = build_skill_dict_from_version(candidate_ver)

        per_sample = []
        disagreements = 0
        compared = 0
        sampled = 0
        sample_size = max(1, min(sample_size, 50))

        if module_key == "classification":
            from app.database import Classification
            from app.classifier import _classify_with_llm as _cls_llm
            rows = db.query(Classification).order_by(Classification.processed_at.desc()).limit(sample_size * 3).all()
            samples = []
            for c in rows:
                if not c.story_title:
                    continue
                samples.append(c)
                sampled += 1
                if sampled >= sample_size:
                    break

            results = await _run_concurrent(
                samples,
                lambda c: _cls_llm(c.story_title, c.story_description or "", skill=candidate_override, temperature=0),
            )
            for c, r in zip(samples, results):
                if isinstance(r, _TaskError):
                    per_sample.append({"id": c.id, "error": r.message})
                    continue
                prod_l1, prod_l2 = c.category_l1, c.category_l2 or ""
                cand_l1, cand_l2 = r.get("category_l1"), r.get("category_l2") or ""
                compared += 1
                if not (prod_l1 == cand_l1 and prod_l2 == cand_l2):
                    disagreements += 1
                per_sample.append({
                    "id": c.id, "story_id": c.story_id, "workspace_id": c.workspace_id,
                    "title": (c.story_title or "")[:80],
                    "production": {"l1": prod_l1, "l2": prod_l2},
                    "candidate": {"l1": cand_l1, "l2": cand_l2},
                })

        elif module_key == "reliability":
            from app.database import UserRequirementJob
            from app.quality_rules import (
                inspect_requirement_text, requirement_precheck_score, normalize_dimension_scores,
            )
            from app.reliability_scorer import _format_precheck
            rows = db.query(UserRequirementJob).order_by(UserRequirementJob.updated_at.desc()).limit(sample_size * 3).all()
            thr = float(get_active_setting("reliability_threshold"))
            samples = []
            for c in rows:
                if not c.title:
                    continue
                samples.append(c)
                sampled += 1
                if sampled >= sample_size:
                    break

            async def _score_like_production(c):
                """与 reliability_scorer.score_single_requirement 对齐：
                同一预检文本注入、同一维度截断与上限归一化、同一硬缺陷判定，
                避免 A/B 重跑口径比生产宽松导致候选分数系统性偏高。"""
                precheck = inspect_requirement_text(c.title, c.description)
                score_rules = requirement_precheck_score(precheck)
                r = await deepseek_client.score_reliability(
                    title=precheck["title"],
                    description=precheck["description"],
                    quality_precheck=_format_precheck(precheck, score_rules),
                    skill=candidate_override,
                    temperature=0,
                )
                normalized, total, _warnings = normalize_dimension_scores(
                    r.get("dimensions", {}), score_rules["caps"]
                )
                return total, precheck

            results = await _run_concurrent(samples, _score_like_production)
            for c, r in zip(samples, results):
                if isinstance(r, _TaskError):
                    per_sample.append({"id": c.id, "error": r.message})
                    continue
                total, precheck = r
                cand_pass = total >= thr and not precheck["has_hard_defect"]
                prod_pass = (c.reliability_score or 0) >= thr and not _prod_hard_defect(c)
                compared += 1
                if cand_pass != prod_pass:
                    disagreements += 1
                # 明细结构与 classification 分支一致（production/candidate 嵌套对象），前端统一渲染
                per_sample.append({
                    "id": c.id, "story_id": c.story_id, "workspace_id": c.workspace_id,
                    "title": (c.title or "")[:80],
                    "production": {"pass": prod_pass, "score": c.reliability_score},
                    "candidate": {"pass": cand_pass, "score": total},
                })

        elif module_key == "prd":
            from app.database import PrdAnalysisJob
            from app.quality_rules import inspect_prd_text, normalize_dimension_scores, weighted_prd_caps
            from app.prd_analyzer import _format_prd_precheck, _PRD_WEIGHT_KEYS
            rows = db.query(PrdAnalysisJob).order_by(PrdAnalysisJob.updated_at.desc()).limit(sample_size * 3).all()
            thr = float(get_active_setting("prd_pass_threshold"))
            samples = []
            for c in rows:
                if not c.title:
                    continue
                samples.append(c)
                sampled += 1
                if sampled >= sample_size:
                    break

            async def _analyze_like_production(c):
                """与 prd_analyzer.analyze_prd_for_record 对齐：
                同一结构预检注入、同一权重上限归一化，避免 A/B 重跑口径比生产宽松。"""
                precheck = inspect_prd_text(c.prd_content, c.original_requirement)
                weights = {key: float(get_active_setting(setting_key)) for key, setting_key in _PRD_WEIGHT_KEYS.items()}
                caps = weighted_prd_caps(weights, precheck)
                r = await deepseek_client.analyze_prd(
                    prd_content=precheck["prd_content"],
                    original_requirement=precheck["original_requirement"],
                    quality_precheck=_format_prd_precheck(precheck),
                    skill=candidate_override,
                    temperature=0,
                )
                normalized, total, _warnings = normalize_dimension_scores(r.get("dimensions", {}), caps)
                return total

            results = await _run_concurrent(samples, _analyze_like_production)
            for c, r in zip(samples, results):
                if isinstance(r, _TaskError):
                    per_sample.append({"id": c.id, "error": r.message})
                    continue
                total = r
                cand_pass = total >= thr
                prod_pass = (c.completeness_score or 0) >= thr
                compared += 1
                if cand_pass != prod_pass:
                    disagreements += 1
                # 明细结构与 classification 分支一致（production/candidate 嵌套对象），前端统一渲染
                per_sample.append({
                    "id": c.id, "story_id": c.story_id, "workspace_id": c.workspace_id,
                    "title": (c.title or "")[:80],
                    "production": {"pass": prod_pass, "score": c.completeness_score},
                    "candidate": {"pass": cand_pass, "score": total},
                })

        else:
            return {"error": f"模块 {module_key} 暂不支持 A/B 实跑对比（重复识别需历史库，成本较高）"}

        change_rate = round(disagreements / compared, 4) if compared else None
        agreement_rate = round(1 - disagreements / compared, 4) if compared else None
        return {
            "module_key": module_key,
            "candidate_version_id": candidate_version_id,
            "sampled": sampled,
            "compared": compared,
            "disagreements": disagreements,
            "agreement_rate": agreement_rate,
            "change_rate": change_rate,
            "per_sample": per_sample,
        }
    finally:
        if own:
            db.close()
