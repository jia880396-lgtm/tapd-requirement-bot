"""定时任务调度器

参考 agents.md：定时 + 手动触发都支持，默认每 30 分钟自动拉取并打分。
同时支持分类机器人的定时批量处理。
"""
import asyncio
import os
import time
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import get_session_local, mark_interrupted_jobs_on_startup, get_status, set_status


_scheduler: BackgroundScheduler = None
_SCHEDULER_LOCK_PATH = None


def _scheduler_lock_path() -> str:
    global _SCHEDULER_LOCK_PATH
    if _SCHEDULER_LOCK_PATH is None:
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _SCHEDULER_LOCK_PATH = os.path.join(backend_dir, ".scheduler.lock")
    return _SCHEDULER_LOCK_PATH


def _acquire_scheduler_lock() -> bool:
    """跨进程单实例锁：成功返回 True，被其它进程持有则返回 False（不抛异常）。

    通过 O_EXCL 原子创建锁文件实现；超过 2 小时的锁视为陈旧自动接管。
    """
    try:
        path = _scheduler_lock_path()
        if os.path.exists(path):
            try:
                if time.time() - os.path.getmtime(path) > 7200:
                    os.remove(path)
            except OSError:
                pass
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        # 失败开放：锁异常不阻止调度器启动
        return True


