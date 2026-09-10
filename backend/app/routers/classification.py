"""API 路由：需求分类机器人

从 tapd-classification-bot 迁移而来，提供分类处理、统计看板、
处理人写回、人工修正、运行日志等功能。

所有接口均需要登录（operator 及以上），管理类接口需要 admin。
"""
import json
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.config import settings
from app.user_settings import get_active_setting
from app.database import (
    get_db, get_session_local, get_status, set_status,
    Classification, RunLog, BotStatus, OwnerModification,
    BackgroundJob, WritebackLog,
)
from app.auth import (
    require_user, require_admin, get_current_user,
    public_user_info, ROLE_ADMIN, ROLE_OPERATOR,
    is_account_locked, register_failed_login, register_success_login,
)
from app.audit import log_operation
from app.tapd_client import tapd_client, TAPDClientError
from app.owner_mapping_cls import get_all_owner_names, get_all_l1_categories
from app.jobs import create_background_job, update_background_job, run_async_task
from app.classifier import process_batch


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/classification", tags=["classification"])


# ==================== 机器人状态 ====================

@router.get("/status")
async def get_bot_status(request: Request):
    """获取分类机器人状态"""
    require_user(request)
    tapd_ok = False
    try:
        tapd_ok = await tapd_client.check_connection()
    except Exception:
        tapd_ok = False
    return {
        "bot_name": settings.bot_name,
        "bot_state": get_status("bot_state", "idle"),
        "scheduler_active": get_status("classification_scheduler_active", "false"),
        "schedule_interval": get_status("schedule_interval", f"{settings.schedule_interval_minutes}分钟"),
        "last_run_start": get_status("last_run_start", ""),
        "last_run_end": get_status("last_run_end", ""),
        "last_run_duration": get_status("last_run_duration", ""),
        "last_run_summary": get_status("last_run_summary", "尚未运行"),
        "last_error": get_status("last_error", ""),
        "tapd_connected": tapd_ok,
        "auto_assign_owner": settings.auto_assign_owner,
        "auto_write_comment": settings.auto_write_comment,
        "owner_update_comment": settings.owner_update_comment,
    }


@router.post("/run")
async def manual_run(request: Request):
    """手动触发一次批量分类处理"""
    user = require_user(request)
    state = get_status("bot_state", "idle")
    if state == "running":
        raise HTTPException(status_code=409, detail="机器人正在运行中，请等待完成")

    # 使用当前账号的 DeepSeek 配置校验，而非共享系统配置。
    SessionLocal = get_session_local()
    config_db = SessionLocal()
    try:
        from app.user_settings import get_user_business_settings
        personal = get_user_business_settings(config_db, user.id)
    finally:
        config_db.close()
    api_key = personal.get("deepseek_api_key") or ""
    if not api_key or api_key.startswith("sk-placeholder") or api_key.startswith("请填入"):
        error_msg = "当前账号未配置有效的 DeepSeek API Key，无法触发处理。"
        set_status("bot_state", "error")
        set_status("last_error", error_msg)
        raise HTTPException(status_code=400, detail=error_msg)

    # 创建后台任务
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        job = create_background_job(db, "classification", total=0, created_by=user.username)
        job_id = job.job_id
    finally:
        db.close()

    # 操作员只处理自己名下的需求，管理员处理全量
    owner_filter = None
    if user.role != ROLE_ADMIN:
        display_name = user.display_name or user.username
        # TAPD API 的 owner 参数需要账号名（如 "徐玥玥01"），而非显示名（如 "徐玥玥"）
        from app.owner_mapping_cls import get_tapd_account_by_display_name
        owner_filter = get_tapd_account_by_display_name(display_name)

    # 在后台线程中运行
    import asyncio
    coro = process_batch(job_id=job_id, created_by=user.username, owner=owner_filter, user_id=user.id)
    run_async_task(job_id, coro)

    log_operation(actor=user.username, action="classification.run", target=job_id, request=request)
    return {"status": "success", "job_id": job_id, "message": "已启动分类处理"}


