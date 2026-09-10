"""API 路由：PRD 分析

对应 agents.md 6.2 节
"""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, PrdAnalysisJob, UserRequirementJob, BackgroundJob, ProcessLog
from app.auth import get_current_user, User
from app.config import settings
from app.user_settings import get_active_setting
from app.tapd_client import tapd_client, TAPDClientError
from app.jobs import (
    create_background_job, update_background_job, append_process_log, run_async_task,
)
from app.prd_analyzer import analyze_prd_for_record
from app.audit import log_audit


router = APIRouter(prefix="/api/prd", tags=["prd"])


def _parse_tapd_datetime(dt_str: str) -> Optional[datetime]:
    """解析 TAPD 返回的时间字符串（如 '2024-01-01 12:00:00'）"""
    if not dt_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None


def _tapd_story_url(workspace_id: str, story_id: str) -> str:
    """生成 TAPD 需求详情页 URL"""
    return f"https://www.tapd.cn/{workspace_id}/prong/stories/view/{story_id}"


# ---------- 数据模型 ----------
class AnalyzeRequest(BaseModel):
    record_ids: list[int]


class FetchPrdRequest(BaseModel):
    workspace_id: Optional[str] = None
    status: Optional[str] = None  # 不传则默认用「待评审」状态
    limit: int = 200
    owner: Optional[str] = None  # 处理人过滤，操作员只能传自己的


