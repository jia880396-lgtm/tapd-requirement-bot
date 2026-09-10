"""用户认证与会话管理

支持 admin / operator 两种角色（参考 agents.md 8.9）：
- admin：全部操作，含"强行提交"、"手动触发"、"停止执行"
- operator：只能查看和处理自己的任务（按 created_by 隔离）

使用 JWT token 做会话保持。
包含登录限流、账号锁定、登录日志等安全功能。
"""
import os
import hashlib
import hmac
import secrets
import time
import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, get_session_local, User, LoginLog


# ---------- 角色常量 ----------
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"

# 角色权限矩阵（从低到高）
ROLE_LEVELS = {ROLE_OPERATOR: 1, ROLE_ADMIN: 2}


# ---------- 密码哈希（简单 PBKDF2，避免依赖 passlib/bcrypt） ----------
def hash_password(password: str) -> str:
    """生成密码哈希（PBKDF2-HMAC-SHA256）"""
    salt = secrets.token_hex(16)
    iterations = 100000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2${iterations}${salt}${dk.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码"""
    try:
        algorithm, iterations, salt, hash_hex = password_hash.split("$", 3)
        if algorithm != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---------- JWT Token ----------
def create_token(user_id: int, username: str, role: str, expires_hours: int = 24) -> str:
    """生成简单 JWT token（不依赖 pyjwt，手写 HMAC-SHA256）"""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "exp": int(time.time()) + expires_hours * 3600,
        "iat": int(time.time()),
    }

    def _b64(obj):
        import base64
        return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=").decode()

    header_b64 = _b64(header)
    payload_b64 = _b64(payload)
    msg = f"{header_b64}.{payload_b64}"
    sig = hmac.new(settings.secret_key.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}.{sig}"


def decode_token(token: str) -> Optional[dict]:
    """解码并校验 token"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig = parts
        msg = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(settings.secret_key.encode(), msg.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None

        import base64
        # 补齐 padding
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ---------- FastAPI 依赖 ----------
security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """获取当前登录用户"""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 无效或已过期")

    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    # 当前请求中的 TAPD、DeepSeek 与评分参数使用该账号个人覆盖配置。
    from app.user_settings import activate_user_business_settings
    activate_user_business_settings(db, user.id)
    return user


def require_admin_dep(user: User = Depends(get_current_user)) -> User:
    """要求 admin 角色（Depends 依赖模式，用于 FastAPI 依赖注入）"""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def require_admin(request: Request) -> User:
    """要求 admin 角色（请求级，直接调用模式）

    用法：require_admin(request)
    """
    user = require_user(request)
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def require_operator(user: User = Depends(get_current_user)) -> User:
    """要求 operator 及以上角色"""
    user_level = ROLE_LEVELS.get(user.role, 0)
    if user_level < ROLE_LEVELS.get(ROLE_OPERATOR, 0):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
    return user


# ---------- 请求级用户解析（非 Depends 模式）----------
def _client_ip(request: Optional[Request]) -> str:
    if not request:
        return ""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _extract_token(request: Request) -> Optional[str]:
    """从 Header Authorization: Bearer xxx 中提取 token"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def get_user_from_request(request: Request) -> Optional[User]:
    """从请求中解析当前用户（非 Depends 模式），无登录返回 None"""
    token = _extract_token(request)
    if not token:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == payload["user_id"]).first()
        if user is None or not user.is_active:
            return None
        return user
    finally:
        db.close()


def require_user(request: Request) -> User:
    """要求已登录（请求级），否则 401"""
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或会话已过期，请重新登录",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已停用，请联系管理员",
        )
    return user


def require_role(min_role: str):
    """请求级权限依赖工厂：要求当前用户角色等级 >= min_role"""
    min_level = ROLE_LEVELS.get(min_role, 0)

    def _dep(request: Request) -> User:
        user = require_user(request)
        user_level = ROLE_LEVELS.get(user.role, 0)
        if user_level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要 {min_role} 及以上角色",
            )
        return user

    return _dep


# ---------- 登录限流 ----------
def is_account_locked(user: User) -> bool:
    """检查账号是否已被锁定"""
    if user.locked_until and user.locked_until > datetime.now():
        return True
    return False


def register_failed_login(user: User, request: Optional[Request], reason: str):
    """登录失败：增加失败次数，超限则锁定"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user.id).first()
        if not u:
            return
        u.failed_login_count = (u.failed_login_count or 0) + 1
        if u.failed_login_count >= settings.login_max_attempts:
            u.locked_until = datetime.now() + timedelta(minutes=settings.login_lock_minutes)
            u.failed_login_count = 0
        db.commit()
        db.add(LoginLog(
            username=user.username,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:500] if request else "",
            success=False,
            reason=reason,
        ))
        db.commit()
    finally:
        db.close()


def register_success_login(user: User, request: Optional[Request]):
    """登录成功：重置失败次数，记录登录日志"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user.id).first()
        if u:
            u.failed_login_count = 0
            u.locked_until = None
            u.last_login_at = datetime.now()
            u.last_login_ip = _client_ip(request)
            db.commit()
        db.add(LoginLog(
            username=user.username,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:500] if request else "",
            success=True,
        ))
        db.commit()
    finally:
        db.close()


def public_user_info(user: User) -> dict:
    """对外安全的用户信息（不含密码哈希）"""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "last_login_ip": user.last_login_ip,
    }


# ---------- 初始化默认管理员 ----------
def ensure_default_admin(db: Session) -> None:
    """首次启动时创建默认 admin 账号（admin / admin123）"""
    existing = db.query(User).filter(User.username == "admin").first()
    if existing:
        return
    admin = User(
        username="admin",
        password_hash=hash_password("admin123"),
        role="admin",
        display_name="默认管理员",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    print("[startup] 已创建默认管理员账号：admin / admin123（请尽快修改密码）")
