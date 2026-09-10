"""按账号隔离的业务配置读取与保存。"""
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.database import UserBusinessSettings

PERSONAL_FIELDS = {
    "tapd_api_endpoint", "tapd_auth_token", "tapd_workspace_ids", "tapd_api_user",
    "deepseek_api_key", "deepseek_base_url", "deepseek_model",
    "reliability_threshold", "duplicate_history_limit", "question_max_count",
    "question_focus", "scoring_strictness", "prd_strictness", "prd_pass_threshold",
    "prd_weight_coverage", "prd_weight_functional", "prd_weight_interaction",
    "prd_weight_acceptance",
    "vision_base_url", "vision_api_key", "vision_model",
}


def _defaults() -> dict[str, Any]:
    return {field: getattr(settings, field) for field in PERSONAL_FIELDS}


def _read_overrides(record: UserBusinessSettings | None) -> dict[str, Any]:
    if not record or not record.config_json:
        return {}
    try:
        raw = json.loads(record.config_json)
        return raw if isinstance(raw, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def get_user_business_settings(db: Session, user_id: int) -> dict[str, Any]:
    """返回用户生效配置：个人覆盖优先，未填写项回退系统默认。"""
    record = db.query(UserBusinessSettings).filter(UserBusinessSettings.user_id == user_id).first()
    merged = _defaults()
    merged.update({k: v for k, v in _read_overrides(record).items() if k in PERSONAL_FIELDS and v is not None})
    return merged


def get_user_override_keys(db: Session, user_id: int) -> list[str]:
    record = db.query(UserBusinessSettings).filter(UserBusinessSettings.user_id == user_id).first()
    return sorted(k for k in _read_overrides(record) if k in PERSONAL_FIELDS)


def update_user_business_settings(db: Session, user_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    """仅保存允许的个人覆盖字段；空字符串表示恢复该字段的系统默认。"""
    record = db.query(UserBusinessSettings).filter(UserBusinessSettings.user_id == user_id).first()
    if not record:
        record = UserBusinessSettings(user_id=user_id, config_json="{}")
        db.add(record)
        db.flush()

    overrides = _read_overrides(record)
    for key, value in updates.items():
        if key not in PERSONAL_FIELDS or value is None:
            continue
        if isinstance(value, str) and not value.strip():
            overrides.pop(key, None)
        else:
            overrides[key] = value
    record.config_json = json.dumps(overrides, ensure_ascii=False)
    db.commit()
    return get_user_business_settings(db, user_id)


_active_settings: ContextVar[dict[str, Any] | None] = ContextVar("active_user_settings", default=None)


def get_active_setting(name: str) -> Any:
    values = _active_settings.get()
    if values and name in values:
        return values[name]
    return getattr(settings, name)


def activate_user_business_settings(db: Session, user_id: int) -> None:
    """为当前请求协程设置个人配置；后台线程请使用上下文管理器。"""
    _active_settings.set(get_user_business_settings(db, user_id))


@contextmanager
def use_user_business_settings(db: Session, user_id: int):
    """在一次请求或后台任务中激活指定账号的个人配置。"""
    token = _active_settings.set(get_user_business_settings(db, user_id))
    try:
        yield
    finally:
        _active_settings.reset(token)


class UserSettingsProxy:
    """兼容需要完整配置对象的调用点。"""
    def __init__(self, values: dict[str, Any]):
        self._values = values

    def __getattr__(self, name: str) -> Any:
        if name in self._values:
            return self._values[name]
        return getattr(settings, name)