@router.post("/stop")
async def stop_execution(request: Request):
    """停止当前执行"""
    user = require_user(request)
    set_status("bot_state", "idle")

    # 标记运行中的分类任务为 interrupted
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        running = db.query(BackgroundJob).filter(
            BackgroundJob.job_type == "classification",
            BackgroundJob.status == "running",
        ).all()
        for job in running:
            update_background_job(db, job.job_id, status="interrupted", error_message="用户手动停止")
    finally:
        db.close()

    log_operation(actor=user.username, action="classification.stop", request=request)
    return {"status": "success", "message": "已请求停止执行"}


@router.post("/scheduler/start")
async def api_start_scheduler(request: Request):
    """启动分类定时任务（仅控制分类机器人，不影响用户需求处理定时）"""
    require_admin(request)
    from app.scheduler import start_scheduler, _scheduler
    start_scheduler()
    interval = settings.schedule_interval_minutes
    if _scheduler is not None:
        try:
            _scheduler.add_job(
                _scheduled_classification_wrapper,
                "interval",
                minutes=interval,
                id="classification_batch",
                replace_existing=True,
            )
        except Exception:
            pass
    set_status("classification_scheduler_active", "true")
    log_operation(actor=require_user(request).username, action="classification.scheduler.start", request=request)
    return {"status": "success", "message": f"分类定时任务已开启，每{interval}分钟执行一次"}


@router.post("/scheduler/stop")
async def api_stop_scheduler(request: Request):
    """停止分类定时任务（仅控制分类机器人，不影响用户需求处理定时）"""
    require_admin(request)
    from app.scheduler import _scheduler
    if _scheduler is not None:
        try:
            _scheduler.remove_job("classification_batch")
        except Exception:
            pass
    set_status("classification_scheduler_active", "false")
    log_operation(actor=require_user(request).username, action="classification.scheduler.stop", request=request)
    return {"status": "success", "message": "分类定时任务已停止"}


def _scheduled_classification_wrapper():
    """分类定时任务包装器（供 scheduler 调用）"""
    from app.scheduler import _scheduled_classification
    _scheduled_classification()


# ==================== 功能开关 ====================

@router.post("/owner/enable")
async def enable_owner_assignment(request: Request):
    """开启自动分配处理人"""
    require_admin(request)
    settings.update_env({"AUTO_ASSIGN_OWNER": "true"})
    log_operation(actor=require_user(request).username, action="classification.owner_assign.enable", request=request)
    return {"status": "success", "message": "自动分配处理人功能已开启"}


@router.post("/owner/disable")
async def disable_owner_assignment(request: Request):
    """关闭自动分配处理人"""
    require_admin(request)
    settings.update_env({"AUTO_ASSIGN_OWNER": "false"})
    log_operation(actor=require_user(request).username, action="classification.owner_assign.disable", request=request)
    return {"status": "success", "message": "自动分配处理人功能已关闭"}


@router.post("/comment/enable")
async def enable_comment_writeback(request: Request):
    """开启自动写回评论"""
    require_admin(request)
    settings.update_env({"AUTO_WRITE_COMMENT": "true"})
    log_operation(actor=require_user(request).username, action="classification.comment.enable", request=request)
    return {"status": "success", "message": "自动写回评论功能已开启"}


@router.post("/comment/disable")
async def disable_comment_writeback(request: Request):
    """关闭自动写回评论"""
    require_admin(request)
    settings.update_env({"AUTO_WRITE_COMMENT": "false"})
    log_operation(actor=require_user(request).username, action="classification.comment.disable", request=request)
    return {"status": "success", "message": "自动写回评论功能已关闭"}


# ==================== 分类结果列表 ====================

