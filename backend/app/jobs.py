"""后台任务管理

对应 agents.md 8.5 节：
- 用 BackgroundJob 表统一记录所有任务
- 启动时调用 mark_interrupted_jobs_on_startup() 把异常中断的任务标记为 interrupted
- 前端用轮询（setInterval 每 2 秒）查询任务进度
"""
import uuid
import json
import asyncio
import threading
from datetime import datetime
from typing import Optional, Callable, Any

from sqlalchemy.orm import Session

from app.database import get_session_local, BackgroundJob, ProcessLog


# 全局任务注册表：job_id -> asyncio.Task
_RUNNING_TASKS: dict = {}


def generate_job_id(job_type: str) -> str:
    """生成任务 ID"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{job_type}_{timestamp}_{short_uuid}"


def create_background_job(
    db: Session,
    job_type: str,
    total: int = 0,
    created_by: str = "system",
    payload: Optional[dict] = None,
) -> BackgroundJob:
    """在数据库中创建一条后台任务记录

    payload: 可序列化的任务恢复参数（如 {"record_ids": [...], "user_id": 1}），
    供服务重启后重跑被中断的任务。
    """
    job = BackgroundJob(
        job_id=generate_job_id(job_type),
        job_type=job_type,
        status="running",
        total=total,
        processed=0,
        succeeded=0,
        failed=0,
        payload=json.dumps(payload, ensure_ascii=False) if payload else None,
        started_at=datetime.now(),
        created_by=created_by,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_background_job(
    db: Session,
    job_id: str,
    *,
    status: Optional[str] = None,
    total: Optional[int] = None,
    processed: Optional[int] = None,
    succeeded: Optional[int] = None,
    failed: Optional[int] = None,
    result: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """更新后台任务进度"""
    job = db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
    if not job:
        return
    if status is not None:
        job.status = status
    if total is not None:
        job.total = total
    if processed is not None:
        job.processed = processed
    if succeeded is not None:
        job.succeeded = succeeded
    if failed is not None:
        job.failed = failed
    if result is not None:
        job.result = result
    if error_message is not None:
        job.error_message = error_message
    if status in ("completed", "failed", "interrupted"):
        job.finished_at = datetime.now()
    db.commit()


def append_process_log(
    db: Session,
    job_id: str,
    job_type: str,
    message: str,
    story_id: Optional[str] = None,
    level: str = "info",
) -> None:
    """追加处理日志（前端日志流展示）"""
    log = ProcessLog(
        job_id=job_id,
        job_type=job_type,
        story_id=story_id or "",
        level=level,
        message=message,
    )
    db.add(log)
    db.commit()


def run_async_task(
    job_id: str,
    coro: asyncio.coroutines,
) -> None:
    """在后台线程中运行 asyncio 任务

    用于在 FastAPI 同步端点中启动后台任务。
    """
    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            err_msg = f"{e}\n{tb}"
            print(f"[background] 任务 {job_id} 异常: {err_msg}")
            # 标记任务失败
            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                update_background_job(
                    db, job_id,
                    status="failed",
                    error_message=err_msg,
                )
            finally:
                db.close()
        finally:
            loop.close()
            _RUNNING_TASKS.pop(job_id, None)

    t = threading.Thread(target=_runner, daemon=True)
    _RUNNING_TASKS[job_id] = t
    t.start()


def _job_interrupted(job_id: str) -> bool:
    """检查任务是否被用户标记为中断（供并发任务中途退出判断）。"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        job = db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
        return bool(job and job.status == "interrupted")
    finally:
        db.close()


