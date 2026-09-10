"""API 路由：通用接口（登录、设置、健康检查）

对应 agents.md 6.3 节
"""
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, User
from app.config import settings
from app.auth import (
    get_current_user, hash_password, verify_password, create_token,
    ensure_default_admin,
    is_account_locked, register_failed_login, register_success_login,
    public_user_info,
    ROLE_ADMIN, ROLE_OPERATOR,
)
from app.audit import log_audit, log_operation
from app.user_settings import (
    PERSONAL_FIELDS, get_user_business_settings, get_user_override_keys,
    update_user_business_settings,
)


router = APIRouter(prefix="/api", tags=["common"])


# ---------- 设置字段类型分组（用于保存时容错转换） ----------
_SETTING_INT_FIELDS = {
    "schedule_interval_minutes", "batch_size", "login_max_attempts",
    "login_lock_minutes", "backup_retention_days",
    "question_max_count", "duplicate_history_limit", "prd_pass_threshold",
    "prd_weight_coverage", "prd_weight_functional",
    "prd_weight_interaction", "prd_weight_acceptance",
}
_SETTING_FLOAT_FIELDS = {"reliability_threshold"}
_SETTING_BOOL_FIELDS = {"auto_assign_owner", "auto_write_comment", "owner_update_comment"}


def _coerce_setting_value(field: str, value: Any) -> Any:
    """把前端传入的值转换为目标类型；无法解析或为空时返回 None（调用方跳过该字段）。

    这样即便前端因交互原因传来空字符串 / null / 对象，也不会触发 422，
    而是安全地忽略该字段（保留原有值或系统默认）。
    """
    if value is None:
        return None
    # 空字符串视为“不修改”
    if isinstance(value, str) and value.strip() == "":
        return None
    # 对象 / 数组无法解析为标量设置，直接忽略
    if isinstance(value, (dict, list)):
        return None
    if field in _SETTING_BOOL_FIELDS:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() == "true"
        return bool(value)
    if field in _SETTING_FLOAT_FIELDS:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if field in _SETTING_INT_FIELDS:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
    # 其余按字符串处理（TAPD/DeepSeek/状态映射/字段映射等）
    return str(value)


# ---------- 数据模型 ----------
class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ---------- POST /auth/login：登录 ----------
@router.post("/auth/login")
async def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    """用户登录（含账号锁定、登录日志）"""
    user = db.query(User).filter(User.username == req.username).first()
    if not user:
        log_operation(actor=req.username, action="auth.login", result="failed",
                      detail="用户不存在", request=request)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if is_account_locked(user):
        raise HTTPException(status_code=403, detail="账号已被临时锁定，请稍后再试")

    if not verify_password(req.password, user.password_hash):
        register_failed_login(user, request, "密码错误")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")

    register_success_login(user, request)
    token = create_token(user.id, user.username, user.role)
    log_audit(db, "login", user.username)
    log_operation(actor=user.username, action="auth.login", request=request)

    info = public_user_info(user)
    return {
        "token": token,
        "user": info,
    }


# ---------- GET /auth/me：当前用户信息 ----------
@router.get("/auth/me")
async def get_me(user: User = Depends(get_current_user)):
    return public_user_info(user)