def _release_scheduler_lock():
    try:
        path = _scheduler_lock_path()
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def start_scheduler():
    """启动后台调度器

    说明：
    - 用户需求处理定时任务：默认启动
    - 分类机器人定时任务：默认不启动，需用户在界面手动开启
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    # 跨进程单实例锁：避免多 worker / 多进程重复启动调度器导致重复拉取与重复打分
    if not _acquire_scheduler_lock():
        print("[scheduler] 检测到其它进程已持有调度器锁，跳过启动（避免重复自动化）")
        return None

    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    interval = settings.schedule_interval_minutes
    # 自动流程默认全部关闭：调度器只检查已由用户明确开启的个人流程。
    # 不再在服务启动时默认执行管理员全量需求处理。
    from app.routers.automation import run_user_automation_cycle
    _scheduler.add_job(
        run_user_automation_cycle,
        "interval",
        minutes=interval,
        id="user_automation_cycle",
        replace_existing=True,
        max_instances=1,   # 同一时刻只允许一个周期在跑，防止重叠
        coalesce=True,      # 错过多个触发点时合并为一次
    )

    # 模块技能定时复盘（Phase 4）：默认关闭，需管理员在设置页开启
    if settings.skill_auto_review_enabled:
        review_hours = settings.skill_auto_review_interval_hours
        _scheduler.add_job(
            _scheduled_skill_review,
            "interval",
            hours=max(1, review_hours),
            id="skill_auto_review",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        print(f"[scheduler] 已启用模块技能定时复盘，每 {review_hours} 小时一次")
    else:
        print("[scheduler] 模块技能定时复盘未启用（SKILL_AUTO_REVIEW_ENABLED=false）")

    _scheduler.start()
    set_status("scheduler_active", "true")
    set_status("schedule_interval", f"{interval}分钟")
    set_status("classification_scheduler_active", "false")
    print(f"[scheduler] 已启动，每 {interval} 分钟检查一次用户自主开启的自动流程")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    _release_scheduler_lock()
    set_status("scheduler_active", "false")


def reschedule_user_automation():
    """配置中的间隔变更后，实时更新用户自动流程检查频率。"""
    global _scheduler
    if _scheduler is None:
        return
    from app.routers.automation import run_user_automation_cycle
    interval = settings.schedule_interval_minutes
    _scheduler.add_job(
        run_user_automation_cycle,
        "interval",
        minutes=interval,
        id="user_automation_cycle",
        replace_existing=True,
    )
    set_status("schedule_interval", f"{interval}分钟")


def _scheduled_fetch_and_score():
    """定时任务：管理员全量自动拉取需求并打分

    以 admin 身份执行全量拉取 + 重复识别 + 可靠性打分的完整流程。
    操作员无法触发定时全量任务，只能通过页面手动拉取自己名下的需求。
    """
    print(f"[scheduler] {datetime.now()} 管理员全量自动拉取需求并打分开始")
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        from app.tapd_client import tapd_client
        from app.database import UserRequirementJob, BackgroundJob
        from app.jobs import create_background_job, run_async_task
        from app.routers.user_requirements import _run_fetch_process

        ws_id = settings.tapd_workspace_ids.split(",")[0].strip()
        stories = asyncio.run(tapd_client.get_stories(
            workspace_id=ws_id,
            limit=settings.batch_size,
            status=settings.story_status_filter or None,
        ))
        print(f"[scheduler] 拉取到 {len(stories)} 条需求")

        if not stories:
            print("[scheduler] 未拉取到需求，跳过处理")
            return

        # 写入数据库（upsert），收集新增记录 ID
        new_record_ids: list[int] = []
        new_count = 0
        update_count = 0
        for item in stories:
            s = tapd_client.extract_fields(item)
            story_id = s.get("story_id")
            if not story_id:
                continue

            user_req_text = s.get("user_requirement") or s.get("description", "")
            from datetime import datetime as _dt
            tapd_created = None
            created_str = s.get("created")
            if created_str:
                try:
                    tapd_created = _dt.strptime(str(created_str), "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    pass
            owner_str = ";".join(s.get("owner", [])) if s.get("owner") else ""

            existing = db.query(UserRequirementJob).filter(
                UserRequirementJob.story_id == story_id,
                UserRequirementJob.workspace_id == ws_id,
            ).first()

            if existing:
                existing.title = s.get("title", "")
                existing.description = user_req_text
                existing.tenant_version = s.get("tenant_version", "")
                existing.priority = s.get("priority_custom", "")
                existing.creator = s.get("creator", "")
                existing.owner = owner_str
                if tapd_created:
                    existing.tapd_created = tapd_created
                existing.updated_at = _dt.now()
                update_count += 1
            else:
                rec = UserRequirementJob(
                    story_id=story_id,
                    workspace_id=ws_id,
                    title=s.get("title", ""),
                    description=user_req_text,
                    tenant_version=s.get("tenant_version", ""),
                    priority=s.get("priority_custom", ""),
                    creator=s.get("creator", ""),
                    owner=owner_str,
                    status="pending",
                    created_by="scheduler",
                    created_at=_dt.now(),
                    updated_at=_dt.now(),
                    tapd_created=tapd_created,
                )
                db.add(rec)
                db.flush()
                new_count += 1
                new_record_ids.append(rec.id)

        db.commit()
        print(f"[scheduler] 新增 {new_count} 条，更新 {update_count} 条")

        # 触发后台处理任务（重复识别 → 打分）
        if new_record_ids:
            bg_job = create_background_job(
                db, job_type="fetch_process",
                total=len(new_record_ids), created_by="scheduler",
            )
            _run_fetch_process(bg_job.job_id, new_record_ids)
            print(f"[scheduler] 已启动后台处理任务: {bg_job.job_id}，共 {len(new_record_ids)} 条")
        else:
            print("[scheduler] 无新增需求，跳过处理")
    except Exception as e:
        print(f"[scheduler] 定时任务异常: {e}")
    finally:
        db.close()


def _scheduled_classification():
    """定时任务：自动批量分类需求"""
    print(f"[scheduler] {datetime.now()} 分类机器人定时任务开始")
    try:
        from app.classifier import process_batch, _is_api_key_configured
        if not _is_api_key_configured():
            print("[scheduler] DeepSeek API Key 未配置，跳过分类定时任务")
            return

        # 检查是否已有分类任务在运行
        state = get_status("bot_state", "idle")
        if state == "running":
            print("[scheduler] 分类机器人正在运行中，跳过本次")
            return

        # 创建后台任务
        from app.jobs import create_background_job
        SessionLocal = get_session_local()
        db = SessionLocal()
        try:
            job = create_background_job(db, "classification", total=0, created_by="scheduler")
            job_id = job.job_id
        finally:
            db.close()

        # 在后台线程运行
        from app.jobs import run_async_task
        coro = process_batch(job_id=job_id, created_by="scheduler")
        run_async_task(job_id, coro)
        print(f"[scheduler] 分类任务已启动: {job_id}")
    except Exception as e:
        print(f"[scheduler] 分类定时任务异常: {e}")
        set_status("bot_state", "error")
        set_status("last_error", str(e)[:500])


def _scheduled_skill_review():
    """定时任务（Phase 4）：逐模块运行复盘流程（产出草稿 + 写复盘日志，不自动激活）。"""
    print(f"[scheduler] {datetime.now()} 模块技能定时复盘开始")
    try:
        from app.skill_engine import run_periodic_review
        from app.skill_store import MODULE_KEYS
        for module_key in MODULE_KEYS:
            try:
                result = asyncio.run(run_periodic_review(module_key, created_by="scheduler"))
                print(f"[scheduler] 复盘 {module_key}: {result.get('status')} "
                      f"(新增误判 {result.get('new_case_count')})")
            except Exception as e:
                print(f"[scheduler] 复盘 {module_key} 异常: {e}")
    except Exception as e:
        print(f"[scheduler] 模块技能定时复盘异常: {e}")