@router.get("/stories")
async def list_stories(
    request: Request,
    page: int = 1,
    size: int = 20,
    category_l1: str = None,
    confidence: str = None,
    owner: str = None,
    order_by: str = "tapd_created",
    order: str = "desc",
    db: Session = Depends(get_db),
):
    """获取分类结果列表"""
    user = require_user(request)
    query = db.query(Classification)
    # 非 admin 只看自己名下的分类结果（按 original_owner 过滤，而非 created_by）
    # 这样管理员批量分类后，操作员也能看到自己名下需求的分类结果
    if user.role != "admin":
        user_display = user.display_name or user.username
        query = query.filter(Classification.original_owner.like(f"%{user_display}%"))
    if category_l1:
        query = query.filter(Classification.category_l1 == category_l1)
    if confidence:
        query = query.filter(Classification.confidence == confidence)
    if owner:
        query = query.filter(Classification.assigned_owner == owner)

    total = query.count()
    # 排序：默认按 TAPD 提交时间倒序，支持前端按提交时间/更新时间切换
    order_col_map = {
        "tapd_created": Classification.tapd_created,
        "tapd_updated": Classification.tapd_updated,
    }
    order_col = order_col_map.get(order_by, Classification.tapd_created)
    if order == "asc":
        records = query.order_by(
            order_col.asc().nullslast(),
            Classification.processed_at.desc(),
        ).offset((page - 1) * size).limit(size).all()
    else:
        records = query.order_by(
            order_col.desc().nullslast(),
            Classification.processed_at.desc(),
        ).offset((page - 1) * size).limit(size).all()

    return {
        "total": total, "page": page, "size": size,
        "data": [
            {
                "id": r.id,
                "story_id": r.story_id,
                "story_title": r.story_title,
                "story_description": r.story_description or "",
                "category_l1": r.category_l1,
                "category_l2": r.category_l2,
                "confidence": r.confidence,
                "confidence_cn": {"high": "高", "medium": "中", "low": "低"}.get(r.confidence, r.confidence),
                "reason": r.reason,
                "original_module": r.original_module,
                "comment_id": r.comment_id,
                "comment_written": r.comment_written,
                "assigned_owner": r.assigned_owner,
                "owner_assigned": r.owner_assigned,
                "writeback_completed": r.writeback_completed,
                "writeback_completed_at": r.writeback_completed_at.isoformat() if r.writeback_completed_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "processed_at": r.processed_at.isoformat() if r.processed_at else None,
                "tapd_created": r.tapd_created.isoformat() if r.tapd_created else None,
                "tapd_updated": r.tapd_updated.isoformat() if r.tapd_updated else None,
                "workspace_id": r.workspace_id,
                "created_by": r.created_by,
                "tenant_version": r.tenant_version or "",
                "priority": r.priority or "",
                "original_owner": r.original_owner or "",
                "story_url": f"https://www.tapd.cn/{r.workspace_id}/prong/stories/view/{r.story_id}",
            }
            for r in records
        ],
    }


# ==================== 按处理人拉取需求 ====================

class FetchByOwnerRequest(BaseModel):
    owner: str
    limit: int = 50
    workspace_id: Optional[str] = None


