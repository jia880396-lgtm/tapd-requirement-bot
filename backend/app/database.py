"""数据库模型与会话管理

对应 agents.md 第四节：4 张核心表
- UserRequirementJob：用户需求处理记录
- PrdAnalysisJob：PRD 分析记录
- BackgroundJob：后台任务统一记录
- WritebackLog：评论写回日志
- User：用户表（admin/operator 多角色）
"""
import json
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey,
    create_engine, event,
)
from sqlalchemy.pool import QueuePool
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func

from app.config import settings


Base = declarative_base()


# ---------- 用户表 ----------
class User(Base):
    """系统用户表，支持 admin / operator 两种角色"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=False)  # bcrypt hash
    role = Column(String(16), default="operator", nullable=False)  # admin / operator
    display_name = Column(String(64))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    must_change_password = Column(Boolean, default=False)
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(64), nullable=True)
    failed_login_count = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    created_by = Column(String(64), nullable=True)


# ---------- 按用户业务配置 ----------
class UserBusinessSettings(Base):
    """用户个人的 TAPD、DeepSeek 与评分配置。

    config_json 仅保存用户明确覆盖的字段；未保存字段持续使用 .env 中的系统默认值，
    因此不同账号的修改互不影响，也兼容既有部署配置。
    """
    __tablename__ = "user_business_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, index=True, nullable=False)
    config_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ---------- 按用户自动流程配置 ----------
class UserAutomationSettings(Base):
    """用户自主开启的自动流程配置。

    所有开关默认关闭；auto_flow_enabled 是用户总开关，三个模块开关控制各页面任务。
    调度节奏支持 per-user 配置：schedule_interval_minutes、batch_size、max_processing_minutes。
    """
    __tablename__ = "user_automation_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, index=True, nullable=False)
    auto_flow_enabled = Column(Boolean, default=False, nullable=False)
    requirements_enabled = Column(Boolean, default=False, nullable=False)
    classification_enabled = Column(Boolean, default=False, nullable=False)
    prd_enabled = Column(Boolean, default=False, nullable=False)
    requirements_last_run_at = Column(DateTime, nullable=True)
    classification_last_run_at = Column(DateTime, nullable=True)
    prd_last_run_at = Column(DateTime, nullable=True)
    # per-user 调度参数
    schedule_interval_minutes = Column(Integer, default=30, nullable=False)
    batch_size = Column(Integer, default=50, nullable=False)
    max_processing_minutes = Column(Integer, default=60, nullable=False)
    # 最近一次自动拉取任务 ID（前端轮询进度用）
    current_job_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ---------- 用户需求处理记录 ----------
class UserRequirementJob(Base):
    """用户需求处理记录

    status: pending/scored/duplicate/confirmed/rejected
    """
    __tablename__ = "user_requirement_jobs"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(64), unique=True, index=True)
    story_id = Column(String(64), index=True)
    workspace_id = Column(String(32))
    title = Column(Text)
    description = Column(Text)                              # 用户原始需求（客户问题描述）
    image_paths = Column(Text, default="")                  # JSON 数组：需求描述中截图地址（供视觉识别）
    image_descriptions = Column(Text, default="")           # 截图 AI 识别文字（与原文隔离，按需拼接）
    tenant_version = Column(String(64))                     # custom_field_17
    priority = Column(String(64))                           # custom_field_18
    creator = Column(String(128))                           # TAPD 提交人
    owner = Column(String(256))                             # TAPD 处理人（owner，多人用分号分隔）
    reliability_score = Column(Float)
    ai_score_10 = Column(Integer)                       # 0-100
    ai_score_reason = Column(String(20))                    # AI打分理由（10字以内）
    reliability_detail = Column(Text)                       # JSON：各维度得分
    manual_score = Column(Float)                            # 人工打分 1-10（0.5 步进，人工复核修正用）
    manual_score_comment = Column(Text)                     # 人工打分备注
    manual_score_by = Column(String(64))                    # 人工打分人
    manual_score_at = Column(DateTime)                      # 人工打分时间
    is_duplicate = Column(Boolean, default=False)
    duplicate_with = Column(Text)                           # JSON：重复的需求 ID 列表
    similarity = Column(Float)                              # 重复识别相似度 0.0-1.0
    duplicate_detail = Column(Text)                         # JSON：top3 重复需求详情 [{story_id, title, similarity}]
    supplemental_questions = Column(Text)                   # JSON：补充问题清单
    comment_written = Column(Boolean, default=False)
    status = Column(String(32), default="pending", index=True)
    created_by = Column(String(64))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    # TAPD 原始创建时间（用于按需求提交时间排序，区别于本地入库时间）
    tapd_created = Column(DateTime, index=True)


# ---------- PRD 分析记录 ----------
class PrdAnalysisJob(Base):
    """PRD 分析记录

    status: pending/analyzed/reviewed
    """
    __tablename__ = "prd_analysis_jobs"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(64), unique=True, index=True)
    story_id = Column(String(64), index=True)
    workspace_id = Column(String(32))
    title = Column(String(500))                             # 需求标题
    owner = Column(String(128), index=True)                 # 处理人
    creator = Column(String(128))                           # 提交人
    tenant_version = Column(String(128))                    # 租户版本
    priority = Column(String(64))                           # 需求重要程度
    tapd_status = Column(String(32))                        # TAPD 原始状态值（如 status_8）
    tapd_created = Column(DateTime)                         # TAPD 创建时间
    tapd_updated = Column(DateTime)                         # TAPD 更新时间
    prd_content = Column(Text)                              # PRD 原文（需求方案）
    original_requirement = Column(Text)                     # 用户原始需求
    image_paths = Column(Text, default="")                  # JSON 数组：需求描述中截图地址（供视觉识别）
    image_descriptions = Column(Text, default="")           # 截图 AI 识别文字（与原文隔离，按需拼接）
    completeness_score = Column(Float)                      # 0-100
    coverage_detail = Column(Text)                          # JSON：覆盖度详情
    suggestions = Column(Text)                              # JSON：补充建议清单
    manual_score = Column(Float)                            # 人工打分 1-10（0.5 步进，人工复核修正用）
    manual_score_comment = Column(Text)                     # 人工打分备注
    manual_score_by = Column(String(64))                    # 人工打分人
    manual_score_at = Column(DateTime)                      # 人工打分时间
    status = Column(String(32), default="pending", index=True)
    created_by = Column(String(64))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ---------- 后台任务记录 ----------
class BackgroundJob(Base):
    """后台任务统一记录

    job_type: user_requirement / prd_analysis / duplicate_check
    status: running/completed/failed/interrupted
    """
    __tablename__ = "background_jobs"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(64), unique=True, index=True)
    job_type = Column(String(32), index=True)
    status = Column(String(32), default="running", index=True)
    total = Column(Integer, default=0)
    processed = Column(Integer, default=0)
    succeeded = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    result = Column(Text)                                   # JSON 结果
    payload = Column(Text)                                   # JSON：任务恢复所需参数（如 record_ids / user_id），供重启后重跑中断任务
    error_message = Column(Text)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime)
    created_by = Column(String(64))
    created_at = Column(DateTime, default=datetime.now)


# ---------- 评论写回日志 ----------
class WritebackLog(Base):
    """评论写回 TAPD 的日志（兼容量评写回与分类处理人写回）"""
    __tablename__ = "writeback_logs"

    id = Column(Integer, primary_key=True)
    story_id = Column(String(64), index=True)
    workspace_id = Column(String(32))
    action = Column(String(32))                             # reliability_comment / confirm / prd_suggestion
    content = Column(Text)
    success = Column(Boolean)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    # 分类机器人写回处理人时使用的扩展字段
    job_id = Column(String(64), nullable=True, index=True)
    field = Column(String(32), nullable=True)               # owner / comment
    before_value = Column(Text, nullable=True)
    after_value = Column(Text, nullable=True)
    operator = Column(String(64), nullable=True)
    operator_ip = Column(String(64), nullable=True)
    result = Column(String(16), nullable=True)              # success / failed
    error = Column(Text, nullable=True)


# ---------- 处理日志流 ----------
class ProcessLog(Base):
    """处理日志流，前端日志面板展示"""
    __tablename__ = "process_logs"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(64), index=True)                 # 关联 BackgroundJob
    job_type = Column(String(32))                           # user_requirement / prd_analysis
    story_id = Column(String(64), index=True)
    level = Column(String(16), default="info")              # info/warning/error/success
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.now, index=True)


# ---------- 分类结果记录 ----------
class Classification(Base):
    """分类结果记录（需求分类机器人）"""
    __tablename__ = "classifications"
    id = Column(Integer, primary_key=True)
    story_id = Column(String(64), index=True)
    story_title = Column(Text)
    story_description = Column(Text)
    category_l1 = Column(String(64))
    category_l2 = Column(String(64))
    confidence = Column(String(16))
    reason = Column(Text)
    original_module = Column(String(64))
    workspace_id = Column(String(32))
    processed_at = Column(DateTime, default=datetime.now)
    comment_id = Column(String(32), nullable=True)
    comment_written = Column(Boolean, default=False)
    assigned_owner = Column(String(64), nullable=True)
    owner_assigned = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    writeback_completed = Column(Boolean, default=False)
    writeback_completed_at = Column(DateTime, nullable=True)
    created_by = Column(String(64), index=True, default="")
    # 新增：与用户需求列表保持一致的业务字段
    tenant_version = Column(String(64), default="")       # 版本
    priority = Column(String(32), default="")             # 重要程度
    original_owner = Column(String(128), default="")      # 原始处理人（TAPD 中的 owner）
    tapd_created = Column(DateTime, index=True)             # TAPD 原始创建时间
    tapd_updated = Column(DateTime, index=True)             # TAPD 原始更新时间


# ---------- 分类运行日志 ----------
class RunLog(Base):
    """分类运行日志"""
    __tablename__ = "run_logs"
    id = Column(Integer, primary_key=True)
    run_time = Column(DateTime, default=datetime.now)
    stories_fetched = Column(Integer, default=0)
    stories_classified = Column(Integer, default=0)
    stories_skipped = Column(Integer, default=0)
    stories_errored = Column(Integer, default=0)
    comments_written = Column(Integer, default=0)
    status = Column(String(16), default="running")
    error_message = Column(Text, nullable=True)
    details = Column(Text, nullable=True)
    owners_assigned = Column(Integer, default=0)


# ---------- 机器人状态键值表 ----------
class BotStatus(Base):
    """机器人状态键值表"""
    __tablename__ = "bot_status"
    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, index=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ---------- 人工修正处理人记录 ----------
class OwnerModification(Base):
    """人工修正处理人记录"""
    __tablename__ = "owner_modifications"
    id = Column(Integer, primary_key=True)
    story_id = Column(String(64), index=True)
    story_title = Column(Text)
    workspace_id = Column(String(32))
    original_predicted_owner = Column(String(64))
    modified_owner = Column(String(64))
    predicted_l1 = Column(String(64))
    predicted_l2 = Column(String(64))
    modified_by = Column(String(64), nullable=True)
    modified_at = Column(DateTime, default=datetime.now)


# ---------- 登录日志 ----------
class LoginLog(Base):
    """登录日志"""
    __tablename__ = "login_logs"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), index=True)
    ip = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    success = Column(Boolean, default=False)
    reason = Column(String(255), nullable=True)
    login_time = Column(DateTime, default=datetime.now)


# ---------- 操作审计日志 ----------
class OperationAuditLog(Base):
    """操作审计日志"""
    __tablename__ = "operation_audit_logs"
    id = Column(Integer, primary_key=True)
    actor = Column(String(64), index=True)
    actor_ip = Column(String(64), nullable=True)
    action = Column(String(64))
    target = Column(String(128), nullable=True)
    detail = Column(Text, nullable=True)
    result = Column(String(16), default="success")
    created_at = Column(DateTime, default=datetime.now)


# ---------- 模块技能 Skill（四流程内化 + 自优化） ----------
class Skill(Base):
    """模块技能主表：一个模块一个 Skill（reliability/duplicate/classification/prd）。"""
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True)
    module_key = Column(String(32), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text)
    active_version_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class SkillVersion(Base):
    """技能版本：每次编辑或优化器产出都落为一个版本，人工审核后激活。"""
    __tablename__ = "skill_versions"

    id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), index=True)
    version_no = Column(Integer, default=1)
    prompt_text = Column(Text, default="")            # 主提示词散文（含 {placeholder}）
    rules_json = Column(Text, default="{}")           # 结构化规则（分类树/术语/跨模块规则/阈值等）
    params_json = Column(Text, default="{}")          # 可调参数（阈值/权重/松紧度）
    kb_context = Column(Text, default="")             # 注入的知识背景（可空，默认复用 knowledge_base）
    status = Column(String(16), default="draft")      # draft | active | archived
    parent_version_id = Column(Integer, nullable=True)
    optimizer_note = Column(Text)
    created_by = Column(String(64), default="system")
    created_at = Column(DateTime, default=datetime.now)


class SkillCase(Base):
    """案例库：将"AI 分类与实际人工分类不准的例子"沉淀下来，供优化器与评测消费。"""
    __tablename__ = "skill_cases"

    id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), index=True)
    requirement_id = Column(String(64), nullable=True)
    requirement_title = Column(Text)
    requirement_desc = Column(Text)
    ai_result_json = Column(Text)                    # 模型当时的输出（JSON 字符串）
    human_result_json = Column(Text)                 # 人工正确结果（JSON 字符串）
    is_mismatch = Column(Boolean, default=True)      # 默认是"不准的例子"
    mismatch_reason = Column(Text)
    source = Column(String(16), default="manual")    # manual | auto
    created_by = Column(String(64), default="system")
    created_at = Column(DateTime, default=datetime.now)


class SkillReviewLog(Base):
    """复盘记录（Phase 4）：定时/手动复盘时记录各模块"优化前→优化后"的准确率变化与建议。

    - 周期性工作流（定期复盘）或管理员手动「立即复盘」都会写入一条记录。
    - 复盘只产出草稿版本 + 记录评测对比，绝不自动激活；是否采纳由管理员在界面决定。
    """
    __tablename__ = "skill_review_logs"

    id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), index=True)
    module_key = Column(String(32), index=True, nullable=False)
    run_at = Column(DateTime, default=datetime.now)
    new_case_count = Column(Integer, default=0)           # 距上次复盘新增的误判案例数
    total_cases = Column(Integer, default=0)             # 评测时案例库总样本数
    draft_version_id = Column(Integer, nullable=True)     # 本次复盘产出的草稿版本（无则空）
    active_accuracy = Column(Float, nullable=True)
    draft_accuracy = Column(Float, nullable=True)
    delta = Column(Float, nullable=True)                 # draft - active
    recommendation = Column(String(16), default="none")   # adopt | review | skip | none
    note = Column(Text)
    created_by = Column(String(64), default="system")


# ---------- 会话管理 ----------
_engine = None
_SessionLocal = None


def _apply_sqlite_pragmas(dbapi_conn, conn_record):
    """每个新连接建立时执行 PRAGMA，提升 SQLite 并发健壮性。

    - journal_mode=WAL：读写并发，避免写操作阻塞读（默认 rollback journal 写时锁读）。
    - busy_timeout=30000：写锁等待 30s，避免高并发时直接抛 "database is locked"。
    - synchronous=NORMAL：WAL 下安全性足够且显著降低 fsync 开销。
    """
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
    except Exception:
        # 单个连接失败不应中断整体，忽略
        pass


def get_engine():
    """延迟创建 engine，避免启动时 DB_PATH 尚未就绪

    使用 QueuePool 替代 SQLite 默认的 SingletonThreadPool，并将连接池放大，
    避免多后台任务并发时连接池耗尽；配合 WAL + busy_timeout 降低写锁冲突。
    """
    global _engine
    if _engine is None:
        db_path = _ensure_data_dir()
        _engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
        event.listen(_engine, "connect", _apply_sqlite_pragmas)
    return _engine


def get_session_local():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _SessionLocal


def _migrate_add_columns():
    """为已有表添加缺失的新列（兼容旧数据库）"""
    from sqlalchemy import inspect, text
    engine = get_engine()
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table_name, table in Base.metadata.tables.items():
            if not inspector.has_table(table_name):
                continue
            existing_cols = {c['name'] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    col_type = col.type.compile(engine.dialect)
                    default_val = "NULL"
                    if col.default and hasattr(col.default, 'arg') and col.default.arg is not None:
                        arg = col.default.arg
                        if isinstance(arg, bool):
                            default_val = "0" if not arg else "1"
                        elif isinstance(arg, (int, float)):
                            default_val = str(arg)
                        elif isinstance(arg, str):
                            escaped = arg.replace("'", "''")
                            default_val = f"'{escaped}'"
                        else:
                            default_val = "NULL"
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} DEFAULT {default_val}"
                    conn.execute(text(sql))
                    print(f"[DB Migration] Added column: {table_name}.{col.name}")


def init_db():
    """创建所有表"""
    Base.metadata.create_all(get_engine())
    _migrate_add_columns()


def get_db():
    """FastAPI 依赖：每个请求一个独立 session"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_status(key: str, default: str = "") -> str:
    """读取机器人状态"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        row = db.query(BotStatus).filter(BotStatus.key == key).first()
        return row.value if row else default
    finally:
        db.close()


def set_status(key: str, value: str):
    """写入机器人状态"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        row = db.query(BotStatus).filter(BotStatus.key == key).first()
        if row:
            row.value = value
            row.updated_at = datetime.now()
        else:
            row = BotStatus(key=key, value=value)
            db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------- 启动时把异常中断的任务标记为 interrupted ----------
def mark_interrupted_jobs_on_startup():
    """启动时把 status=running 的任务标记为 interrupted（参考 agents.md 8.5）"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        running_jobs = db.query(BackgroundJob).filter(BackgroundJob.status == "running").all()
        for job in running_jobs:
            job.status = "interrupted"
            job.finished_at = datetime.now()
            job.error_message = "服务重启时被中断"
        db.commit()
        if running_jobs:
            print(f"[startup] 标记 {len(running_jobs)} 个未完成任务为 interrupted")
    except Exception as e:
        db.rollback()
        print(f"[startup] mark_interrupted_jobs 失败: {e}")
    finally:
        db.close()


import os  # noqa: E402  (放在末尾避免循环引用)


def _ensure_data_dir():
    """确保数据库所在目录存在"""
    db_path = settings.db_path
    # 相对路径归一化到 backend 目录下
    if not os.path.isabs(db_path):
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(backend_dir, db_path)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    return db_path


# 启动时确保目录存在
_ensure_data_dir()
