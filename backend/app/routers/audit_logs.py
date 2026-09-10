"""API 路由：审计日志

提供操作审计日志和登录日志的查询功能（仅管理员）。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db, OperationAuditLog, LoginLog
from app.auth import require_admin


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audit-logs", tags=["audit-logs"])


@router.get("")
async def list_audit_logs(
    request: Request,
    page: int = 1,
    size: int = 50,
    action: Optional[str] = None,
    actor: Optional[str] = None,
    module: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """获取操作审计日志（仅管理员）

    支持按 action、actor、module 筛选。
    module 参数用于按模块前缀筛选（如 classification / user / prd 等）。
    """
    require_admin(request)
    q = db.query(OperationAuditLog)
    if action:
        q = q.filter(OperationAuditLog.action == action)
    if actor:
        q = q.filter(OperationAuditLog.actor.like(f"%{actor}%"))
    if module:
        q = q.filter(OperationAuditLog.action.like(f"{module}%"))

    total = q.count()
    records = q.order_by(desc(OperationAuditLog.created_at)) \
        .offset((page - 1) * size).limit(size).all()
    return {
        "total": total, "page": page, "size": size,
        "data": [
            {
                "id": r.id,
                "actor": r.actor,
                "actor_ip": r.actor_ip,
                "action": r.action,
                "target": r.target,
                "detail": r.detail,
                "result": r.result,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }


@router.get("/login-logs")
async def list_login_logs(
    request: Request,
    page: int = 1,
    size: int = 50,
    username: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """获取登录日志（仅管理员）"""
    require_admin(request)
    q = db.query(LoginLog)
    if username:
        q = q.filter(LoginLog.username.like(f"%{username}%"))
    total = q.count()
    records = q.order_by(desc(LoginLog.login_time)) \
        .offset((page - 1) * size).limit(size).all()
    return {
        "total": total, "page": page, "size": size,
        "data": [
            {
                "id": r.id,
                "username": r.username,
                "ip": r.ip,
                "user_agent": r.user_agent,
                "success": r.success,
                "reason": r.reason,
                "login_time": r.login_time.isoformat() if r.login_time else None,
            }
            for r in records
        ],
    }


@router.get("/modules")
async def list_audit_modules(request: Request):
    """获取所有审计日志模块分类（仅管理员）"""
    require_admin(request)
    return {
        "status": "success",
        "data": [
            {"key": "all", "label": "全部"},
            {"key": "auth", "label": "认证登录"},
            {"key": "user", "label": "用户管理"},
            {"key": "classification", "label": "分类机器人"},
            {"key": "settings", "label": "系统设置"},
            {"key": "writeback", "label": "写回操作"},
            {"key": "scheduler", "label": "定时任务"},
            {"key": "job", "label": "后台任务"},
        ],
    }
