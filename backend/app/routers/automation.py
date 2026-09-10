"""按用户自动流程：用户自主开启三个业务页面的定时任务。"""
import asyncio
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import log_audit
from app.auth import User, get_current_user
from app.config import settings
from app.database import (
    BackgroundJob,
    PrdAnalysisJob,
    UserAutomationSettings,
    get_db,
    get_session_local,
)
from app.jobs import create_background_job, run_async_task

router = APIRouter(prefix="/api/automation", tags=["automation"])

MODULE_FIELDS = {
    "requirements": "requirements_enabled",
    "classification": "classification_enabled",
    "prd": "prd_enabled",
}
MODULE_LABELS = {
    "requirements": "用户需求处理",
    "classification": "需求分类",
    "prd": "PRD 分析",
}


class AutoFlowRequest(BaseModel):
    enabled: bool


class AutomationSettingsUpdate(BaseModel):
    schedule_interval_minutes: int = Field(ge=5, le=1440)
    batch_size: int = Field(ge=1, le=200)
    max_processing_minutes: int = Field(ge=5, le=480)


def _get_or_create(db: Session, user_id: int) -> UserAutomationSettings:
    record = db.query(UserAutomationSettings).filter(UserAutomationSettings.user_id == user_id).first()
    if not record:
        record = UserAutomationSettings(user_id=user_id)
        db.add(record)
        db.commit()
        db.refresh(record)
    return record


def _serialize(record: UserAutomationSettings, db=None) -> dict:
    """序列化用户自动流程设置，可选附带当前任务状态。"""
    data = {
        "auto_flow_enabled": bool(record.auto_flow_enabled),
        "requirements_enabled": bool(record.requirements_enabled),
        "classification_enabled": bool(record.classification_enabled),
        "prd_enabled": bool(record.prd_enabled),
        "requirements_last_run_at": record.requirements_last_run_at.isoformat() if record.requirements_last_run_at else None,
        "classification_last_run_at": record.classification_last_run_at.isoformat() if record.classification_last_run_at else None,
        "prd_last_run_at": record.prd_last_run_at.isoformat() if record.prd_last_run_at else None,
        "schedule_interval_minutes": record.schedule_interval_minutes or 30,
        "batch_size": record.batch_size or 50,
        "max_processing_minutes": record.max_processing_minutes or 60,
        "current_job_id": record.current_job_id,
        "current_job_status": None,
        "current_job_result": None,
    }
    # 若有 db 且存在任务 ID，附带任务状态供前端轮询（已完成/失败的任务不暴露，避免重复触发进度面板）
    if db and record.current_job_id:
        import json as _json
        from app.database import BackgroundJob
        job = db.query(BackgroundJob).filter(BackgroundJob.job_id == record.current_job_id).first()
        if job and job.status in ("running", "pending"):
            data["current_job_status"] = job.status
            data["current_job_result"] = _json.loads(job.result) if job.result else None
        elif job and job.status in ("completed", "failed", "interrupted"):
            # 任务已结束，清空数据库中的 current_job_id，避免每次轮询都查
            data["current_job_id"] = None
            record.current_job_id = None
            db.commit()
    return data