# ---------- GET /settings：获取设置 ----------
@router.get("/settings")
async def get_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取当前账号生效的业务设置（凭据脱敏）。"""
    personal = get_user_business_settings(db, user.id)
    override_keys = get_user_override_keys(db, user.id)

    def _mask(s: str) -> str:
        if not s or len(s) <= 8:
            return "*" * (len(s) or 8)
        return s[:4] + "*" * (len(s) - 8) + s[-4:]

    return {
        "tapd_api_endpoint": personal["tapd_api_endpoint"],
        "tapd_auth_token": _mask(personal["tapd_auth_token"]),
        "tapd_auth_token_configured": bool(personal["tapd_auth_token"]),
        "tapd_workspace_ids": personal["tapd_workspace_ids"],
        "tapd_api_user": personal["tapd_api_user"],
        "deepseek_api_key": _mask(personal["deepseek_api_key"]),
        "deepseek_api_key_configured": bool(personal["deepseek_api_key"]),
        "deepseek_base_url": personal["deepseek_base_url"],
        "deepseek_model": personal["deepseek_model"],
        "bot_name": settings.bot_name,
        "schedule_interval_minutes": settings.schedule_interval_minutes,
        "batch_size": settings.batch_size,
        "story_status_filter": settings.story_status_filter,
        "reliability_threshold": personal["reliability_threshold"],
        "duplicate_history_limit": personal["duplicate_history_limit"],
        "question_max_count": personal["question_max_count"],
        "question_focus": personal["question_focus"],
        "scoring_strictness": personal["scoring_strictness"],
        "prd_strictness": personal["prd_strictness"],
        "prd_pass_threshold": personal["prd_pass_threshold"],
        "prd_weight_coverage": personal["prd_weight_coverage"],
        "prd_weight_functional": personal["prd_weight_functional"],
        "prd_weight_interaction": personal["prd_weight_interaction"],
        "prd_weight_acceptance": personal["prd_weight_acceptance"],
        "story_status_duplicate": settings.story_status_duplicate,
        "story_status_product_designing": settings.story_status_product_designing,
        "story_status_prd_review": settings.story_status_prd_review,
        "custom_field_tenant_version": settings.custom_field_tenant_version,
        "custom_field_priority": settings.custom_field_priority,
        "custom_field_prd": settings.custom_field_prd,
        "custom_field_user_requirement": settings.custom_field_user_requirement,
        # 分类机器人配置
        "auto_assign_owner": settings.auto_assign_owner,
        "auto_write_comment": settings.auto_write_comment,
        "owner_update_comment": settings.owner_update_comment,
        "login_max_attempts": settings.login_max_attempts,
        "login_lock_minutes": settings.login_lock_minutes,
        "backup_retention_days": settings.backup_retention_days,
        "allowed_origins": settings.allowed_origins,
        "personal_override_keys": override_keys,
        "settings_scope": "personal",
    }


# ---------- POST /settings：保存设置（admin） ----------
@router.post("/settings")
async def save_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存设置。

    直接解析原始请求体并对字段类型做容错转换，避免前端因清空输入框、交互产生
    异常类型等导致 422。TAPD、DeepSeek 和评分标准为账号私有配置，操作员与管理员
    均可修改且不影响他人；其余系统级配置仅管理员可改。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    scope = body.get("scope", "personal")
    if scope not in ("personal", "system"):
        scope = "personal"

    # ---------- 个人业务配置 ----------
    personal_updates = {}
    if scope != "system":
        for field in PERSONAL_FIELDS:
            if field not in body:
                continue
            value = body[field]
            # 前端回传脱敏凭据（含 *）时跳过，不覆盖个人真实凭据
            if field in {"tapd_auth_token", "deepseek_api_key"} and isinstance(value, str) and "*" in value:
                continue
            coerced = _coerce_setting_value(field, value)
            if coerced is None:
                continue
            personal_updates[field] = coerced

    weight_fields = (
        "prd_weight_coverage", "prd_weight_functional",
        "prd_weight_interaction", "prd_weight_acceptance",
    )
    if any(field in personal_updates for field in weight_fields):
        effective = get_user_business_settings(db, user.id)
        effective.update(personal_updates)
        if sum(int(effective[field]) for field in weight_fields) != 100:
            raise HTTPException(status_code=400, detail="PRD 维度权重总和必须等于 100")

    if personal_updates:
        update_user_business_settings(db, user.id, personal_updates)
        log_audit(db, "personal_business_settings_update", user.username, detail=str(sorted(personal_updates)))

    # ---------- 系统级配置（仅管理员） ----------
    global_env_map = {
        "bot_name": "BOT_NAME",
        "schedule_interval_minutes": "SCHEDULE_INTERVAL_MINUTES",
        "batch_size": "BATCH_SIZE",
        "story_status_filter": "STORY_STATUS_FILTER",
        "story_status_duplicate": "STORY_STATUS_DUPLICATE",
        "story_status_product_designing": "STORY_STATUS_PRODUCT_DESIGNING",
        "story_status_prd_review": "STORY_STATUS_PRD_REVIEW",
        "custom_field_tenant_version": "CUSTOM_FIELD_TENANT_VERSION",
        "custom_field_priority": "CUSTOM_FIELD_PRIORITY",
        "custom_field_prd": "CUSTOM_FIELD_PRD",
        "custom_field_user_requirement": "CUSTOM_FIELD_USER_REQUIREMENT",
        "auto_assign_owner": "AUTO_ASSIGN_OWNER",
        "auto_write_comment": "AUTO_WRITE_COMMENT",
        "owner_update_comment": "OWNER_UPDATE_COMMENT",
        "login_max_attempts": "LOGIN_MAX_ATTEMPTS",
        "login_lock_minutes": "LOGIN_LOCK_MINUTES",
        "backup_retention_days": "BACKUP_RETENTION_DAYS",
        "allowed_origins": "ALLOWED_ORIGINS",
    }
    global_updates = {}
    if user.role == "admin" and scope == "system":
        bool_fields = _SETTING_BOOL_FIELDS
        for field, env_key in global_env_map.items():
            if field not in body:
                continue
            coerced = _coerce_setting_value(field, body[field])
            if coerced is None:
                continue
            if field in bool_fields:
                global_updates[env_key] = "true" if coerced else "false"
            else:
                global_updates[env_key] = str(coerced)
        if global_updates:
            settings.update_env(global_updates)
            log_audit(db, "system_settings_update", user.username, detail=str(sorted(global_updates)))

    return {
        "success": True,
        "personal_updated_keys": sorted(personal_updates),
        "system_updated_keys": sorted(global_updates),
        "message": "个人业务配置已保存，修改仅对当前账号生效",
    }


# ---------- POST /auth/change-password：修改密码 ----------
@router.post("/auth/change-password")
async def change_password(
    req: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    user.password_hash = hash_password(req.new_password)
    db.commit()
    log_audit(db, "change_password", user.username)
    return {"success": True}


# ---------- GET /health：健康检查 ----------
@router.get("/health")
async def health_check():
    """健康检查（无需登录）"""
    return {
        "status": "ok",
        "bot_name": settings.bot_name,
        "environment": settings.environment,
        "tapd_configured": bool(settings.tapd_auth_token) and "*" not in settings.tapd_auth_token,
        "deepseek_configured": bool(settings.deepseek_api_key) and "*" not in settings.deepseek_api_key,
    }
