"""操作审计日志

记录关键操作：登录、强行提交、配置修改、手动触发任务等。
日志同时写入数据库 + 文件（logs/audit/）。

提供两个函数：
- log_audit: 旧版，写入 ProcessLog（用于现有路由）
- log_operation: 新版，写入 OperationAuditLog（用于分类机器人/用户管理等新路由）
"""
import os
import logging
from datetime import datetime
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import ProcessLog, OperationAuditLog, get_session_local


logger = logging.getLogger(__name__)


def _client_ip(request: Optional[Request]) -> str:
    if not request:
        return ""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request and request.client else ""


def log_audit(
    db: Session,
    action: str,
    operator: str,
    target: Optional[str] = None,
    detail: Optional[str] = None,
    level: str = "info",
) -> None:
    """记录审计日志（旧版，写入 ProcessLog）

    Args:
        action: 操作类型，如 login / force_advance / config_update / manual_trigger
        operator: 操作人用户名
        target: 操作目标，如 story_id
        detail: 详细信息
        level: info / warning / error
    """
    # 1. 写入数据库 ProcessLog
    log_entry = ProcessLog(
        job_id=f"audit_{action}",
        job_type="audit",
        story_id=target or "",
        level=level,
        message=f"[{operator}] {action}" + (f" -> {target}" if target else "") + (f" | {detail}" if detail else ""),
    )
    try:
        db.add(log_entry)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[audit] 写入数据库失败: {e}")

    # 2. 追加写入文件
    try:
        audit_dir = os.path.join(settings.log_dir, "audit")
        os.makedirs(audit_dir, exist_ok=True)
        log_file = os.path.join(audit_dir, f"audit_{datetime.now().strftime('%Y-%m-%d')}.log")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level.upper()}] [{operator}] {action}"
        if target:
            line += f" -> {target}"
        if detail:
            line += f" | {detail}"
        line += "\n"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"[audit] 写入文件失败: {e}")


def log_operation(
    actor: str,
    action: str,
    target: Optional[str] = None,
    detail: Optional[str] = None,
    result: str = "success",
    request: Optional[Request] = None,
):
    """记录一条审计日志到 OperationAuditLog 表（新版，用于分类机器人/用户管理等）

    detail 中禁止包含敏感值（密码/Token/API Key）。
    """
    db = get_session_local()()
    try:
        db.add(OperationAuditLog(
            actor=actor or "anonymous",
            actor_ip=_client_ip(request),
            action=action,
            target=target,
            detail=detail,
            result=result,
        ))
        db.commit()
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")
    finally:
        db.close()