@router.post("/fetch-by-owner")
async def fetch_by_owner(
    body: FetchByOwnerRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """按处理人从 TAPD 拉取需求并分类入库（SSE 流式返回进度）

    拉取指定处理人名下"需求待评估"状态的需求，对每条需求进行 LLM 分类，
    结果直接写入 classifications 表，可在分类结果列表中查看。
    使用 SSE 实时推送每条需求的处理进度。
    """
    user = require_user(request)
    if not body.owner:
        raise HTTPException(status_code=400, detail="请指定处理人")

    # 权限校验：操作员只能拉取自己的需求，管理员可以拉取任意处理人
    # owner 为处理人显示名（与 TAPD owner 字段一致），与当前用户 display_name 比较
    if user.role != ROLE_ADMIN and body.owner != (user.display_name or user.username):
        raise HTTPException(status_code=403, detail="操作员仅能拉取自己名下的需求")

    # 检查 DeepSeek API Key
    from app.classifier import _is_api_key_configured
    if not _is_api_key_configured():
        raise HTTPException(status_code=400, detail="DeepSeek API Key 未配置，无法分类")

    ws_id = body.workspace_id or settings.tapd_workspace_ids.split(",")[0].strip()
    fetch_status = settings.story_status_filter or "status_2"

    # TAPD API 的 owner 参数需要账号名（如 "徐玥玥01"），而非显示名（如 "徐玥玥"）
    from app.owner_mapping_cls import get_tapd_account_by_display_name
    tapd_owner = get_tapd_account_by_display_name(body.owner)

    # 提前拉取需求列表
    try:
        stories = await tapd_client.get_stories(
            workspace_id=ws_id,
            limit=body.limit,
            status=fetch_status,
            owner=tapd_owner,
        )
    except TAPDClientError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TAPD 调用失败: {e}")

    total_count = len(stories)

    async def stream_classify():
        from app.classifier import _classify_with_llm, _is_already_classified
        from app.owner_mapping_cls import resolve_owner

        # 发送开始事件
        yield f"data: {json.dumps({'type': 'start', 'total': total_count, 'owner': body.owner}, ensure_ascii=False)}\n\n"

        if total_count == 0:
            done_data = {
                "type": "done",
                "total": 0, "classified": 0, "skipped": 0, "errored": 0,
                "message": f"处理人 {body.owner} 名下暂无需求待评估状态的需求",
            }
            yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"
            return

        total_classified = 0
        total_skipped = 0
        total_errored = 0

        for idx, item in enumerate(stories):
            story = item.get("Story", {})
            story_id = story.get("id", "")
            title = story.get("name", "")
            description = story.get("description", "")
            module = story.get("module", "")

            if not story_id:
                continue

            # 已分类则跳过
            if _is_already_classified(db, story_id):
                total_skipped += 1
                progress_data = {
                    "type": "progress",
                    "index": idx + 1, "total": total_count,
                    "story_id": story_id, "title": title[:60],
                    "status": "skipped",
                    "classified": total_classified,
                    "skipped": total_skipped,
                    "errored": total_errored,
                }
                yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"
                continue

            # 提取业务字段
            extracted = tapd_client.extract_fields(item)
            tenant_version = extracted.get("tenant_version", "") or ""
            priority = extracted.get("priority_custom", "") or ""
            owner_list = extracted.get("owner", []) or []
            original_owner = ";".join(owner_list) if isinstance(owner_list, list) else str(owner_list)
            # TAPD 原始提交/更新时间，用于列表展示和排序
            tapd_created = None
            tapd_updated = None
            for field_name, field_value in (("created", extracted.get("created", "")), ("updated", extracted.get("modified", ""))):
                if not field_value:
                    continue
                try:
                    parsed_time = datetime.strptime(str(field_value), "%Y-%m-%d %H:%M:%S")
                    if field_name == "created":
                        tapd_created = parsed_time
                    else:
                        tapd_updated = parsed_time
                except (ValueError, TypeError):
                    pass

            try:
                result = await _classify_with_llm(title, description)
                category_l1 = result.get("category_l1", "对接")
                category_l2 = result.get("category_l2", "")
                confidence = result.get("confidence", "low")
                reason = result.get("reason", "")

                if category_l1 in ("其它", "其他"):
                    category_l1 = "对接"
                    reason = f"[已纠正其它] {reason}"

                owner_info = resolve_owner(category_l1, category_l2)
                assigned_owner = owner_info["display_name"] if owner_info else None

                record = Classification(
                    story_id=story_id,
                    story_title=title,
                    story_description=(description or "")[:2000],
                    category_l1=category_l1,
                    category_l2=category_l2,
                    confidence=confidence,
                    reason=reason,
                    original_module=module,
                    workspace_id=ws_id,
                    assigned_owner=assigned_owner,
                    owner_assigned=False,
                    comment_written=False,
                    created_by=user.username,
                    tenant_version=tenant_version,
                    priority=priority,
                    original_owner=original_owner,
                    tapd_created=tapd_created,
                    tapd_updated=tapd_updated,
                )
                db.add(record)
                db.commit()
                total_classified += 1
                story_status = "classified"
            except Exception as e:
                logger.error(f"Error classifying story {story_id}: {e}")
                total_errored += 1
                db.rollback()
                story_status = "error"

            progress_data = {
                "type": "progress",
                "index": idx + 1, "total": total_count,
                "story_id": story_id, "title": title[:60],
                "status": story_status,
                "classified": total_classified,
                "skipped": total_skipped,
                "errored": total_errored,
            }
            yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"

        log_operation(
            actor=user.username,
            action="classification.fetch_by_owner",
            target=body.owner,
            detail=f"拉取处理人={body.owner}，共{total_count}条，分类{total_classified}，跳过{total_skipped}，失败{total_errored}",
            request=request,
        )

        message = f"处理人 {body.owner}：共拉取 {total_count} 条，新分类 {total_classified} 条，已存在跳过 {total_skipped} 条"
        if total_errored:
            message += f"，失败 {total_errored} 条"

        done_data = {
            "type": "done",
            "total": total_count,
            "classified": total_classified,
            "skipped": total_skipped,
            "errored": total_errored,
            "message": message,
        }
        yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream_classify(), media_type="text/event-stream")