@router.get("/status")
def get_automation_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回当前登录用户的自动流程开关及执行参数，附带当前任务状态。"""
    return _serialize(_get_or_create(db, user.id), db=db)


@router.post("/enable")
def enable_auto_flow(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """确认启用当前用户的自动流程总开关（各模块仍需单独开启）。"""
    record = _get_or_create(db, user.id)
    record.auto_flow_enabled = True
    db.commit()
    log_audit(db, "automation_enable", user.username, detail="启用个人自动流程总开关")
    return {"success": True, "message": "自动流程已启用，请在各业务页面开启需要自动执行的任务", **_serialize(record)}


@router.post("/disable")
def disable_auto_flow(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """关闭当前用户全部自动流程。"""
    record = _get_or_create(db, user.id)
    record.auto_flow_enabled = False
    record.requirements_enabled = False
    record.classification_enabled = False
    record.prd_enabled = False
    db.commit()
    log_audit(db, "automation_disable", user.username, detail="关闭个人全部自动流程")
    return {"success": True, "message": "自动流程已关闭", **_serialize(record)}


@router.post("/modules/{module}")
def toggle_module(
    module: Literal["requirements", "classification", "prd"],
    req: AutoFlowRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """启用或停止当前用户某个页面的自动任务。开启时立即触发一次执行，无需等待下一个调度周期。"""
    record = _get_or_create(db, user.id)
    if req.enabled and not record.auto_flow_enabled:
        raise HTTPException(status_code=400, detail="请先在系统管理中确认开启自动流程功能")
    setattr(record, MODULE_FIELDS[module], req.enabled)
    db.commit()
    action = "开启" if req.enabled else "停止"
    log_audit(db, "automation_module_toggle", user.username, target=module, detail=f"{action}{MODULE_LABELS[module]}自动任务")

    # 开启时立即在后台触发一次，避免等待第一个调度周期
    if req.enabled:
        batch_size = record.batch_size or 50
        max_minutes = record.max_processing_minutes or 60
        if module == "requirements":
            from app.jobs import run_async_task
            run_async_task(
                f"auto_immediate_{user.id}",
                _run_with_timeout(_run_requirements_for_user(user, batch_size), max_minutes, user.username, "requirements"),
            )
        elif module == "classification":
            from app.jobs import run_async_task
            run_async_task(
                f"auto_cls_immediate_{user.id}",
                _run_with_timeout(_run_classification_for_user(user, batch_size), max_minutes, user.username, "classification"),
            )
        elif module == "prd":
            from app.jobs import run_async_task
            run_async_task(
                f"auto_prd_immediate_{user.id}",
                _run_with_timeout(_run_prd_for_user(user, batch_size), max_minutes, user.username, "prd"),
            )

    return {
        "success": True,
        "message": f"{MODULE_LABELS[module]}自动任务已{action}{'，已立即开始执行第一次处理' if req.enabled else ''}",
        **_serialize(record, db=db),
    }


@router.post("/settings")
def update_automation_settings(
    req: AutomationSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """每个用户独立设置自己的调度间隔、批量大小和最大处理时长。"""
    record = _get_or_create(db, user.id)
    record.schedule_interval_minutes = req.schedule_interval_minutes
    record.batch_size = req.batch_size
    record.max_processing_minutes = req.max_processing_minutes
    db.commit()
    log_audit(
        db,
        "automation_settings_update",
        user.username,
        detail=f"调度间隔={req.schedule_interval_minutes}分钟，批量大小={req.batch_size}，最大时长={req.max_processing_minutes}分钟",
    )
    return {
        "success": True,
        **_serialize(record),
        "message": "个人自动流程参数已保存，将在下一次调度生效",
    }


async def _run_requirements_for_user(user: User, batch_size: int = 50):
    """直接调用底层拉取流程，绕过 FastAPI 依赖注入层，避免嵌套事件循环问题。"""
    import json as _json
    from app.user_settings import get_active_setting, activate_user_business_settings
    from app.jobs import create_background_job, update_background_job
    from app.owner_mapping_cls import get_tapd_account_by_display_name

    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        # 切换用户业务设置上下文
        activate_user_business_settings(db, user.id)

        # 解析运行参数
        ws_id = get_active_setting("tapd_workspace_ids").split(",")[0].strip()
        status_filter = get_active_setting("story_status_filter")

        # 操作员用自己的处理人名过滤，管理员拉全量
        tapd_owner = None
        if user.role != "admin":
            display = user.display_name or user.username
            tapd_owner = get_tapd_account_by_display_name(display)

        # 创建 BackgroundJob 并写入初始进度
        bg_job = create_background_job(
            db, job_type="fetch_process",
            total=0, created_by=user.username,
            payload={
                "ws_id": ws_id, "status_filter": status_filter,
                "tapd_owner": tapd_owner, "limit": batch_size,
                "user_id": user.id, "user_role": user.role,
            },
        )
        job_id = bg_job.job_id
        init_state = {
            "phase": "fetching",
            "fetch_total": 0, "fetch_new": 0, "fetch_updated": 0,
            "duplicate_total": 0, "duplicate_processed": 0,
            "duplicate_succeeded": 0, "duplicate_failed": 0,
            "score_total": 0, "score_processed": 0,
            "score_succeeded": 0, "score_failed": 0,
        }
        update_background_job(db, job_id, result=_json.dumps(init_state))

        # 立即把 job_id 写回 UserAutomationSettings，前端心跳可感知
        record = db.query(UserAutomationSettings).filter(UserAutomationSettings.user_id == user.id).first()
        if record:
            record.current_job_id = job_id
            db.commit()

        # 启动完整后台流程（在当前事件循环里直接 await，避免二次嵌套线程）
        from app.routers.user_requirements import _run_full_fetch_process_coro
        await _run_full_fetch_process_coro(job_id, ws_id, status_filter, tapd_owner, batch_size, user.id, user.role)

    except Exception as e:
        import traceback
        print(f"[automation] _run_requirements_for_user 失败: {e}\n" + traceback.format_exc())
    finally:
        db.close()


async def _run_classification_for_user(user: User, batch_size: int = 50):
    """启动本用户范围的分类任务；同一时刻已有分类任务则跳过。"""
    from app.classifier import process_batch
    from app.database import get_status
    from app.user_settings import get_user_business_settings, activate_user_business_settings
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        if not get_user_business_settings(db, user.id).get("deepseek_api_key") or get_status("bot_state", "idle") == "running":
            return
        activate_user_business_settings(db, user.id)
        owner = None
        if user.role != "admin":
            from app.owner_mapping_cls import get_tapd_account_by_display_name
            owner = get_tapd_account_by_display_name(user.display_name or user.username)
        job = create_background_job(db, "classification", total=0, created_by=user.username)
        # 写回 current_job_id 供前端感知
        record = db.query(UserAutomationSettings).filter(UserAutomationSettings.user_id == user.id).first()
        if record:
            record.current_job_id = job.job_id
            db.commit()
        # 直接 await，避免嵌套线程
        await process_batch(job_id=job.job_id, created_by=user.username, owner=owner, user_id=user.id)
    except Exception as e:
        import traceback
        print(f"[automation] _run_classification_for_user 失败: {e}\n" + traceback.format_exc())
    finally:
        db.close()


async def _run_prd_for_user(user: User, batch_size: int = 50):
    """自动拉取本用户范围 PRD，并分析本批待分析记录。"""
    from app.routers.prd import AnalyzeRequest, FetchPrdRequest, fetch_prds, start_analyze
    from app.user_settings import activate_user_business_settings
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        activate_user_business_settings(db, user.id)
        owner = None if user.role == "admin" else (user.display_name or user.username)
        await fetch_prds(
            FetchPrdRequest(limit=batch_size, owner=owner),
            db=db,
            user=user,
        )
        query = db.query(PrdAnalysisJob).filter(PrdAnalysisJob.status == "pending")
        if user.role != "admin":
            query = query.filter(PrdAnalysisJob.owner.like(f"%{user.display_name or user.username}%"))
        ids = [row.id for row in query.order_by(PrdAnalysisJob.tapd_created.desc()).limit(batch_size).all()]
        if ids:
            result = await start_analyze(AnalyzeRequest(record_ids=ids), db=db, user=user)
            # 写回 current_job_id 供前端感知
            if result and result.get("job_id"):
                record = db.query(UserAutomationSettings).filter(UserAutomationSettings.user_id == user.id).first()
                if record:
                    record.current_job_id = result["job_id"]
                    db.commit()
    except Exception as e:
        import traceback
        print(f"[automation] _run_prd_for_user 失败: {e}\n" + traceback.format_exc())
    finally:
        db.close()


def _is_due(last_run_at, now: datetime, interval_minutes: int = 30) -> bool:
    return last_run_at is None or now - last_run_at >= timedelta(minutes=interval_minutes)


def run_user_automation_cycle():
    """调度器心跳：检查所有已开启用户的三类自动任务（per-user 调度参数）。"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        records = db.query(UserAutomationSettings).filter(UserAutomationSettings.auto_flow_enabled == True).all()
        now = datetime.now()
        from app.database import User
        for record in records:
            user = db.query(User).filter(User.id == record.user_id, User.is_active == True).first()
            if not user:
                continue
            interval = record.schedule_interval_minutes or 30
            batch_size = record.batch_size or 50
            max_minutes = record.max_processing_minutes or 60
            scheduled = []
            if record.requirements_enabled and _is_due(record.requirements_last_run_at, now, interval):
                record.requirements_last_run_at = now
                scheduled.append(_run_with_timeout(_run_requirements_for_user(user, batch_size), max_minutes, user.username, "requirements"))
            if record.classification_enabled and _is_due(record.classification_last_run_at, now, interval):
                record.classification_last_run_at = now
                scheduled.append(_run_with_timeout(_run_classification_for_user(user, batch_size), max_minutes, user.username, "classification"))
            if record.prd_enabled and _is_due(record.prd_last_run_at, now, interval):
                record.prd_last_run_at = now
                scheduled.append(_run_with_timeout(_run_prd_for_user(user, batch_size), max_minutes, user.username, "prd"))
            db.commit()
            for coro in scheduled:
                try:
                    from app.jobs import run_async_task
                    import uuid as _uuid
                    _jid = f"auto_cycle_{user.id}_{int(now.timestamp())}_{_uuid.uuid4().hex[:4]}"
                    run_async_task(_jid, coro)
                except Exception as exc:
                    print(f"[automation] 用户 {user.username} 自动流程执行失败: {exc}")
    finally:
        db.close()


async def _run_with_timeout(coro, max_minutes: int, username: str, module: str):
    """超时保护：单次自动处理超过 max_minutes 则终止并记录日志。"""
    try:
        await asyncio.wait_for(coro, timeout=max_minutes * 60)
    except asyncio.TimeoutError:
        print(f"[automation] 用户 {username} {module} 模块超时（{max_minutes}分钟），已终止本次执行")