# ---------- POST /fetch：从 TAPD 拉取含 PRD 的需求 ----------
@router.post("/fetch")
async def fetch_prds(
    req: FetchPrdRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """从 TAPD 拉取含 PRD（需求方案）的需求

    默认只拉取「待评审」状态的需求（由 STORY_STATUS_PRD_REVIEW 配置），
    也可通过 status 参数指定其他状态。
    权限：管理员可拉取全量 PRD（不传 owner）；操作员必须传 owner 且只能拉取自己名下的。
    """
    # 操作员默认使用自己的处理人范围；管理员不传 owner 时拉取全量。
    user_display = user.display_name or user.username
    if user.role != "admin":
        if not req.owner:
            req.owner = user_display
        elif req.owner != user_display:
            raise HTTPException(status_code=403, detail="操作员仅能拉取自己名下的 PRD")

    from app.user_settings import get_active_setting
    ws_id = req.workspace_id or get_active_setting("tapd_workspace_ids").split(",")[0].strip()
    # 默认使用「待评审」状态
    fetch_status = req.status or get_active_setting("story_status_prd_review")

    # TAPD 的 owner 参数使用账号名；本地记录和权限判断仍使用显示名。
    tapd_owner = req.owner
    if tapd_owner:
        from app.owner_mapping_cls import get_tapd_account_by_display_name
        tapd_owner = get_tapd_account_by_display_name(tapd_owner)

    try:
        stories = await tapd_client.get_stories(
            workspace_id=ws_id,
            limit=req.limit,
            status=fetch_status,
            owner=tapd_owner or None,
        )
    except TAPDClientError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TAPD 调用失败: {e}")

    new_count = 0
    update_count = 0
    skip_count = 0
    pending_prd_count = 0
    for item in stories:
        s = tapd_client.extract_fields(item)
        story_id = s.get("story_id")
        prd_content = s.get("prd_content")
        if not story_id:
            skip_count += 1
            continue

        # PRD 为空的需求也拉取进来，标记为"待补充PRD"
        record_status = "待补充PRD" if not prd_content else "pending"
        if not prd_content:
            pending_prd_count += 1

        # 原始需求回退链：优先本次 TAPD 自定义字段，再复用用户需求模块已提取记录；
        # 两者都为空时明确保留空值，由分析器限制覆盖度并生成待补充建议。
        original_req = s.get("user_requirement") or s.get("description", "")
        if not (original_req or "").strip():
            existing_requirement = db.query(UserRequirementJob).filter(
                UserRequirementJob.story_id == story_id,
                UserRequirementJob.workspace_id == ws_id,
            ).first()
            if existing_requirement:
                original_req = existing_requirement.description or ""
        tapd_created = _parse_tapd_datetime(s.get("created", ""))
        tapd_updated = _parse_tapd_datetime(s.get("modified", ""))

        # extract_fields 返回 owner 为 list，存库时转为分号分隔字符串
        owner_raw = s.get("owner", "")
        owner_str = ";".join(owner_raw) if isinstance(owner_raw, list) else (owner_raw or "")
        creator_raw = s.get("creator", "")
        creator_str = ";".join(creator_raw) if isinstance(creator_raw, list) else (creator_raw or "")

        existing = db.query(PrdAnalysisJob).filter(
            PrdAnalysisJob.story_id == story_id,
            PrdAnalysisJob.workspace_id == ws_id,
        ).first()

        if existing:
            existing.prd_content = prd_content
            existing.original_requirement = original_req
            existing.image_paths = json.dumps(s.get("image_urls", []), ensure_ascii=False)
            existing.title = s.get("title", "")
            existing.owner = owner_str
            existing.creator = creator_str
            existing.tenant_version = s.get("tenant_version", "")
            existing.priority = s.get("priority_custom", "") or s.get("priority_tapd", "")
            existing.tapd_status = s.get("status", "")
            existing.tapd_created = tapd_created
            existing.tapd_updated = tapd_updated
            # 仅在未分析状态（pending/待补充PRD）时同步状态，避免覆盖已分析结果
            if existing.status in ("pending", "待补充PRD"):
                existing.status = record_status
            existing.updated_at = datetime.now()
            update_count += 1
        else:
            db.add(PrdAnalysisJob(
                story_id=story_id,
                workspace_id=ws_id,
                title=s.get("title", ""),
                owner=owner_str,
                creator=creator_str,
                tenant_version=s.get("tenant_version", ""),
                priority=s.get("priority_custom", "") or s.get("priority_tapd", ""),
                tapd_status=s.get("status", ""),
                tapd_created=tapd_created,
                tapd_updated=tapd_updated,
                prd_content=prd_content,
                original_requirement=original_req,
                image_paths=json.dumps(s.get("image_urls", []), ensure_ascii=False),
                status=record_status,
                created_by=user.username,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ))
            new_count += 1

    db.commit()

    log_audit(db, "fetch_prds", user.username, target=ws_id,
              detail=f"状态={fetch_status}，owner={req.owner or '全部'}，新增 {new_count} 条，更新 {update_count} 条，跳过 {skip_count} 条，待补充PRD {pending_prd_count} 条")

    return {
        "total": len(stories),
        "new": new_count,
        "updated": update_count,
        "skipped": skip_count,
        "pending_prd": pending_prd_count,
        "status_filter": fetch_status,
        "owner": req.owner,
    }


# ---------- GET /list：本地 PRD 列表 ----------
@router.get("/list")
async def list_prds(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    status: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    owner: Optional[str] = Query(None, description="处理人筛选"),
    order_by: Optional[str] = Query(None, description="排序字段：score / tapd_created / tapd_updated / created"),
    order: Optional[str] = Query("desc", description="排序方向：asc / desc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取本地 PRD 列表"""
    q = db.query(PrdAnalysisJob)
    # 操作员只能查看自己名下的 PRD（按 owner 字段过滤）
    if user.role != "admin":
        user_display = user.display_name or user.username
        q = q.filter(PrdAnalysisJob.owner.like(f"%{user_display}%"))
    if status:
        q = q.filter(PrdAnalysisJob.status == status)
    if keyword:
        q = q.filter(PrdAnalysisJob.story_id.like(f"%{keyword}%"))
    if owner:
        q = q.filter(PrdAnalysisJob.owner.like(f"%{owner}%"))

    total = q.count()

    # 排序
    order_col_map = {
        "score": PrdAnalysisJob.completeness_score,
        "tapd_created": PrdAnalysisJob.tapd_created,
        "tapd_updated": PrdAnalysisJob.tapd_updated,
        "created": PrdAnalysisJob.created_at,
    }
    order_col = order_col_map.get(order_by, PrdAnalysisJob.tapd_created)
    if order == "asc":
        records = q.order_by(order_col.asc().nullslast(), PrdAnalysisJob.created_at.desc()) \
            .offset((page - 1) * page_size) \
            .limit(page_size) \
            .all()
    else:
        records = q.order_by(order_col.desc().nullslast(), PrdAnalysisJob.created_at.desc()) \
            .offset((page - 1) * page_size) \
            .limit(page_size) \
            .all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_prd(r) for r in records],
    }


# ---------- GET /owners：获取所有处理人列表 ----------
@router.get("/owners")
async def list_owners(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取所有有 PRD 记录的处理人列表（用于筛选下拉）"""
    q = db.query(PrdAnalysisJob.owner).filter(
        PrdAnalysisJob.owner.isnot(None),
        PrdAnalysisJob.owner != "",
    ).distinct()
    # 操作员不需要额外过滤，owner 字段本身就是处理人标识
    owners = [r[0] for r in q.all()]
    return {"owners": sorted(owners)}


# ---------- POST /record/{record_id}/manual-score：人工打分（1-10 分） ----------
class ManualScoreRequest(BaseModel):
    score: float
    comment: str = ""


@router.post("/record/{record_id}/manual-score")
async def manual_score(
    record_id: int,
    req: ManualScoreRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """人工复核打分：1-10 分（0.5 步进）。

    AI 完整度评分保持 0-100 内部体系不变；人工用 1-10 粗粒度修正，
    存储原值（与 AI 分对比时 ×10），并记录打分人与备注，供校准分析与案例库沉淀。
    """
    if req.score < 1 or req.score > 10:
        raise HTTPException(status_code=400, detail="人工打分须在 1-10 分之间")
    score = round(req.score * 2) / 2  # 对齐 0.5 步进

    record = db.query(PrdAnalysisJob).filter(PrdAnalysisJob.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="PRD 记录不存在")

    record.manual_score = score
    record.manual_score_comment = (req.comment or "").strip()[:500]
    record.manual_score_by = user.display_name or user.username
    record.manual_score_at = datetime.now()
    db.commit()

    log_audit(db, "prd_manual_score", user.username, target=record.story_id,
              detail=f"PRD 人工打分 {score}/10（AI {record.completeness_score}）")
    return {"status": "success", "data": {
        "record_id": record_id,
        "manual_score": score,
        "ai_score": record.completeness_score,
        "manual_score_by": record.manual_score_by,
        "manual_score_at": record.manual_score_at.isoformat() if record.manual_score_at else None,
    }}


# ---------- POST /analyze：启动 PRD 分析 ----------
@router.post("/analyze")
async def start_analyze(
    req: AnalyzeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """启动 PRD 有效性打分任务"""
    if not req.record_ids:
        raise HTTPException(status_code=400, detail="请选择至少一条 PRD")

    bg_job = create_background_job(
        db, job_type="prd_analysis",
        total=len(req.record_ids), created_by=user.username,
        payload={"record_ids": req.record_ids, "user_id": user.id},
    )
    _run_prd_records(bg_job.job_id, req.record_ids, user.id)

    log_audit(db, "manual_trigger_prd", user.username,
              target=bg_job.job_id, detail=f"{len(req.record_ids)} 条 PRD")

    return {"job_id": bg_job.job_id, "total": len(req.record_ids)}


def _run_prd_records(job_id: str, record_ids: list[int], user_id: int | None = None) -> None:
    """PRD 分析后台执行体（手动分析 / 中断恢复共用）"""
    from app.database import get_session_local
    from app.prd_analyzer import analyze_prd_for_record

    async def _run():
        SessionLocal = get_session_local()
        task_db = SessionLocal()
        try:
            if user_id is not None:
                from app.user_settings import activate_user_business_settings
                activate_user_business_settings(task_db, user_id)
            # 阶段0：截图识别增强（视觉模型未配置时整段跳过）
            from app.vision_client import vision_configured, enrich_prd_record
            if vision_configured():
                append_process_log(task_db, job_id, "prd_analysis",
                                   f"开始截图识别增强（共 {len(record_ids)} 条，每条最多 3 张）")
                for rid in list(record_ids):
                    rec = task_db.query(PrdAnalysisJob).filter(PrdAnalysisJob.id == rid).first()
                    if not rec:
                        continue
                    try:
                        changed = await enrich_prd_record(task_db, rec)
                        if changed:
                            append_process_log(task_db, job_id, "prd_analysis",
                                               f"PRD {rec.story_id} 截图识别完成，已并入需求文字",
                                               story_id=rec.story_id, level="info")
                    except Exception as e:
                        append_process_log(task_db, job_id, "prd_analysis",
                                           f"记录 ID={rid} 截图增强失败：{e}", level="warning")
            else:
                append_process_log(task_db, job_id, "prd_analysis",
                                   "视觉模型未配置（VISION_API_KEY），跳过截图识别增强", level="info")
            success_count = 0
            fail_count = 0
            for idx, rid in enumerate(record_ids, 1):
                bg = task_db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
                if bg and bg.status == "interrupted":
                    break
                try:
                    await analyze_prd_for_record(task_db, job_id, rid)
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    append_process_log(task_db, job_id, "prd_analysis",
                                       f"记录 ID={rid} 分析失败：{e}", level="error")
                update_background_job(task_db, job_id, processed=idx,
                                      succeeded=success_count, failed=fail_count)
            update_background_job(task_db, job_id, status="completed",
                                  result=json.dumps({"succeeded": success_count, "failed": fail_count}))
        finally:
            task_db.close()

    run_async_task(job_id, _run())


# ---------- GET /{story_id}/compare：对比用户需求与 PRD ----------
@router.get("/{story_id}/compare")
async def compare_prd(
    story_id: str,
    workspace_id: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对比用户需求与 PRD"""
    ws_id = workspace_id or get_active_setting("tapd_workspace_ids").split(",")[0].strip()
    record = db.query(PrdAnalysisJob).filter(
        PrdAnalysisJob.story_id == story_id,
        PrdAnalysisJob.workspace_id == ws_id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="PRD 记录不存在")
    return _serialize_prd(record)


# ---------- GET /jobs/{job_id}/result：任务结果 ----------
@router.get("/jobs/{job_id}/result")
async def get_job_result(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取 PRD 分析任务结果"""
    job = db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "status": job.status,
        "total": job.total,
        "processed": job.processed,
        "succeeded": job.succeeded,
        "failed": job.failed,
        "result": json.loads(job.result) if job.result else None,
        "error_message": job.error_message,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


# ---------- 内部工具 ----------
def _serialize_prd(r: PrdAnalysisJob) -> dict:
    return {
        "id": r.id,
        "story_id": r.story_id,
        "workspace_id": r.workspace_id,
        "title": r.title or "",
        "owner": r.owner or "",
        "creator": r.creator or "",
        "tenant_version": r.tenant_version or "",
        "priority": r.priority or "",
        "tapd_status": r.tapd_status or "",
        "tapd_created": r.tapd_created.strftime("%Y-%m-%d %H:%M:%S") if r.tapd_created else None,
        "tapd_updated": r.tapd_updated.strftime("%Y-%m-%d %H:%M:%S") if r.tapd_updated else None,
        "tapd_url": _tapd_story_url(r.workspace_id, r.story_id) if r.workspace_id and r.story_id else "",
        "prd_content": r.prd_content,
        "original_requirement": r.original_requirement,
        "completeness_score": r.completeness_score,
        "manual_score": r.manual_score,
        "manual_score_comment": r.manual_score_comment,
        "manual_score_by": r.manual_score_by,
        "manual_score_at": r.manual_score_at.isoformat() if r.manual_score_at else None,
        "coverage_detail": json.loads(r.coverage_detail) if r.coverage_detail else None,
        "suggestions": json.loads(r.suggestions) if r.suggestions else None,
        "status": r.status,
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