# ==================== 统计看板 ====================

@router.get("/stats")
async def get_stats(request: Request, db: Session = Depends(get_db)):
    """获取分类统计看板数据"""
    user = require_user(request)
    scope_q = db.query(Classification)
    if user.role != "admin":
        user_display = user.display_name or user.username
        scope_q = scope_q.filter(Classification.original_owner.like(f"%{user_display}%"))

    total = scope_q.count()
    written = scope_q.filter(Classification.comment_written == True).count()
    owners_assigned = scope_q.filter(Classification.owner_assigned == True).count()
    writebacked = scope_q.filter(Classification.writeback_completed == True).count()
    high_conf = scope_q.filter(Classification.confidence == "high").count()
    med_conf = scope_q.filter(Classification.confidence == "medium").count()
    low_conf = scope_q.filter(Classification.confidence == "low").count()

    l1_dist = scope_q.with_entities(
        Classification.category_l1,
        func.count(Classification.id).label("count")
    ).group_by(Classification.category_l1).all()

    l2_dist = scope_q.with_entities(
        Classification.category_l2,
        func.count(Classification.id).label("count")
    ).filter(Classification.category_l2 != "") \
        .group_by(Classification.category_l2) \
        .order_by(desc("count")) \
        .limit(15).all()

    # 处理人分布
    owner_dist = scope_q.with_entities(
        Classification.assigned_owner,
        func.count(Classification.id).label("count")
    ).filter(Classification.assigned_owner.isnot(None)) \
        .filter(Classification.assigned_owner != "") \
        .group_by(Classification.assigned_owner) \
        .order_by(desc("count")).all()

    return {
        "total_classified": total,
        "total_comments_written": written,
        "total_owners_assigned": owners_assigned,
        "total_writebacked": writebacked,
        "confidence_distribution": {
            "high": high_conf,
            "medium": med_conf,
            "low": low_conf,
        },
        "category_l1_distribution": [
            {"name": r[0], "count": r[1]} for r in l1_dist
        ],
        "category_l2_distribution": [
            {"name": r[0], "count": r[1]} for r in l2_dist
        ],
        "owner_distribution": [
            {"name": r[0], "count": r[1]} for r in owner_dist
        ],
    }


# ==================== 运行日志 ====================

@router.get("/runs")
async def list_runs(request: Request, page: int = 1, size: int = 20, db: Session = Depends(get_db)):
    """获取分类运行日志"""
    require_user(request)
    total = db.query(RunLog).count()
    records = db.query(RunLog).order_by(desc(RunLog.run_time)) \
        .offset((page - 1) * size).limit(size).all()
    return {
        "total": total, "page": page, "size": size,
        "data": [
            {
                "id": r.id,
                "run_time": r.run_time.isoformat() if r.run_time else None,
                "stories_fetched": r.stories_fetched,
                "stories_classified": r.stories_classified,
                "stories_skipped": r.stories_skipped,
                "stories_errored": r.stories_errored,
                "comments_written": r.comments_written,
                "owners_assigned": r.owners_assigned,
                "status": r.status,
                "error_message": r.error_message,
                "details": r.details,
            }
            for r in records
        ],
    }


# ==================== 分类体系与处理人 ====================