async def run_concurrent_record_tasks(
    job_id: str,
    record_ids: list,
    worker,
    job_type: str = "user_requirement",
    concurrency: int = 4,
    log_db=None,
    on_progress=None,
):
    """并发执行逐条独立任务（如打分）。

    设计要点（避免 SQLite / SQLAlchemy 会话并发问题）：
    - 每条任务使用独立 DB 会话（SessionLocal），互不干扰；
    - 进度更新（on_progress / append_process_log 写 log_db）仅由主协程顺序调用，
      不会出现多个协程同时写同一个会话。

    Args:
        job_id: 后台任务 ID
        record_ids: 待处理的记录 ID 列表
        worker: async callable(record_id, session) -> None，处理单条记录
        job_type: 日志类型
        concurrency: 并发度（默认 4，避免触发 DeepSeek 限流）
        log_db: 用于写处理日志的会话（由主协程持有）
        on_progress: callable(success, fail)，每完成一条调用一次以更新进度
    Returns:
        {"ok": int, "fail": int}
    """
    if not record_ids:
        return {"ok": 0, "fail": 0}

    sem = asyncio.Semaphore(concurrency)
    stats = {"ok": 0, "fail": 0}

    async def _one(rid):
        async with sem:
            # 任务进行中允许被用户停止：未开始的记录直接跳过
            if _job_interrupted(job_id):
                return (rid, False, "interrupted")
            SessionLocal = get_session_local()
            sdb = SessionLocal()
            try:
                await worker(rid, sdb)
                return (rid, True, None)
            except Exception as e:
                return (rid, False, str(e)[:500])
            finally:
                sdb.close()

    for coro in asyncio.as_completed([_one(r) for r in record_ids]):
        rid, ok, err = await coro
        if ok:
            stats["ok"] += 1
        else:
            stats["fail"] += 1
            if log_db is not None:
                append_process_log(
                    log_db, job_id, job_type,
                    f"记录 ID={rid} 处理失败：{err}", level="error",
                )
        if on_progress is not None:
            on_progress(stats["ok"], stats["fail"])
    return stats


def stop_background_job(job_id: str) -> bool:
    """停止后台任务（仅 admin 可调用）

    注意：Python 线程无法强制 kill，这里只是标记为 interrupted，
    任务内部应主动检查 status 并退出。
    """
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        update_background_job(db, job_id, status="interrupted", error_message="用户手动停止")
        return True
    except Exception:
        return False
    finally:
        db.close()


def recover_interrupted_jobs():
    """服务启动时重跑上一轮被中断（running→interrupted）的后台任务。

    仅重跑带有 payload（含待处理 record_ids）的任务，避免无谓重跑或卡死。
    无 payload 的旧中断任务会被标记为 failed 并给出说明，不再静默滞留为 pending。
    """
    SessionLocal = get_session_local()
    db = SessionLocal()
    recovered = 0
    failed = 0
    try:
        interrupted = db.query(BackgroundJob).filter(BackgroundJob.status == "interrupted").all()
        if not interrupted:
            return
        print(f"[recovery] 发现 {len(interrupted)} 个中断任务，开始尝试恢复")
        for job in interrupted:
            payload = None
            if job.payload:
                try:
                    payload = json.loads(job.payload)
                except Exception:
                    payload = None
            record_ids = (payload or {}).get("record_ids") or []
            user_id = (payload or {}).get("user_id") if payload else None

            if not record_ids:
                job.status = "failed"
                job.error_message = "任务在重启前被中断，且缺少可恢复的 record_ids，已置为失败（可手动重新触发）"
                failed += 1
                continue

            # 重置任务状态，准备重跑
            job.status = "running"
            job.finished_at = None
            job.error_message = None
            job.processed = 0
            job.succeeded = 0
            job.failed = 0
            db.commit()

            job_type = job.job_type
            try:
                if job_type == "fetch_process":
                    from app.routers.user_requirements import _run_fetch_process
                    _run_fetch_process(job.job_id, record_ids, user_id=user_id)
                elif job_type == "user_requirement_score":
                    from app.routers.user_requirements import _run_score_records
                    _run_score_records(job.job_id, record_ids, user_id=user_id)
                elif job_type == "duplicate_check":
                    from app.routers.user_requirements import _run_duplicate_records
                    _run_duplicate_records(job.job_id, record_ids, user_id=user_id)
                elif job_type == "prd_analysis":
                    from app.routers.prd import _run_prd_records
                    _run_prd_records(job.job_id, record_ids, user_id=user_id)
                else:
                    job.status = "failed"
                    job.error_message = f"未知任务类型 {job_type}，无法自动恢复"
                    db.commit()
                    failed += 1
                    continue
                recovered += 1
            except Exception as e:
                job.status = "failed"
                job.error_message = f"恢复启动失败: {e}"
                db.commit()
                failed += 1
        if recovered or failed:
            print(f"[recovery] 恢复完成：已重跑 {recovered} 个，无法恢复 {failed} 个")
    except Exception as e:
        print(f"[recovery] 恢复过程异常: {e}")
    finally:
        db.close()
