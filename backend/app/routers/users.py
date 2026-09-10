"""API 路由：用户管理（仅管理员）

从 tapd-classification-bot 迁移而来，提供用户增删改查、重置密码、停用等管理功能。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db, User, LoginLog
from app.auth import (
    require_user, require_admin,
    hash_password, verify_password,
    public_user_info, ROLE_ADMIN, ROLE_OPERATOR,
)
from app.audit import log_operation


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


# ---------- 数据模型 ----------
class UserCreateRequest(BaseModel):
    username: str
    display_name: str = ""
    password: str
    role: str = ROLE_OPERATOR
    must_change_password: bool = True


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    must_change_password: Optional[bool] = None


class ResetPasswordRequest(BaseModel):
    new_password: str
    must_change_password: bool = True


# ---------- 用户 CRUD ----------
@router.get("")
async def list_users(request: Request, db: Session = Depends(get_db)):
    """获取用户列表（仅管理员）"""
    admin = require_admin(request)
    records = db.query(User).order_by(desc(User.created_at)).all()
    return {
        "status": "success",
        "data": [
            {
                **public_user_info(r),
                "failed_login_count": r.failed_login_count,
                "locked_until": r.locked_until.isoformat() if r.locked_until else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "created_by": r.created_by,
            }
            for r in records
        ],
    }


@router.post("")
async def create_user(body: UserCreateRequest, request: Request, db: Session = Depends(get_db)):
    """创建用户（仅管理员）"""
    admin = require_admin(request)
    if body.role not in (ROLE_ADMIN, ROLE_OPERATOR):
        raise HTTPException(status_code=400, detail="角色无效")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="密码长度不少于 8 位")
    u = User(
        username=body.username,
        display_name=body.display_name or body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
        must_change_password=body.must_change_password,
        created_by=admin.username,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    log_operation(actor=admin.username, action="user.create", target=body.username,
                  detail=f"role={body.role}", request=request)
    return {"status": "success", "data": public_user_info(u), "message": "用户创建成功"}


@router.put("/{user_id}")
async def update_user(user_id: int, body: UserUpdateRequest, request: Request, db: Session = Depends(get_db)):
    """更新用户信息（仅管理员）"""
    admin = require_admin(request)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.role is not None:
        if body.role not in (ROLE_ADMIN, ROLE_OPERATOR):
            raise HTTPException(status_code=400, detail="角色无效")
        u.role = body.role
    if body.display_name is not None:
        u.display_name = body.display_name
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.must_change_password is not None:
        u.must_change_password = body.must_change_password
    db.commit()
    log_operation(actor=admin.username, action="user.update", target=u.username,
                  detail=f"role={u.role}, active={u.is_active}", request=request)
    return {"status": "success", "data": public_user_info(u)}


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: int, body: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """重置用户密码（仅管理员）"""
    admin = require_admin(request)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="密码长度不少于 8 位")
    u.password_hash = hash_password(body.new_password)
    u.must_change_password = body.must_change_password
    u.failed_login_count = 0
    u.locked_until = None
    db.commit()
    log_operation(actor=admin.username, action="user.reset_password", target=u.username, request=request)
    return {"status": "success", "message": "密码已重置"}


@router.delete("/{user_id}")
async def deactivate_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    """停用用户（仅管理员）"""
    admin = require_admin(request)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="不能停用自己")
    u.is_active = False
    db.commit()
    log_operation(actor=admin.username, action="user.deactivate", target=u.username, request=request)
    return {"status": "success", "message": "账号已停用"}


# ---------- 登录日志 ----------
@router.get("/login-logs")
async def list_login_logs(request: Request, page: int = 1, size: int = 50, db: Session = Depends(get_db)):
    """获取登录日志（仅管理员）"""
    require_admin(request)
    total = db.query(LoginLog).count()
    records = db.query(LoginLog).order_by(desc(LoginLog.login_time)) \
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