@router.get("/categories")
async def get_categories(request: Request):
    """获取分类树"""
    require_user(request)
    from app.classification_kb import CATEGORY_TREE, CATEGORY_DESCRIPTIONS
    tree = []
    for l1, l2_list in CATEGORY_TREE.items():
        desc = CATEGORY_DESCRIPTIONS.get(l1, {})
        l1_desc = desc.get("_self", "") if isinstance(desc, dict) else str(desc)
        tree.append({
            "l1": l1,
            "l1_desc": l1_desc,
            "l2_list": [
                {"name": l2, "desc": desc.get(l2, "") if isinstance(desc, dict) else ""}
                for l2 in l2_list
            ] if isinstance(desc, dict) else [],
        })
    return {"categories": tree}


@router.get("/owners")
async def get_all_owners(request: Request):
    """获取所有模块负责人列表"""
    require_user(request)
    return {"status": "success", "data": get_all_owner_names()}


# ==================== 批量写回处理人 ====================

class WritebackItem(BaseModel):
    story_id: str
    workspace_id: str
    owner: str
    before_owner: Optional[str] = None


class BatchWritebackRequest(BaseModel):
    items: list
    write_comment: bool = False
    confirm_token: Optional[str] = None


@router.post("/writeback/prepare")
async def prepare_writeback(request: Request, body: BatchWritebackRequest):
    """二次确认：返回一个短期 confirm_token"""
    user = require_user(request)
    if not body.items:
        raise HTTPException(status_code=400, detail="没有需要写回的项")
    token = secrets.token_urlsafe(24)
    log_operation(
        actor=user.username,
        action="classification.writeback.prepare",
        detail=f"待写回 {len(body.items)} 条",
        request=request,
    )
    key = f"writeback_confirm:{token}"
    set_status(key, json.dumps({
        "user": user.username,
        "story_ids": [str(i.get("story_id")) for i in body.items],
        "expires_at": (datetime.now() + timedelta(minutes=5)).isoformat(),
    }, ensure_ascii=False))
    return {"status": "success", "confirm_token": token, "expires_in": 300}


@router.post("/writeback")
async def batch_writeback(request: Request, body: BatchWritebackRequest, db: Session = Depends(get_db)):
    """批量写回处理人到 TAPD"""
    user = require_user(request)
    if not body.confirm_token:
        raise HTTPException(status_code=400, detail="缺少二次确认 token，请先调用 prepare")

    confirm_key = f"writeback_confirm:{body.confirm_token}"
    confirm_data = get_status(confirm_key, "")
    if not confirm_data:
        raise HTTPException(status_code=400, detail="二次确认 token 无效或已过期")
    try:
        confirm = json.loads(confirm_data)
    except Exception:
        raise HTTPException(status_code=400, detail="二次确认 token 解析失败")
    expires_at = datetime.fromisoformat(confirm["expires_at"])
    if expires_at < datetime.now():
        raise HTTPException(status_code=400, detail="二次确认 token 已过期，请重新发起")
    if confirm.get("user") != user.username:
        raise HTTPException(status_code=403, detail="二次确认 token 与当前用户不匹配")

    # 创建写回任务记录
    SessionLocal = get_session_local()
    job_db = SessionLocal()
    job = None
    try:
        job = create_background_job(job_db, "writeback", total=len(body.items), created_by=user.username)
        job_id = job.job_id
    finally:
        job_db.close()

    results = {"success": 0, "failed": 0, "skipped": 0, "errors": []}

    for item in body.items:
        story_id = str(item.get("story_id"))
        # 幂等：同一条需求只成功写回一次
        existing = db.query(Classification).filter(Classification.story_id == story_id).first()
        if existing and existing.writeback_completed:
            results["skipped"] += 1
            continue

        before_owner = (existing.assigned_owner if existing else None) or item.get("before_owner")
        try:
            await tapd_client.update_story_owner(
                workspace_id=item["workspace_id"],
                story_id=story_id,
                owner=item["owner"],
            )
            results["success"] += 1

            db.add(WritebackLog(
                job_id=job_id,
                story_id=story_id,
                workspace_id=item["workspace_id"],
                field="owner",
                before_value=before_owner or "",
                after_value=item["owner"],
                operator=user.username,
                result="success",
            ))

            if existing:
                existing.writeback_completed = True
                existing.writeback_completed_at = datetime.now()
                existing.assigned_owner = item["owner"]

            if body.write_comment:
                comment_text = f"🤖 AI处理 | 处理人已分配: {item['owner']}"
                try:
                    await tapd_client.add_comment(
                        workspace_id=item["workspace_id"],
                        entry_type="stories",
                        entry_id=story_id,
                        description=comment_text,
                    )
                except Exception as e:
                    logger.warning(f"Comment write failed for {story_id}: {e}")

            db.commit()

        except Exception as e:
            results["failed"] += 1
            err_msg = str(e) if e is not None else "未知错误"
            results["errors"].append(f"{story_id}: {err_msg[:80]}")
            db.add(WritebackLog(
                job_id=job_id, story_id=story_id, workspace_id=item["workspace_id"],
                field="owner", before_value=before_owner or "", after_value=item["owner"],
                operator=user.username, result="failed", error=err_msg[:200],
            ))
            db.commit()

    # 用掉 confirm_token
    SessionLocal = get_session_local()
    tdb = SessionLocal()
    try:
        row = tdb.query(BotStatus).filter(BotStatus.key == confirm_key).first()
        if row:
            tdb.delete(row)
            tdb.commit()
        update_background_job(tdb, job_id, status="completed",
                              result=json.dumps(results, ensure_ascii=False))
    finally:
        tdb.close()

    log_operation(actor=user.username, action="classification.writeback.execute", target=job_id,
                  detail=f"成功 {results['success']} 失败 {results['failed']} 跳过 {results['skipped']}",
                  request=request)
    return {
        "status": "success",
        "data": results,
        "job_id": job_id,
        "message": f"写回完成: 成功 {results['success']}, 失败 {results['failed']}, 跳过 {results['skipped']}",
    }


