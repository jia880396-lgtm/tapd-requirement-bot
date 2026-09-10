"""API 路由：模块技能（四流程内化 + 案例库 + 自优化）

权限：
- 查看 Skill / 案例：已登录即可（require_user）
- 编辑版本 / 激活 / 优化 / 评测：管理员（require_admin）
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.database import get_db, get_session_local, Skill, SkillVersion, SkillCase, SkillReviewLog
from app.auth import require_user, require_admin
from app.skill_store import get_active_skill, get_skill_versions, invalidate_skill, MODULE_KEYS
from app.skill_engine import run_evaluation, run_optimization, run_periodic_review, run_ab_compare
from app.user_settings import activate_user_business_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])


# ----------------------------- 请求体 -----------------------------
class CreateVersionRequest(BaseModel):
    prompt_text: str = ""
    rules_json: str = "{}"
    params_json: str = "{}"
    kb_context: str = ""


class AddCaseRequest(BaseModel):
    requirement_id: Optional[str] = None
    requirement_title: str
    requirement_desc: str = ""
    ai_result_json: str = "{}"
    human_result_json: str = "{}"
    is_mismatch: bool = True
    mismatch_reason: str = ""
    source: str = "manual"


class EvaluateRequest(BaseModel):
    draft_version_id: Optional[int] = None


class OptimizeRequest(BaseModel):
    max_cases: int = 50


class ABCompareRequest(BaseModel):
    candidate_version_id: int
    sample_size: int = 20


class ReviewRunRequest(BaseModel):
    module_key: Optional[str] = None  # 不传则复盘全部 4 个模块


# ----------------------------- 辅助 -----------------------------
def _serialize_version(v: SkillVersion) -> dict:
    return {
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


def _serialize_skill(db: Session, skill: Skill) -> dict:
    active = None
    if skill.active_version_id:
        v = db.query(SkillVersion).filter(SkillVersion.id == skill.active_version_id).first()
        if v:
            active = {
                "version_id": v.id,
                "version_no": v.version_no,
                "status": v.status,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "prompt_text": v.prompt_text,
                "rules_json": v.rules_json,
                "params_json": v.params_json,
                "kb_context": v.kb_context,
            }
    return {
        "id": skill.id,
        "module_key": skill.module_key,
        "name": skill.name,
        "description": skill.description,
        "active_version_id": skill.active_version_id,
        "active_version": active,
    }


# ----------------------------- 列表 / 详情 -----------------------------
@router.get("")
async def list_skills(request: Request, db: Session = Depends(get_db)):
    """列出 4 个模块 Skill + 生效版本摘要"""
    require_user(request)
    skills = db.query(Skill).order_by(Skill.id).all()
    return {"data": [_serialize_skill(db, s) for s in skills]}


@router.get("/{module_key}")
async def get_skill(module_key: str, request: Request, db: Session = Depends(get_db)):
    """获取单个 Skill 详情（含生效版本全文）"""
    require_user(request)
    skill = db.query(Skill).filter(Skill.module_key == module_key).first()
    if not skill:
        raise HTTPException(status_code=404, detail="未找到该模块 Skill")
    return _serialize_skill(db, skill)


# ----------------------------- 版本管理 -----------------------------
@router.get("/{module_key}/versions")
async def list_versions(module_key: str, request: Request, db: Session = Depends(get_db)):
    """版本历史"""
    require_user(request)
    skill = db.query(Skill).filter(Skill.module_key == module_key).first()
    if not skill:
        raise HTTPException(status_code=404, detail="未找到该模块 Skill")
    return {"data": get_skill_versions(skill.id, db)}


@router.post("/{module_key}/versions")
async def create_version(module_key: str, body: CreateVersionRequest, request: Request, db: Session = Depends(get_db)):
    """人工创建草稿版本（编辑 prompt/rules/params）"""
    require_admin(request)
    skill = db.query(Skill).filter(Skill.module_key == module_key).first()
    if not skill:
        raise HTTPException(status_code=404, detail="未找到该模块 Skill")
    # 校验 JSON 合法性
    try:
        json.loads(body.rules_json)
        json.loads(body.params_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"rules_json/params_json 不是合法 JSON: {e}")

    max_no = db.query(func.max(SkillVersion.version_no)).filter(
        SkillVersion.skill_id == skill.id
    ).scalar() or 0
    ver = SkillVersion(
        skill_id=skill.id,
        version_no=max_no + 1,
        prompt_text=body.prompt_text,
        rules_json=body.rules_json,
        params_json=body.params_json,
        kb_context=body.kb_context,
        status="draft",
        # 记录父版本，便于「采纳草稿后不如预期」时一键回滚
        parent_version_id=skill.active_version_id,
        created_by=request.headers.get("x-user", "admin"),
    )
    db.add(ver)
    db.commit()
    db.refresh(ver)
    return {"status": "success", "data": _serialize_version(ver)}


@router.post("/{module_key}/versions/{vid}/activate")
async def activate_version(module_key: str, vid: int, request: Request, db: Session = Depends(get_db)):
    """将指定版本设为生效，并失效旧生效版本 + 进程缓存"""
    require_admin(request)
    skill = db.query(Skill).filter(Skill.module_key == module_key).first()
    if not skill:
        raise HTTPException(status_code=404, detail="未找到该模块 Skill")
    ver = db.query(SkillVersion).filter(SkillVersion.id == vid, SkillVersion.skill_id == skill.id).first()
    if not ver:
        raise HTTPException(status_code=404, detail="未找到该版本")
    # 旧版本置为非 active
    db.query(SkillVersion).filter(
        SkillVersion.skill_id == skill.id, SkillVersion.status == "active"
    ).update({"status": "archived"})
    ver.status = "active"
    skill.active_version_id = ver.id
    db.commit()
    invalidate_skill(module_key)  # 单进程内即时生效
    return {"status": "success", "data": _serialize_version(ver)}


# ----------------------------- 案例库 -----------------------------
@router.get("/{module_key}/cases")
async def list_cases(
    module_key: str,
    request: Request,
    is_mismatch: Optional[bool] = None,
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
):
    """案例列表（可按是否误判筛选）"""
    require_user(request)
    skill = db.query(Skill).filter(Skill.module_key == module_key).first()
    if not skill:
        raise HTTPException(status_code=404, detail="未找到该模块 Skill")
    q = db.query(SkillCase).filter(SkillCase.skill_id == skill.id)
    if is_mismatch is not None:
        q = q.filter(SkillCase.is_mismatch == is_mismatch)
    total = q.count()
    records = q.order_by(desc(SkillCase.created_at)).offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "data": [
            {
                "id": c.id,
                "requirement_id": c.requirement_id,
                "requirement_title": c.requirement_title,
                "requirement_desc": (c.requirement_desc or "")[:500],
                "ai_result_json": c.ai_result_json,
                "human_result_json": c.human_result_json,
                "is_mismatch": c.is_mismatch,
                "mismatch_reason": c.mismatch_reason,
                "source": c.source,
                "created_by": c.created_by,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in records
        ],
    }


@router.post("/{module_key}/cases")
async def add_case(module_key: str, body: AddCaseRequest, request: Request, db: Session = Depends(get_db)):
    """新增案例（模块页"加入案例库"按钮调用）"""
    require_user(request)
    skill = db.query(Skill).filter(Skill.module_key == module_key).first()
    if not skill:
        raise HTTPException(status_code=404, detail="未找到该模块 Skill")
    case = SkillCase(
        skill_id=skill.id,
        requirement_id=body.requirement_id,
        requirement_title=body.requirement_title,
        requirement_desc=body.requirement_desc,
        ai_result_json=body.ai_result_json,
        human_result_json=body.human_result_json,
        is_mismatch=body.is_mismatch,
        mismatch_reason=body.mismatch_reason,
        source=body.source,
        created_by=request.headers.get("x-user", "user"),
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return {"status": "success", "data": {"id": case.id}}


@router.delete("/{module_key}/cases/{cid}")
async def delete_case(module_key: str, cid: int, request: Request, db: Session = Depends(get_db)):
    """删除案例"""
    require_user(request)
    skill = db.query(Skill).filter(Skill.module_key == module_key).first()
    if not skill:
        raise HTTPException(status_code=404, detail="未找到该模块 Skill")
    case = db.query(SkillCase).filter(SkillCase.id == cid, SkillCase.skill_id == skill.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="未找到该案例")
    db.delete(case)
    db.commit()
    return {"status": "success"}


# ----------------------------- 优化 / 评测 -----------------------------
@router.post("/{module_key}/optimize")
async def optimize_skill(module_key: str, body: OptimizeRequest, request: Request, db: Session = Depends(get_db)):
    """基于误判案例运行优化器，产出一份 draft 版本"""
    user = require_admin(request)
    activate_user_business_settings(db, user.id)
    try:
        result = await run_optimization(module_key, db=db, created_by="optimizer", max_cases=body.max_cases)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"optimize {module_key} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"优化失败: {e}")
    return {"status": "success", "data": result}


@router.post("/{module_key}/evaluate")
async def evaluate_skill(module_key: str, body: EvaluateRequest, request: Request, db: Session = Depends(get_db)):
    """评测生效版本 vs 草稿版本，返回准确率对比"""
    user = require_admin(request)
    activate_user_business_settings(db, user.id)
    try:
        result = await run_evaluation(module_key, draft_version_id=body.draft_version_id, db=db)
    except Exception as e:
        logger.error(f"evaluate {module_key} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"评测失败: {e}")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"status": "success", "data": result}


# ----------------------------- 回滚（Phase 4） -----------------------------
@router.post("/{module_key}/rollback")
async def rollback_version(module_key: str, request: Request, db: Session = Depends(get_db)):
    """回滚到当前生效版本的父版本（旧生效版本置 archived）。

    用于「采纳草稿后发现不如预期」时一键撤销，回到上一生效版本。绝不自动跳过人工确认。
    """
    require_admin(request)
    skill = db.query(Skill).filter(Skill.module_key == module_key).first()
    if not skill or not skill.active_version_id:
        raise HTTPException(status_code=404, detail="未找到该模块 Skill 或生效版本")
    active_ver = db.query(SkillVersion).filter(SkillVersion.id == skill.active_version_id).first()
    if not active_ver or not active_ver.parent_version_id:
        raise HTTPException(status_code=400, detail="当前生效版本没有可回滚的父版本（它可能就是首个版本）")
    parent = db.query(SkillVersion).filter(SkillVersion.id == active_ver.parent_version_id).first()
    if not parent:
        raise HTTPException(status_code=400, detail="未找到父版本")
    # 当前生效版本置归档，父版本重新生效
    db.query(SkillVersion).filter(
        SkillVersion.skill_id == skill.id, SkillVersion.status == "active"
    ).update({"status": "archived"})
    parent.status = "active"
    skill.active_version_id = parent.id
    db.commit()
    invalidate_skill(module_key)
    return {"status": "success", "data": _serialize_version(parent)}


# ----------------------------- A/B 实跑对比（Phase 4） -----------------------------
@router.post("/{module_key}/ab-compare")
async def ab_compare(module_key: str, body: ABCompareRequest, request: Request, db: Session = Depends(get_db)):
    """A/B 影子对比：在近期线上数据上对比 生效版本 vs 候选版本 的决策变化率（只读，不写回）。"""
    user = require_admin(request)
    # 激活当前账号业务配置：使重跑与生产任务使用相同的模型/松紧度/阈值口径
    activate_user_business_settings(db, user.id)
    try:
        result = await run_ab_compare(module_key, body.candidate_version_id, body.sample_size, db=db)
    except Exception as e:
        logger.error(f"ab-compare {module_key} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"A/B 对比失败: {e}")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"status": "success", "data": result}


# ----------------------------- 复盘（Phase 4：定期复盘 / 查看历史） -----------------------------
@router.post("/review/run")
async def run_review(body: ReviewRunRequest, request: Request, db: Session = Depends(get_db)):
    """管理员手动触发复盘：对指定模块或全部 4 个模块运行定期复盘流程（产出草稿 + 写复盘日志，不自动激活）。"""
    require_admin(request)
    keys = [body.module_key] if body.module_key else list(MODULE_KEYS)
    results = []
    for k in keys:
        try:
            r = await run_periodic_review(k, db=db, created_by="manual")
            results.append(r)
        except Exception as e:
            results.append({"module_key": k, "status": "error", "reason": str(e)[:200]})
    return {"status": "success", "data": results}


@router.get("/review/logs")
async def list_review_logs(
    module_key: Optional[str] = None,
    limit: int = 50,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """查看复盘历史（含准确率趋势），供「复盘记录」页展示。"""
    require_user(request)
    q = db.query(SkillReviewLog)
    if module_key:
        q = q.filter(SkillReviewLog.module_key == module_key)
    logs = q.order_by(SkillReviewLog.run_at.desc()).limit(limit).all()
    draft_ids = {l.draft_version_id for l in logs if l.draft_version_id}
    ver_no_map = {}
    if draft_ids:
        vers = db.query(SkillVersion.id, SkillVersion.version_no).filter(SkillVersion.id.in_(draft_ids)).all()
        ver_no_map = {v.id: v.version_no for v in vers}
    return {
        "data": [
            {
                "id": l.id,
                "module_key": l.module_key,
                "run_at": l.run_at.isoformat() if l.run_at else None,
                "new_case_count": l.new_case_count,
                "total_cases": l.total_cases,
                "draft_version_id": l.draft_version_id,
                "draft_version_no": ver_no_map.get(l.draft_version_id) if l.draft_version_id else None,
                "active_accuracy": l.active_accuracy,
                "draft_accuracy": l.draft_accuracy,
                "delta": l.delta,
                "recommendation": l.recommendation,
                "note": l.note,
                "created_by": l.created_by,
            }
            for l in logs
        ]
    }
