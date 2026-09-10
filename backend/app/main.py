"""FastAPI 主应用

对应 agents.md 第 3.1 节架构。
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db, get_session_local, mark_interrupted_jobs_on_startup
from app.jobs import recover_interrupted_jobs
from app.auth import ensure_default_admin
from app.scheduler import start_scheduler, stop_scheduler
from app.skill_store import seed_skills_if_needed


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动与关闭钩子"""
    # ---------- 启动 ----------
    # 1. 初始化数据库
    init_db()

    # 2. 创建默认管理员
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        ensure_default_admin(db)
    finally:
        db.close()

    # 3. 标记异常中断的任务
    mark_interrupted_jobs_on_startup()

    # 3.5 重跑上一轮被中断的后台任务（带 payload 的），避免需求永久停留在 pending
    recover_interrupted_jobs()

    # 3.6 初始化模块 Skill（用现有硬编码常量播种 4 个 active 版本；失败不影响现有逻辑）
    seed_skills_if_needed()

    # 4. 启动定时调度器
    start_scheduler()

    # 5. 确保日志目录存在
    for sub in ["system", "login", "audit", "tapd"]:
        os.makedirs(os.path.join(settings.log_dir, sub), exist_ok=True)

    print(f"[startup] {settings.bot_name} 已启动，监听 {settings.host}:{settings.port}")

    yield

    # ---------- 关闭 ----------
    stop_scheduler()
    print("[shutdown] 服务已停止")


app = FastAPI(
    title=settings.bot_name,
    description="TAPD 需求智能处理 Agent",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS（开发期允许前端 dev server 跨域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 全局异常处理 ----------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"内部错误: {str(exc)}"},
    )


# ---------- 注册路由 ----------
from app.routers import common, user_requirements, prd, classification, automation, users, audit_logs, skills  # noqa: E402

app.include_router(common.router)
app.include_router(user_requirements.router)
app.include_router(prd.router)
app.include_router(classification.router)
app.include_router(automation.router)
app.include_router(users.router)
app.include_router(audit_logs.router)
app.include_router(skills.router)


# ---------- 静态文件托管（前端构建产物） ----------
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static_dist")
if os.path.exists(_static_dir):
    # 先挂载 /assets 静态资源（带 hash 的 JS/CSS，可长期缓存）
    _assets_dir = os.path.join(_static_dir, "assets")
    if os.path.exists(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    # SPA 回退：所有非 /api 路径都返回 index.html，由 Vue Router 处理路由
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """SPA 路由回退：非 API 请求先尝试静态文件，找不到就返回 index.html"""
        # 排除 API 路径
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="API not found")
        # 尝试返回静态文件
        file_path = os.path.join(_static_dir, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        # 回退到 index.html
        index_path = os.path.join(_static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="index.html not found")

    print(f"[startup] 静态文件托管目录: {_static_dir}")
else:
    print(f"[startup] 静态目录不存在（{ _static_dir }），仅 API 模式")


@app.get("/api")
async def api_root():
    return {"name": settings.bot_name, "version": "1.0.0", "docs": "/docs"}