@router.get("/writeback/logs")
async def list_writeback_logs(request: Request, page: int = 1, size: int = 50, db: Session = Depends(get_db)):
    """获取写回日志"""
    user = require_user(request)
    base_q = db.query(WritebackLog).filter(WritebackLog.job_id.isnot(None))
    if user.role != "admin":
        base_q = base_q.filter(WritebackLog.operator == user.username)
    total = base_q.count()
    records = base_q.order_by(desc(WritebackLog.created_at)) \
        .offset((page - 1) * size).limit(size).all()
    return {
        "total": total, "page": page, "size": size,
        "data": [
            {
                "id": r.id,
                "job_id": r.job_id,
                "story_id": r.story_id,
                "workspace_id": r.workspace_id,
                "field": r.field,
                "before_value": r.before_value,
                "after_value": r.after_value,
                "operator": r.operator,
                "result": r.result,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }


# ==================== 人工修正处理人 ====================

class OwnerModificationItem(BaseModel):
    story_id: str
    story_title: str
    workspace_id: str
    original_predicted_owner: str
    modified_owner: str
    predicted_l1: str
    predicted_l2: str
    updated_at: Optional[str] = None


class BatchOwnerModificationRequest(BaseModel):
    items: list


@router.post("/owner-modifications")
async def record_owner_modifications(request: Request, body: BatchOwnerModificationRequest, db: Session = Depends(get_db)):
    """记录人工修正处理人"""
    user = require_user(request)
    saved = 0
    conflict = []
    for item in body.items:
        story_id = item.get("story_id")
        record = db.query(Classification).filter(Classification.story_id == story_id).first()
        if record:
            # 并发冲突检测
            client_updated = item.get("updated_at")
            if client_updated:
                try:
                    client_dt = datetime.fromisoformat(client_updated.replace("Z", ""))
                except Exception:
                    client_dt = None
                if client_dt and record.updated_at and record.updated_at > client_dt + timedelta(seconds=1):
                    conflict.append({
                        "story_id": story_id,
                        "message": "该需求已被其他人修改，请刷新后重试",
                        "server_updated_at": record.updated_at.isoformat(),
                    })
                    continue
            record.assigned_owner = item.get("modified_owner")
            record.updated_at = datetime.now()

        mod = OwnerModification(
            story_id=story_id,
            story_title=item.get("story_title", ""),
            workspace_id=item.get("workspace_id", ""),
            original_predicted_owner=item.get("original_predicted_owner", ""),
            modified_owner=item.get("modified_owner", ""),
            predicted_l1=item.get("predicted_l1", ""),
            predicted_l2=item.get("predicted_l2", ""),
            modified_by=user.username,
        )
        db.add(mod)
        saved += 1
    db.commit()
    log_operation(actor=user.username, action="classification.owner_modification",
                  detail=f"保存 {saved} 条修正" + (f"；冲突 {len(conflict)} 条" if conflict else ""),
                  request=request)
    return {"status": "success", "data": {"saved": saved, "conflicts": conflict}}


@router.get("/owner-modifications")
async def list_owner_modifications(request: Request, page: int = 1, size: int = 50, db: Session = Depends(get_db)):
    """获取人工修正记录"""
    user = require_user(request)
    base_q = db.query(OwnerModification)
    if user.role != "admin":
        base_q = base_q.filter(OwnerModification.modified_by == user.username)
    total = base_q.count()
    records = base_q.order_by(desc(OwnerModification.modified_at)) \
        .offset((page - 1) * size).limit(size).all()
    freq_stats = base_q.with_entities(
        OwnerModification.predicted_l1,
        func.count(OwnerModification.id).label("count"),
    ).group_by(OwnerModification.predicted_l1).order_by(desc("count")).all()

    return {
        "status": "success",
        "data": {
            "total": total,
            "page": page,
            "size": size,
            "records": [
                {
                    "id": r.id,
                    "story_id": r.story_id,
                    "story_title": r.story_title,
                    "workspace_id": r.workspace_id,
                    "original_predicted_owner": r.original_predicted_owner,
                    "modified_owner": r.modified_owner,
                    "predicted_l1": r.predicted_l1,
                    "predicted_l2": r.predicted_l2,
                    "modified_by": r.modified_by,
                    "modified_at": r.modified_at.isoformat() if r.modified_at else None,
                }
                for r in records
            ],
            "frequency_by_l1": [
                {"category": r[0], "count": r[1]} for r in freq_stats
            ],
        },
    }


# ==================== 任务进度查询 ====================

@router.get("/jobs")
async def list_jobs(request: Request, limit: int = 20):
    """获取分类相关后台任务列表"""
    user = require_user(request)
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        q = db.query(BackgroundJob).filter(
            BackgroundJob.job_type.in_(["classification", "writeback"])
        )
        if user.role != "admin":
            q = q.filter(BackgroundJob.created_by == user.username)
        records = q.order_by(desc(BackgroundJob.created_at)).limit(limit).all()
        return {
            "status": "success",
            "data": [
                {
                    "job_id": j.job_id,
                    "job_type": j.job_type,
                    "status": j.status,
                    "total": j.total,
                    "processed": j.processed,
                    "succeeded": j.succeeded,
                    "failed": j.failed,
                    "created_by": j.created_by,
                    "started_at": j.started_at.isoformat() if j.started_at else None,
                    "finished_at": j.finished_at.isoformat() if j.finished_at else None,
                    "error_message": j.error_message,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                }
                for j in records
            ],
        }
    finally:
        db.close()


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    """获取任务进度"""
    user = require_user(request)
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        job = db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if user.role != "admin" and job.created_by != user.username:
            raise HTTPException(status_code=403, detail="无权查看他人任务")
        return {
            "status": "success",
            "data": {
                "job_id": job.job_id,
                "job_type": job.job_type,
                "status": job.status,
                "total": job.total,
                "processed": job.processed,
                "succeeded": job.succeeded,
                "failed": job.failed,
                "created_by": job.created_by,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                "error_message": job.error_message,
                "result": job.result,
                "created_at": job.created_at.isoformat() if job.created_at else None,
            },
        }
    finally:
        db.close()
