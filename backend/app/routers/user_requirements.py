"""API 路由：用户需求处理

对应 agents.md 6.1 节
"""
import json
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, UserRequirementJob, BackgroundJob, ProcessLog, WritebackLog
from app.auth import get_current_user, require_admin_dep, User
from app.config import settings
from app.user_settings import get_active_setting
from app.tapd_client import tapd_client, TAPDClientError
from app.llm_client import LLMClientError
from app.jobs import (
    create_background_job, update_background_job, append_process_log, run_async_task,
)
from app.reliability_scorer import score_single_requirement
from app.duplicate_detector import detect_duplicate_for_record
from app.quality_rules import generate_concise_reason
from app.prompts import (
    RELIABILITY_COMMENT_TEMPLATE, DUPLICATE_COMMENT_TEMPLATE,
)
from app.audit import log_audit


router = APIRouter(prefix="/api/user-requirements", tags=["user-requirements"])


def _build_reliability_comment(record: UserRequirementJob) -> str:
    """根据 reliability_detail 和 supplemental_questions 构建可靠性评论内容"""
    detail = json.loads(record.reliability_detail or "{}")
    # 兼容新旧存储结构
    if "dimensions" in detail:
        reason = detail.get("reason", "")
    else:
        dims = detail
        comments = [v.get("comment", "") for v in dims.values() if isinstance(v, dict) and v.get("comment")]
        reason = "；".join(comments) if comments else "需求评估未达标，请补充关键信息"
    if not reason:
        reason = "需求评估未达标，请补充关键信息"
    questions = json.loads(record.supplemental_questions or "[]")
    if questions:
        questions_block = (
            "\n为了更准确地理解和推进该需求，还需要补充以下信息：\n"
            + "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
            + "\n"
        )
    else:
        questions_block = ""

    # 截图建议：需求本身没有截图（且描述中无已识别的截图内容）时提示补充
    try:
        has_image = bool(json.loads(record.image_paths or "[]"))
    except Exception:
        has_image = False
    if not has_image and "【需求截图内容" not in (record.description or ""):
        extra_tip = "\n💡 另外，如能附上相关操作截图（当前页面、报错提示等），可帮助更快定位问题。\n"
    else:
        extra_tip = ""

    return RELIABILITY_COMMENT_TEMPLATE.format(
        score=record.reliability_score if record.reliability_score is not None else "--",
        reason=reason,
        questions_block=questions_block,
        extra_tip=extra_tip,
    )


def _parse_tapd_datetime(dt_str: str) -> Optional[datetime]:
    """解析 TAPD 返回的时间字符串（如 '2026-08-10 15:30:00'）"""
    if not dt_str:
        return None
    try:
        return datetime.strptime(str(dt_str), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


# ---------- 数据模型 ----------
class FetchRequest(BaseModel):
    workspace_id: Optional[str] = None
    status: Optional[str] = None


class ScoreRequest(BaseModel):
    record_ids: list[int]
    workspace_id: Optional[str] = None


class DuplicateCheckRequest(BaseModel):
    record_ids: list[int]


class ForceAdvanceRequest(BaseModel):
    comment: Optional[str] = None


# ---------- GET /fetch：拉取需求 ----------
@router.get("/fetch")
async def fetch_stories(
    workspace_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    owner: Optional[str] = Query(None, description="处理人账号过滤，多人用分号分隔"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """从 TAPD 拉取用户提交的需求

    立即创建后台任务并返回 job_id（<100ms），TAPD 拉取 + DB 入库 + 重复识别 + 打分
    全部在后台异步执行。前端通过轮询 job_id 获取实时进度。
    权限：管理员可拉取全量需求（不传 owner）；操作员必须通过 owner 参数拉取自己名下的需求。
    """
    # 权限校验：操作员不传 owner 时自动填充为自己的处理人名，管理员可不传 owner 拉取全量
    user_display = user.display_name or user.username
    if user.role != "admin":
        if not owner:
            owner = user_display
        elif owner != user_display:
            raise HTTPException(status_code=403, detail="操作员仅能拉取自己名下的需求")

    from app.user_settings import get_active_setting
    ws_id = workspace_id or get_active_setting("tapd_workspace_ids").split(",")[0].strip()
    status_filter = status or get_active_setting("story_status_filter")

    # TAPD API 的 owner 参数需要账号名（如 "徐玥玥01"），而非显示名（如 "徐玥玥"）
    tapd_owner = owner
    if tapd_owner:
        from app.owner_mapping_cls import get_tapd_account_by_display_name
        tapd_owner = get_tapd_account_by_display_name(tapd_owner)

    # 立即创建后台任务（<100ms），前端拿到 job_id 后开始轮询进度
    bg_job = create_background_job(
        db, job_type="fetch_process",
        total=0, created_by=user.username,
        payload={
            "ws_id": ws_id, "status_filter": status_filter,
            "tapd_owner": tapd_owner, "limit": limit,
            "user_id": user.id, "user_role": user.role,
        },
    )
    job_id = bg_job.job_id

    # 写入初始进度（fetching 阶段），前端轮询时立即可见
    init_state = {
        "phase": "fetching",
        "fetch_total": 0, "fetch_new": 0, "fetch_updated": 0,
        "duplicate_total": 0, "duplicate_processed": 0,
        "duplicate_succeeded": 0, "duplicate_failed": 0,
        "score_total": 0, "score_processed": 0,
        "score_succeeded": 0, "score_failed": 0,
    }
    update_background_job(db, job_id, result=json.dumps(init_state))

    # 启动完整后台流程（TAPD 拉取 → DB 入库 → 重复识别 → 打分）
    _run_full_fetch_process(job_id, ws_id, status_filter, tapd_owner, limit, user.id, user.role)

    return {
        "workspace_id": ws_id,
        "status_filter": status_filter,
        "owner": owner,
        "job_id": job_id,
    }


def _run_full_fetch_process(
    job_id: str, ws_id: str, status_filter: str,
    tapd_owner: str, limit: int, user_id: int, user_role: str,
) -> None:
    """完整后台流程：TAPD 拉取 → 批量 DB 入库 → 重复识别 → 打分

    相比旧版 _run_fetch_process，本函数把 TAPD 拉取和 DB 入库也放入后台执行，
    使 API 端点可以立即返回 job_id。前端通过轮询看到 fetching → duplicate → score 三阶段进度。
    """

    async def _full_run():
        from app.database import get_session_local
        SessionLocal = get_session_local()
        task_db = SessionLocal()
        try:
            if user_id is not None:
                from app.user_settings import activate_user_business_settings
                activate_user_business_settings(task_db, user_id)

            # ---- 阶段0：TAPD 拉取 ----
            try:
                stories = await tapd_client.get_stories(
                    workspace_id=ws_id, limit=limit,
                    status=status_filter or None,
                    owner=tapd_owner or None,
                )
            except Exception as e:
                update_background_job(task_db, job_id, status="failed",
                                      error_message=f"TAPD 拉取失败: {e}")
                append_process_log(task_db, job_id, "user_requirement",
                                   f"TAPD 拉取失败: {e}", level="error")
                return

            # ---- 阶段1：批量 DB 入库（1 次 SELECT + 批量更新/插入） ----
            parsed_items = []
            story_ids = []
            for item in stories:
                s = tapd_client.extract_fields(item)
                sid = s.get("story_id")
                if not sid:
                    continue
                story_ids.append(sid)
                parsed_items.append(s)

            # 批量查询已有记录（1 次 SELECT 替代 N 次）
            existing_map = {}
            if story_ids:
                existing_rows = task_db.query(UserRequirementJob).filter(
                    UserRequirementJob.story_id.in_(story_ids),
                    UserRequirementJob.workspace_id == ws_id,
                ).all()
                existing_map = {r.story_id: r for r in existing_rows}

            new_count = 0
            update_count = 0
            new_record_ids = []
            pending_existing_ids = []
            now = datetime.now()

            for s in parsed_items:
                sid = s.get("story_id")
                user_req_text = s.get("user_requirement") or s.get("description", "")
                tapd_created = _parse_tapd_datetime(s.get("created"))
                owner_str = ";".join(s.get("owner", [])) if s.get("owner") else ""
                image_paths_json = json.dumps(s.get("image_urls", []), ensure_ascii=False)

                existing = existing_map.get(sid)
                if existing:
                    existing.title = s.get("title", "")
                    existing.description = user_req_text
                    existing.image_paths = image_paths_json
                    existing.tenant_version = s.get("tenant_version", "")
                    existing.priority = s.get("priority_custom", "")
                    existing.creator = s.get("creator", "")
                    existing.owner = owner_str
                    if tapd_created:
                        existing.tapd_created = tapd_created
                    existing.updated_at = now
                    if (user_role != "admin"
                            and existing.status == "pending"
                            and existing.reliability_score is None
                            and existing.id not in pending_existing_ids):
                        pending_existing_ids.append(existing.id)
                    update_count += 1
                else:
                    rec = UserRequirementJob(
                        story_id=sid, workspace_id=ws_id,
                        title=s.get("title", ""),
                        description=user_req_text,
                        image_paths=image_paths_json,
                        tenant_version=s.get("tenant_version", ""),
                        priority=s.get("priority_custom", ""),
                        creator=s.get("creator", ""),
                        owner=owner_str,
                        status="pending",
                        created_by="",
                        created_at=now, updated_at=now,
                        tapd_created=tapd_created,
                    )
                    task_db.add(rec)
                    task_db.flush()
                    new_count += 1
                    new_record_ids.append(rec.id)

            task_db.commit()

            # 更新进度：fetching 完成
            all_to_process = new_record_ids + pending_existing_ids
            state = {
                "phase": "fetching",
                "fetch_total": len(stories), "fetch_new": new_count, "fetch_updated": update_count,
                "duplicate_total": 0, "duplicate_processed": 0,
                "duplicate_succeeded": 0, "duplicate_failed": 0,
                "score_total": 0, "score_processed": 0,
                "score_succeeded": 0, "score_failed": 0,
            }
            update_background_job(task_db, job_id,
                                  total=len(all_to_process), processed=0,
                                  succeeded=0, failed=0,
                                  result=json.dumps(state))
            append_process_log(task_db, job_id, "user_requirement",
                               f"TAPD 拉取完成：共 {len(stories)} 条，新增 {new_count}，更新 {update_count}，待处理 {len(all_to_process)}",
                               level="success")

            if not all_to_process:
                state["phase"] = "done"
                update_background_job(task_db, job_id, status="completed",
                                      result=json.dumps(state))
                return

            # ---- 后续阶段：重复识别 + 打分 ----
            await _run_duplicate_and_score(job_id, all_to_process, user_id, task_db, state)

        except Exception as e:
            import traceback
            update_background_job(task_db, job_id, status="failed",
                                  error_message=f"{e}\n{traceback.format_exc()}"[:1000])
        finally:
            task_db.close()

    run_async_task(job_id, _full_run())


async def _run_full_fetch_process_coro(
    job_id: str, ws_id: str, status_filter: str,
    tapd_owner: str, limit: int, user_id: int, user_role: str,
) -> None:
    """可直接 await 的版本（供 automation 自动触发使用，避免嵌套事件循环）。"""
    from app.database import get_session_local
    SessionLocal = get_session_local()
    task_db = SessionLocal()
    try:
        if user_id is not None:
            from app.user_settings import activate_user_business_settings
            activate_user_business_settings(task_db, user_id)

        # ---- 阶段0：TAPD 拉取 ----
        try:
            stories = await tapd_client.get_stories(
                workspace_id=ws_id, limit=limit,
                status=status_filter or None,
                owner=tapd_owner or None,
            )
        except Exception as e:
            update_background_job(task_db, job_id, status="failed",
                                  error_message=f"TAPD 拉取失败: {e}")
            append_process_log(task_db, job_id, "user_requirement",
                               f"TAPD 拉取失败: {e}", level="error")
            return

        # ---- 阶段1：批量 DB 入库 ----
        parsed_items = []
        story_ids = []
        for item in stories:
            s = tapd_client.extract_fields(item)
            sid = s.get("story_id")
            if not sid:
                continue
            story_ids.append(sid)
            parsed_items.append(s)

        existing_map = {}
        if story_ids:
            existing_rows = task_db.query(UserRequirementJob).filter(
                UserRequirementJob.story_id.in_(story_ids),
                UserRequirementJob.workspace_id == ws_id,
            ).all()
            existing_map = {r.story_id: r for r in existing_rows}

        new_count = 0
        update_count = 0
        new_record_ids = []
        pending_existing_ids = []
        now = datetime.now()

        for s in parsed_items:
            sid = s.get("story_id")
            user_req_text = s.get("user_requirement") or s.get("description", "")
            tapd_created = _parse_tapd_datetime(s.get("created"))
            owner_str = ";".join(s.get("owner", [])) if s.get("owner") else ""
            image_paths_json = json.dumps(s.get("image_urls", []), ensure_ascii=False)

            existing = existing_map.get(sid)
            if existing:
                existing.title = s.get("title", "")
                existing.description = user_req_text
                existing.image_paths = image_paths_json
                existing.tenant_version = s.get("tenant_version", "")
                existing.priority = s.get("priority_custom", "")
                existing.creator = s.get("creator", "")
                existing.owner = owner_str
                if tapd_created:
                    existing.tapd_created = tapd_created
                existing.updated_at = now
                if (user_role != "admin"
                        and existing.status == "pending"
                        and existing.reliability_score is None
                        and existing.id not in pending_existing_ids):
                    pending_existing_ids.append(existing.id)
                update_count += 1
            else:
                rec = UserRequirementJob(
                    story_id=sid, workspace_id=ws_id,
                    title=s.get("title", ""),
                    description=user_req_text,
                    image_paths=image_paths_json,
                    tenant_version=s.get("tenant_version", ""),
                    priority=s.get("priority_custom", ""),
                    creator=s.get("creator", ""),
                    owner=owner_str,
                    status="pending",
                    created_by="",
                    created_at=now, updated_at=now,
                    tapd_created=tapd_created,
                )
                task_db.add(rec)
                task_db.flush()
                new_count += 1
                new_record_ids.append(rec.id)

        task_db.commit()

        all_to_process = new_record_ids + pending_existing_ids
        state = {
            "phase": "fetching",
            "fetch_total": len(stories), "fetch_new": new_count, "fetch_updated": update_count,
            "duplicate_total": 0, "duplicate_processed": 0,
            "duplicate_succeeded": 0, "duplicate_failed": 0,
            "score_total": 0, "score_processed": 0,
            "score_succeeded": 0, "score_failed": 0,
        }
        update_background_job(task_db, job_id,
                              total=len(all_to_process), processed=0,
                              succeeded=0, failed=0,
                              result=json.dumps(state))
        append_process_log(task_db, job_id, "user_requirement",
                           f"TAPD 拉取完成：共 {len(stories)} 条，新增 {new_count}，更新 {update_count}，待处理 {len(all_to_process)}",
                           level="success")

        if not all_to_process:
            state["phase"] = "done"
            update_background_job(task_db, job_id, status="completed",
                                  result=json.dumps(state))
            return

        await _run_duplicate_and_score(job_id, all_to_process, user_id, task_db, state)

    except Exception as e:
        import traceback
        update_background_job(task_db, job_id, status="failed",
                              error_message=f"{e}\n{traceback.format_exc()}"[:1000])
    finally:
        task_db.close()


def _run_fetch_process(job_id: str, record_ids: list, user_id=None) -> None:
    """向后兼容：供 recover_interrupted_jobs 和 scheduler 等既有调用路径使用。"""
    from app.database import get_session_local

    async def _run():
        SessionLocal = get_session_local()
        task_db = SessionLocal()
        try:
            if user_id is not None:
                from app.user_settings import activate_user_business_settings
                activate_user_business_settings(task_db, user_id)

            state = {
                "phase": "duplicate",
                "fetch_total": 0, "fetch_new": 0, "fetch_updated": 0,
                "duplicate_total": len(record_ids), "duplicate_processed": 0,
                "duplicate_succeeded": 0, "duplicate_failed": 0,
                "score_total": 0, "score_processed": 0,
                "score_succeeded": 0, "score_failed": 0,
            }
            update_background_job(task_db, job_id, total=len(record_ids),
                                  processed=0, succeeded=0, failed=0,
                                  result=json.dumps(state))
            await _run_duplicate_and_score(job_id, record_ids, user_id, task_db, state)
        except Exception as e:
            import traceback
            update_background_job(task_db, job_id, status="failed",
                                  error_message=f"{e}\n{traceback.format_exc()}"[:1000])
        finally:
            task_db.close()

    run_async_task(job_id, _run())


async def _run_duplicate_and_score(job_id, record_ids, user_id, task_db, state):
    """重复识别 + 打分核心逻辑（从原 _run_fetch_process 提取，供新旧路径复用）"""
    from app.reliability_scorer import score_single_requirement
    from app.jobs import run_concurrent_record_tasks

    # 本次待处理的记录
    new_records = task_db.query(UserRequirementJob) \
        .filter(UserRequirementJob.id.in_(record_ids)) \
        .all() if record_ids else []

    # 历史库：排除本次新增的记录
    new_story_ids = {r.story_id for r in new_records}
    from app.user_settings import get_active_setting
    history_limit = get_active_setting("duplicate_history_limit")
    try:
        history_limit = min(int(history_limit), 2000)
    except (TypeError, ValueError):
        history_limit = 500
    historical = task_db.query(UserRequirementJob) \
        .filter(~UserRequirementJob.story_id.in_(new_story_ids) if new_story_ids else True) \
        .order_by(
            UserRequirementJob.tapd_created.desc().nullslast(),
            UserRequirementJob.created_at.desc(),
        ) \
        .limit(history_limit) \
        .all()
    append_process_log(task_db, job_id, "user_requirement",
                       f"已加载历史需求 {len(historical)} 条作为对比库（已排除本次新增 {len(new_records)} 条）")

    # 按 TAPD 创建时间正序处理（早提交的优先保留）
    new_records_sorted = sorted(
        new_records,
        key=lambda r: (r.tapd_created or r.created_at),
    )

    total = len(new_records_sorted)
    state["phase"] = "duplicate"
    state["duplicate_total"] = total
    update_background_job(task_db, job_id, total=total, processed=0,
                          succeeded=0, failed=0, result=json.dumps(state))

    # 阶段0：图片识别增强
    from app.vision_client import vision_configured, enrich_record_with_images
    if vision_configured():
        append_process_log(task_db, job_id, "user_requirement",
                           f"开始截图识别增强（共 {total} 条，每条最多 3 张）")
        for rec in new_records_sorted:
            try:
                changed = await enrich_record_with_images(task_db, rec)
                if changed:
                    append_process_log(task_db, job_id, "user_requirement",
                                       f"需求 {rec.story_id} 截图识别完成，已并入需求文字",
                                       story_id=rec.story_id, level="info")
            except Exception as e:
                append_process_log(task_db, job_id, "user_requirement",
                                   f"记录 ID={rec.id} 截图增强失败：{e}", level="warning")
    else:
        append_process_log(task_db, job_id, "user_requirement",
                           "视觉模型未配置（VISION_API_KEY），跳过截图识别增强", level="info")

    # 阶段1：重复识别
    kept_records = []
    dup_success = 0
    dup_fail = 0
    non_duplicate_ids = []
    duplicate_ids = []

    for idx, rec in enumerate(new_records_sorted, 1):
        bg = task_db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
        if bg and bg.status == "interrupted":
            append_process_log(task_db, job_id, "user_requirement",
                               "任务被用户停止", level="warning")
            break

        compare_pool = historical + kept_records
        try:
            await detect_duplicate_for_record(task_db, job_id, rec.id, compare_pool)
            dup_success += 1

            rec = task_db.query(UserRequirementJob).filter(
                UserRequirementJob.id == rec.id).first()

            if rec and rec.is_duplicate:
                duplicate_ids.append(rec.id)
                append_process_log(task_db, job_id, "user_requirement",
                                   f"需求 {rec.story_id} 标记为重复（保留更早提交的需求）",
                                   story_id=rec.story_id, level="warning")
            else:
                kept_records.append(rec)
                non_duplicate_ids.append(rec.id)
        except Exception as e:
            dup_fail += 1
            append_process_log(task_db, job_id, "user_requirement",
                               f"记录 ID={rec.id} 重复识别失败：{e}", level="error")
            try:
                rec = task_db.query(UserRequirementJob).filter(
                    UserRequirementJob.id == rec.id).first()
                if rec:
                    rec.duplicate_detail = json.dumps(
                        {"error": f"重复识别失败: {e}", "needs_review": True},
                        ensure_ascii=False)
                    rec.status = "pending"
                    task_db.commit()
            except Exception:
                pass

        state["duplicate_processed"] = idx
        state["duplicate_succeeded"] = dup_success
        state["duplicate_failed"] = dup_fail
        update_background_job(task_db, job_id, processed=idx,
                              succeeded=dup_success, failed=dup_fail,
                              result=json.dumps(state))

    # 对重复需求写回默认 AI 打分和分类（不调用 LLM，直接写回 TAPD）
    if duplicate_ids:
        from app.config import settings as _settings
        from app.tapd_client import TAPDClient as _TAPDClient
        _tc = _TAPDClient()
        append_process_log(task_db, job_id, "user_requirement",
                           f"开始写回 {len(duplicate_ids)} 条重复需求的 AI打分和分类", level="info")
        for dup_rid in duplicate_ids:
            try:
                dup_rec = task_db.query(UserRequirementJob).filter(UserRequirementJob.id == dup_rid).first()
                if not dup_rec or not dup_rec.workspace_id or not dup_rec.story_id:
                    continue
                # AI 打分：0 分，理由"重复需求"
                dup_rec.reliability_score = 0
                dup_rec.ai_score_10 = 0
                dup_rec.ai_score_reason = "重复需求"
                dup_rec.reliability_detail = json.dumps({"reason": "重复需求，不计分"}, ensure_ascii=False)
                task_db.commit()
                await _tc.update_story_ai_score(
                    workspace_id=dup_rec.workspace_id,
                    story_id=dup_rec.story_id,
                    score_10=0,
                    reason="重复需求",
                )
                # AI 模块分类：标记为"重复需求"
                await _tc.update_story_custom_fields(
                    workspace_id=dup_rec.workspace_id,
                    story_id=dup_rec.story_id,
                    fields={_settings.custom_field_ai_module: "重复需求"},
                )
                append_process_log(task_db, job_id, "user_requirement",
                                   f"重复需求 {dup_rec.story_id} 已写回 AI打分(0) + 理由(重复需求) + 分类(重复需求)",
                                   story_id=dup_rec.story_id, level="info")
            except Exception as e:
                append_process_log(task_db, job_id, "user_requirement",
                                   f"重复需求 ID={dup_rid} 写回 TAPD 失败：{e}", level="warning")

    # 阶段2：打分（仅对非重复需求，并发提速）
    state["phase"] = "score"
    state["score_total"] = len(non_duplicate_ids)
    update_background_job(task_db, job_id, total=len(non_duplicate_ids),
                          processed=0, succeeded=0, failed=0,
                          result=json.dumps(state))

    async def _score_worker(rid, sdb):
        await score_single_requirement(sdb, job_id, rid)

    def _score_progress(ok, fail_count):
        state["score_processed"] = ok + fail_count
        state["score_succeeded"] = ok
        state["score_failed"] = fail_count
        update_background_job(task_db, job_id, processed=ok + fail_count,
                              succeeded=ok, failed=fail_count,
                              result=json.dumps(state))

    stats = await run_concurrent_record_tasks(
        job_id, non_duplicate_ids, _score_worker,
        job_type="user_requirement", concurrency=4,
        log_db=task_db, on_progress=_score_progress,
    )
    score_success = stats["ok"]
    score_fail = stats["fail"]

    # 阶段3：AI模块分类（仅对非重复需求，需 DeepSeek API Key）
    classify_success = 0
    classify_fail = 0
    from app.classifier import _is_api_key_configured, classify_single_record
    if _is_api_key_configured() and non_duplicate_ids:
        state["phase"] = "classify"
        state["classify_total"] = len(non_duplicate_ids)
        state["classify_processed"] = 0
        state["classify_succeeded"] = 0
        state["classify_failed"] = 0
        update_background_job(task_db, job_id, result=json.dumps(state))
        append_process_log(task_db, job_id, "user_requirement",
                           f"开始AI模块分类（共 {len(non_duplicate_ids)} 条）", level="info")

        for rid in non_duplicate_ids:
            bg = task_db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
            if bg and bg.status == "interrupted":
                append_process_log(task_db, job_id, "user_requirement",
                                   "任务被用户停止（分类阶段）", level="warning")
                break
            rec = task_db.query(UserRequirementJob).filter(UserRequirementJob.id == rid).first()
            if rec:
                try:
                    result = await classify_single_record(task_db, rec)
                    if result:
                        classify_success += 1
                    else:
                        classify_fail += 1
                except Exception as e:
                    classify_fail += 1
                    append_process_log(task_db, job_id, "user_requirement",
                                       f"记录 {rec.story_id} 分类失败：{e}", level="warning")

            state["classify_processed"] = classify_success + classify_fail
            state["classify_succeeded"] = classify_success
            state["classify_failed"] = classify_fail
            update_background_job(task_db, job_id,
                                  processed=classify_success + classify_fail,
                                  succeeded=classify_success,
                                  failed=classify_fail,
                                  result=json.dumps(state))
    else:
        if not _is_api_key_configured():
            append_process_log(task_db, job_id, "user_requirement",
                               "DeepSeek API Key 未配置，跳过AI模块分类", level="info")

    state["phase"] = "done"
    state["score_processed"] = len(non_duplicate_ids)
    state["score_succeeded"] = score_success
    state["score_failed"] = score_fail
    state["classify_succeeded"] = classify_success
    state["classify_failed"] = classify_fail
    update_background_job(task_db, job_id, status="completed",
                          result=json.dumps(state))
    append_process_log(task_db, job_id, "user_requirement",
                       f"组合任务完成：重复识别 {dup_success}/{total}，打分 {score_success}/{len(non_duplicate_ids)}，分类 {classify_success}/{len(non_duplicate_ids)}",
                       level="success")


# ---------- GET /list：本地已拉取的需求列表 ----------
@router.get("/list")
async def list_requirements(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    status: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    owner: Optional[str] = Query(None, description="处理人筛选"),
    max_score: Optional[float] = Query(None, description="分数上限筛选（如 60 表示只看低于60分的需求）"),
    min_score: Optional[float] = Query(None, description="分数下限筛选"),
    order_by: Optional[str] = Query(None, description="排序字段：score / created / tapd_created / updated（默认 tapd_created）"),
    order: Optional[str] = Query("desc", description="排序方向：asc / desc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取本地数据库中的需求列表（分页）

    注意：识别为重复的需求（is_duplicate=True）不在此页面显示，
    请到「重复需求处理」页面查看。
    权限：管理员可查看全部；操作员仅能查看自己名下（owner 字段包含自己显示名）的需求。
    """
    q = db.query(UserRequirementJob)

    # operator 只能看自己处理的需求（按 owner 字段过滤，而非 created_by）
    # 这样管理员拉取的数据，操作员也能看到自己名下的部分
    if user.role != "admin":
        user_display = user.display_name or user.username
        q = q.filter(UserRequirementJob.owner.like(f"%{user_display}%"))

    # 排除重复需求（重复需求只在「重复需求处理」页面显示）
    q = q.filter(UserRequirementJob.is_duplicate == False)  # noqa: E712

    if status:
        q = q.filter(UserRequirementJob.status == status)
    if keyword:
        q = q.filter(UserRequirementJob.title.like(f"%{keyword}%"))
    if owner:
        q = q.filter(UserRequirementJob.owner.like(f"%{owner}%"))
    if max_score is not None:
        # 低于 max_score 的需求（包含已打分但分数 < max_score 的记录）
        q = q.filter(
            UserRequirementJob.reliability_score.isnot(None),
            UserRequirementJob.reliability_score < max_score,
        )
    if min_score is not None:
        q = q.filter(
            UserRequirementJob.reliability_score.isnot(None),
            UserRequirementJob.reliability_score >= min_score,
        )

    total = q.count()
    # 排序：支持 score / created / tapd_created / updated，默认 tapd_created desc
    order_col_map = {
        "score": UserRequirementJob.reliability_score,
        "ai_score_10": UserRequirementJob.ai_score_10,
        "created": UserRequirementJob.created_at,
        "tapd_created": UserRequirementJob.tapd_created,
        "updated": UserRequirementJob.updated_at,
    }
    order_col = order_col_map.get(order_by, UserRequirementJob.tapd_created)
    if order == "asc":
        records = q.order_by(order_col.asc().nullslast(), UserRequirementJob.created_at.desc()) \
            .offset((page - 1) * page_size) \
            .limit(page_size) \
            .all()
    else:
        records = q.order_by(order_col.desc().nullslast(), UserRequirementJob.created_at.desc()) \
            .offset((page - 1) * page_size) \
            .limit(page_size) \
            .all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_requirement(r) for r in records],
    }


# ---------- POST /score：启动可靠性打分任务 ----------
@router.post("/score")
async def start_score(
    req: ScoreRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """启动可靠性打分任务（后台执行）"""
    if not req.record_ids:
        raise HTTPException(status_code=400, detail="请选择至少一条需求")

    bg_job = create_background_job(
        db, job_type="user_requirement_score",
        total=len(req.record_ids), created_by=user.username,
        payload={"record_ids": req.record_ids, "user_id": user.id},
    )
    _run_score_records(bg_job.job_id, req.record_ids, user.id)

    log_audit(db, "manual_trigger_score", user.username,
              target=bg_job.job_id, detail=f"{len(req.record_ids)} 条需求")

    return {"job_id": bg_job.job_id, "total": len(req.record_ids)}


def _run_score_records(job_id: str, record_ids: list[int], user_id: int | None = None) -> None:
    """可靠性打分后台执行体（手动打分 / 驳回重打 / 中断恢复共用）

    打分各条相互独立，使用有界并发提速（每条独立 DB 会话）。
    """
    from app.database import get_session_local
    from app.reliability_scorer import score_single_requirement
    from app.jobs import run_concurrent_record_tasks

    async def _run():
        SessionLocal = get_session_local()
        task_db = SessionLocal()
        try:
            if user_id is not None:
                from app.user_settings import activate_user_business_settings
                activate_user_business_settings(task_db, user_id)
            total = len(record_ids)
            update_background_job(task_db, job_id, total=total, processed=0,
                                  succeeded=0, failed=0)
            success = 0
            fail = 0

            async def worker(rid, sdb):
                await score_single_requirement(sdb, job_id, rid)

            def on_progress(ok, fail_count):
                nonlocal success, fail
                success, fail = ok, fail_count
                update_background_job(task_db, job_id, processed=ok + fail_count,
                                      succeeded=ok, failed=fail_count)

            stats = await run_concurrent_record_tasks(
                job_id, record_ids, worker,
                job_type="user_requirement", concurrency=4,
                log_db=task_db, on_progress=on_progress,
            )
            update_background_job(task_db, job_id, status="completed",
                                  result=json.dumps({"succeeded": stats["ok"], "failed": stats["fail"]}))
            append_process_log(task_db, job_id, "user_requirement",
                               f"打分完成：成功 {stats['ok']} 条，失败 {stats['fail']} 条",
                               level="success")
        finally:
            task_db.close()

    run_async_task(job_id, _run())


# ---------- POST /duplicate-check：启动重复识别 ----------
@router.post("/duplicate-check")
async def start_duplicate_check(
    req: DuplicateCheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """启动重复需求识别"""
    if not req.record_ids:
        raise HTTPException(status_code=400, detail="请选择至少一条需求")

    bg_job = create_background_job(
        db, job_type="duplicate_check",
        total=len(req.record_ids), created_by=user.username,
        payload={"record_ids": req.record_ids, "user_id": user.id},
    )
    _run_duplicate_records(bg_job.job_id, req.record_ids, user.id)

    log_audit(db, "manual_trigger_duplicate", user.username,
              target=bg_job.job_id, detail=f"{len(req.record_ids)} 条需求")

    return {"job_id": bg_job.job_id, "total": len(req.record_ids)}


def _run_duplicate_records(job_id: str, record_ids: list[int], user_id: int | None = None) -> None:
    """重复识别后台执行体（手动识别 / 中断恢复共用）"""
    from app.database import get_session_local
    from app.duplicate_detector import detect_duplicate_for_record
    from app.user_settings import get_active_setting

    async def _run():
        SessionLocal = get_session_local()
        task_db = SessionLocal()
        try:
            if user_id is not None:
                from app.user_settings import activate_user_business_settings
                activate_user_business_settings(task_db, user_id)
            # 先拉取历史需求库（最近 N 条，设防御性上限避免雪崩）
            history_limit = get_active_setting("duplicate_history_limit")
            try:
                history_limit = min(int(history_limit), 2000)
            except (TypeError, ValueError):
                history_limit = 500
            historical = task_db.query(UserRequirementJob) \
                .order_by(UserRequirementJob.created_at.desc()) \
                .limit(history_limit) \
                .all()
            append_process_log(task_db, job_id, "user_requirement",
                               f"已加载历史需求 {len(historical)} 条作为对比库")

            success_count = 0
            fail_count = 0
            for idx, rid in enumerate(record_ids, 1):
                bg = task_db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
                if bg and bg.status == "interrupted":
                    break
                try:
                    await detect_duplicate_for_record(task_db, job_id, rid, historical)
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    append_process_log(task_db, job_id, "user_requirement",
                                       f"记录 ID={rid} 重复识别失败：{e}", level="error")
                update_background_job(task_db, job_id, processed=idx,
                                      succeeded=success_count, failed=fail_count)
            update_background_job(task_db, job_id, status="completed",
                                  result=json.dumps({"succeeded": success_count, "failed": fail_count}))
        finally:
            task_db.close()

    run_async_task(job_id, _run())


# ---------- POST /{story_id}/write-comment：写回评论 ----------
@router.post("/{story_id}/write-comment")
async def write_comment(
    story_id: str,
    workspace_id: str = Query(None),
    action: str = Query("reliability_comment", pattern="^(reliability_comment|duplicate_comment|prd_suggestion)$"),
    dry_run: bool = Query(False, description="干跑模式：只生成评论内容不实际写回 TAPD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """写回补充问题评论到 TAPD"""
    ws_id = workspace_id or get_active_setting("tapd_workspace_ids").split(",")[0].strip()
    record = db.query(UserRequirementJob).filter(
        UserRequirementJob.story_id == story_id,
        UserRequirementJob.workspace_id == ws_id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="需求记录不存在")

    # 按类型生成评论内容
    if action == "reliability_comment":
        if not record.reliability_detail:
            raise HTTPException(status_code=400, detail="该需求尚未打分，无法生成评论")
        # 通过的需求不写回评论，只有未达标时才写回
        if (record.reliability_score or 0) >= get_active_setting("reliability_threshold"):
            raise HTTPException(status_code=400, detail="该需求已通过评估，无需写回评论")
        content = _build_reliability_comment(record)
    elif action == "duplicate_comment":
        if not record.is_duplicate:
            raise HTTPException(status_code=400, detail="该需求未标记为重复")
        dup_with = json.loads(record.duplicate_with or "[]")
        dup_detail = _safe_json(record.duplicate_detail) or []
        first_detail = dup_detail[0] if dup_detail else {}
        content = DUPLICATE_COMMENT_TEMPLATE.format(
            duplicate_list=", ".join(dup_with) or "无",
            similarity=record.similarity if record.similarity is not None else "未知",
            duplicate_type=first_detail.get("duplicate_type", "自动检测标记为重复"),
            reason=first_detail.get("reason", "自动检测标记为重复"),
        )
    else:
        raise HTTPException(status_code=400, detail="不支持的评论类型")

    # 干跑模式：只返回生成内容，不实际写回 TAPD
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "story_id": story_id,
            "action": action,
            "content": content,
            "content_length": len(content),
            "message": "干跑模式：评论已生成但未实际写回 TAPD",
        }

    # 调用 TAPD
    from app.database import WritebackLog
    try:
        result = await tapd_client.add_comment(
            workspace_id=ws_id,
            entry_type="story",
            entry_id=story_id,
            description=content,
            author=None,
        )
        record.comment_written = True
        db.commit()

        db.add(WritebackLog(
            story_id=story_id, workspace_id=ws_id,
            action=action, content=content,
            success=True, created_at=datetime.now(),
        ))
        db.commit()

        log_audit(db, "write_comment", user.username, target=story_id, detail=action)
        return {"success": True, "result": result}
    except TAPDClientError as e:
        db.add(WritebackLog(
            story_id=story_id, workspace_id=ws_id,
            action=action, content=content,
            success=False, error_message=str(e),
            created_at=datetime.now(),
        ))
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.add(WritebackLog(
            story_id=story_id, workspace_id=ws_id,
            action=action, content=content,
            success=False, error_message=str(e),
            created_at=datetime.now(),
        ))
        db.commit()
        raise HTTPException(status_code=500, detail=f"评论写回失败: {e}")


# ---------- GET /{story_id}/comment-preview：预览 AI 生成的评论内容 ----------
@router.get("/{story_id}/comment-preview")
async def preview_comment(
    story_id: str,
    workspace_id: str = Query(None),
    action: str = Query("reliability_comment", pattern="^(reliability_comment|duplicate_comment)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """预览 AI 生成的待写回评论内容（不实际写回 TAPD）

    仅对未达标需求（score < 60）返回 reliability_comment 内容；
    通过的需求返回 400。
    """
    ws_id = workspace_id or get_active_setting("tapd_workspace_ids").split(",")[0].strip()
    record = db.query(UserRequirementJob).filter(
        UserRequirementJob.story_id == story_id,
        UserRequirementJob.workspace_id == ws_id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="需求记录不存在")

    if action == "reliability_comment":
        if not record.reliability_detail:
            raise HTTPException(status_code=400, detail="该需求尚未打分，无法生成评论")
        if (record.reliability_score or 0) >= get_active_setting("reliability_threshold"):
            raise HTTPException(status_code=400, detail="该需求已通过评估，无需写回评论")
        content = _build_reliability_comment(record)
    elif action == "duplicate_comment":
        if not record.is_duplicate:
            raise HTTPException(status_code=400, detail="该需求未标记为重复")
        dup_with = json.loads(record.duplicate_with or "[]")
        dup_detail = _safe_json(record.duplicate_detail) or []
        first_detail = dup_detail[0] if dup_detail else {}
        content = DUPLICATE_COMMENT_TEMPLATE.format(
            duplicate_list=", ".join(dup_with) or "无",
            similarity=record.similarity if record.similarity is not None else "未知",
            duplicate_type=first_detail.get("duplicate_type", "自动检测标记为重复"),
            reason=first_detail.get("reason", "自动检测标记为重复"),
        )
    else:
        raise HTTPException(status_code=400, detail="不支持的评论类型")

    return {
        "success": True,
        "story_id": story_id,
        "action": action,
        "content": content,
        "content_length": len(content),
        "reliability_score": record.reliability_score,
    }


# ---------- POST /record/{record_id}/manual-score：人工打分（1-10 分） ----------
class ManualScoreRequest(BaseModel):
    score: float
    comment: str = ""


@router.post("/record/{record_id}/manual-score")
async def manual_score(
    record_id: int,
    req: ManualScoreRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """人工复核打分：1-10 分（0.5 步进）。

    AI 打分保持 0-100 内部体系不变；人工用 1-10 粗粒度修正（人的分辨力上限约 20 档），
    存储原值（与 AI 分对比时 ×10），并记录打分人与备注，供 AI 打分校准分析。
    """
    if req.score < 1 or req.score > 10:
        raise HTTPException(status_code=400, detail="人工打分须在 1-10 分之间")
    score = round(req.score * 2) / 2  # 对齐 0.5 步进

    record = db.query(UserRequirementJob).filter(UserRequirementJob.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="需求记录不存在")

    record.manual_score = score
    record.manual_score_comment = (req.comment or "").strip()[:500]
    record.manual_score_by = user.display_name or user.username
    record.manual_score_at = datetime.now()
    db.commit()

    log_audit(db, "manual_score", user.username, target=record.story_id,
              detail=f"人工打分 {score}/10（AI {record.reliability_score}）")
    return {"status": "success", "data": {
        "record_id": record_id,
        "manual_score": score,
        "ai_score": record.reliability_score,
        "manual_score_by": record.manual_score_by,
        "manual_score_at": record.manual_score_at.isoformat() if record.manual_score_at else None,
    }}


# ---------- POST /{story_id}/write-comment-custom：写回人工修改后的评论 ----------
class CustomCommentRequest(BaseModel):
    content: str
    workspace_id: Optional[str] = None
    action: str = "reliability_comment"


@router.post("/{story_id}/write-comment-custom")
async def write_comment_custom(
    story_id: str,
    req: CustomCommentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """写回人工修改后的评论内容到 TAPD

    与 write-comment 不同：本接口直接使用前端传入的 content 写回 TAPD，
    支持"先预览 → 人工修改 → 写回"的工作流。
    """
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=400, detail="评论内容不能为空")

    ws_id = req.workspace_id or get_active_setting("tapd_workspace_ids").split(",")[0].strip()
    record = db.query(UserRequirementJob).filter(
        UserRequirementJob.story_id == story_id,
        UserRequirementJob.workspace_id == ws_id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="需求记录不存在")

    # 通过的需求不允许写回评论
    if req.action == "reliability_comment" and (record.reliability_score or 0) >= settings.reliability_threshold:
        raise HTTPException(status_code=400, detail="该需求已通过评估，无需写回评论")

    content = req.content.strip()
    from app.database import WritebackLog
    try:
        result = await tapd_client.add_comment(
            workspace_id=ws_id,
            entry_type="story",
            entry_id=story_id,
            description=content,
            author=None,
        )
        record.comment_written = True
        db.commit()

        db.add(WritebackLog(
            story_id=story_id, workspace_id=ws_id,
            action=req.action, content=content,
            success=True, created_at=datetime.now(),
        ))
        db.commit()

        log_audit(db, "write_comment_custom", user.username, target=story_id,
                  detail=f"{req.action}（人工修改后写回）")
        return {"success": True, "result": result, "content_length": len(content)}
    except TAPDClientError as e:
        db.add(WritebackLog(
            story_id=story_id, workspace_id=ws_id,
            action=req.action, content=content,
            success=False, error_message=str(e),
            created_at=datetime.now(),
        ))
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.add(WritebackLog(
            story_id=story_id, workspace_id=ws_id,
            action=req.action, content=content,
            success=False, error_message=str(e),
            created_at=datetime.now(),
        ))
        db.commit()
        raise HTTPException(status_code=500, detail=f"评论写回失败: {e}")


# ---------- POST /{story_id}/force-advance：强行提交至下一步（admin） ----------
@router.post("/{story_id}/force-advance")
async def force_advance(
    story_id: str,
    req: ForceAdvanceRequest,
    workspace_id: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_dep),
):
    """产品经理强行将选定需求标记为已确认（绕过自动流程，仅 admin）

    说明：不修改 TAPD 需求状态，只在本地数据库标记为 confirmed。
    TAPD 那边的状态保持"需求待评估"不变，由产品经理后续在 TAPD 中手动流转。
    """
    ws_id = workspace_id or get_active_setting("tapd_workspace_ids").split(",")[0].strip()
    record = db.query(UserRequirementJob).filter(
        UserRequirementJob.story_id == story_id,
        UserRequirementJob.workspace_id == ws_id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="需求记录不存在")

    # 只更新本地记录状态，不调用 TAPD 接口
    record.status = "confirmed"
    db.commit()

    log_audit(db, "force_advance", user.username, target=story_id,
              detail=f"备注: {req.comment}" if req.comment else "无备注")
    return {"success": True, "message": "已标记为已确认", "story_id": story_id}


class ChangeTapdStatusRequest(BaseModel):
    record_ids: list[int]
    workspace_id: Optional[str] = None


# ---------- POST /change-tapd-status：更改 TAPD 需求状态为「产品设计中」 ----------
@router.post("/change-tapd-status")
async def change_tapd_status(
    req: ChangeTapdStatusRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量更改 TAPD 需求状态为「产品设计中」

    选中需求后点击按钮，调用 TAPD 接口将状态改为 status_21（产品设计中），
    并同步更新本地记录状态为 confirmed。
    """
    if not req.record_ids:
        raise HTTPException(status_code=400, detail="请选择至少一条需求")

    target_status = get_active_setting("story_status_product_designing")
    if not target_status:
        raise HTTPException(status_code=500, detail="未配置 STORY_STATUS_PRODUCT_DESIGNING")

    ws_id = req.workspace_id or get_active_setting("tapd_workspace_ids").split(",")[0].strip()

    records = db.query(UserRequirementJob).filter(
        UserRequirementJob.id.in_(req.record_ids)
    ).all()
    if not records:
        raise HTTPException(status_code=404, detail="未找到对应需求记录")

    succeeded = []
    failed = []
    for rec in records:
        try:
            await tapd_client.update_story_status(
                workspace_id=rec.workspace_id or ws_id,
                story_id=rec.story_id,
                status=target_status,
            )
            rec.status = "confirmed"
            succeeded.append(rec.story_id)
        except TAPDClientError as e:
            failed.append({"story_id": rec.story_id, "error": str(e)})
        except Exception as e:
            failed.append({"story_id": rec.story_id, "error": f"TAPD 调用失败: {e}"})

    db.commit()
    log_audit(db, "change_tapd_status", user.username, target=ws_id,
              detail=f"目标状态=产品设计中({target_status})，成功 {len(succeeded)} 条，失败 {len(failed)} 条")

    return {
        "success": len(failed) == 0,
        "message": f"成功更改 {len(succeeded)} 条需求状态为「产品设计中」"
                   + (f"，失败 {len(failed)} 条" if failed else ""),
        "succeeded": succeeded,
        "failed": failed,
    }


# ---------- POST /mark-duplicate：手动标记需求为重复 ----------
@router.post("/mark-duplicate")
async def mark_duplicate(
    req: ChangeTapdStatusRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动将选中需求标记为重复

    标记后需求从「用户需求处理」页面移除，转入「重复需求处理」页面，
    由用户在重复需求页面确认重复（写回 TAPD 状态）或确认不重复（发回打分）。
    """
    if not req.record_ids:
        raise HTTPException(status_code=400, detail="请选择至少一条需求")

    records = db.query(UserRequirementJob).filter(
        UserRequirementJob.id.in_(req.record_ids)
    ).all()
    if not records:
        raise HTTPException(status_code=404, detail="未找到对应需求记录")

    count = 0
    for rec in records:
        rec.is_duplicate = True
        rec.status = "duplicate"
        # 手动标记无 top3 重复详情，清空避免误导
        if not rec.duplicate_detail:
            rec.duplicate_detail = json.dumps([], ensure_ascii=False)
        count += 1

    db.commit()
    log_audit(db, "mark_duplicate", user.username, target=",".join(str(r.story_id) for r in records),
              detail=f"手动标记 {count} 条需求为重复")

    return {
        "success": True,
        "message": f"已将 {count} 条需求标记为重复，请到「重复需求处理」页面处理",
        "count": count,
    }


# ---------- GET /logs：处理日志 ----------
@router.get("/logs")
async def get_logs(
    job_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取处理日志（分页）"""
    from app.database import ProcessLog
    q = db.query(ProcessLog)
    if job_id:
        q = q.filter(ProcessLog.job_id == job_id)
    total = q.count()
    logs = q.order_by(ProcessLog.created_at.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [{
            "id": l.id, "job_id": l.job_id, "job_type": l.job_type,
            "story_id": l.story_id, "level": l.level, "message": l.message,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        } for l in logs],
    }


# ---------- GET /{story_id}/timeline：需求处理时间线 ----------
@router.get("/{story_id}/timeline")
async def get_timeline(
    story_id: str,
    workspace_id: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取需求的完整处理时间线

    合并 ProcessLog、WritebackLog 和字段变更时间，按时间正序返回。
    """
    ws_id = workspace_id or get_active_setting("tapd_workspace_ids").split(",")[0].strip()
    record = db.query(UserRequirementJob).filter(
        UserRequirementJob.story_id == story_id,
        UserRequirementJob.workspace_id == ws_id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="需求记录不存在")

    events = []

    # 1. 关键节点（基于记录字段）
    if record.tapd_created:
        events.append({
            "time": record.tapd_created.strftime("%Y-%m-%d %H:%M:%S"),
            "type": "created",
            "title": "需求提交到 TAPD",
            "desc": f"提交人: {record.creator or '-'}",
            "level": "info",
        })
    if record.created_at:
        events.append({
            "time": record.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "type": "fetched",
            "title": "拉取到本系统",
            "desc": f"操作人: {record.created_by or '-'}",
            "level": "info",
        })
    if record.reliability_score is not None:
        score = record.reliability_score
        is_pass = score >= get_active_setting("reliability_threshold")
        events.append({
            "time": record.updated_at.strftime("%Y-%m-%d %H:%M:%S") if record.updated_at else "",
            "type": "scored",
            "title": f"AI 可靠性打分: {score} 分 ({'通过' if is_pass else '未达标'})",
            "desc": f"阈值: {get_active_setting('reliability_threshold')}",
            "level": "success" if is_pass else "warning",
        })
    if record.is_duplicate:
        events.append({
            "time": record.updated_at.strftime("%Y-%m-%d %H:%M:%S") if record.updated_at else "",
            "type": "duplicate",
            "title": "标记为重复需求",
            "desc": f"相似度: {record.similarity or '未知'}",
            "level": "warning",
        })
    if record.comment_written:
        events.append({
            "time": record.updated_at.strftime("%Y-%m-%d %H:%M:%S") if record.updated_at else "",
            "type": "comment",
            "title": "评论已写回 TAPD",
            "desc": "AI 初步评估评论已写回",
            "level": "success",
        })

    # 2. ProcessLog（处理过程中的详细日志）
    process_logs = db.query(ProcessLog).filter(
        ProcessLog.story_id == story_id
    ).order_by(ProcessLog.created_at.asc()).all()
    for log in process_logs:
        # 跳过审计日志（避免与关键节点重复）
        if log.job_type == "audit":
            continue
        events.append({
            "time": log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
            "type": "log",
            "title": log.message or "",
            "desc": f"任务: {log.job_id}",
            "level": log.level or "info",
        })

    # 3. WritebackLog（评论写回日志）
    writeback_logs = db.query(WritebackLog).filter(
        WritebackLog.story_id == story_id
    ).order_by(WritebackLog.created_at.asc()).all()
    for wb in writeback_logs:
        status_text = "成功" if wb.success else f"失败: {wb.error_message or ''}"
        events.append({
            "time": wb.created_at.strftime("%Y-%m-%d %H:%M:%S") if wb.created_at else "",
            "type": "writeback",
            "title": f"评论写回 {status_text}",
            "desc": f"类型: {wb.action}, 长度: {len(wb.content or '')}",
            "level": "success" if wb.success else "error",
        })

    # 4. 审计日志（手动操作记录）
    audit_logs = db.query(ProcessLog).filter(
        ProcessLog.job_type == "audit",
        ProcessLog.story_id == story_id,
    ).order_by(ProcessLog.created_at.asc()).all()
    for log in audit_logs:
        events.append({
            "time": log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
            "type": "audit",
            "title": log.message or "",
            "desc": "",
            "level": log.level or "info",
        })

    # 按时间排序（正序）
    events.sort(key=lambda e: e["time"])

    return {
        "story_id": story_id,
        "events": events,
        "total": len(events),
    }


# ---------- GET /statistics：统计数据 ----------


# ---------- 批量写回AI打分到TAPD ----------
@router.post("/batch-writeback-score")
async def batch_writeback_score(
    story_ids: list[str] = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_dep),
):
    """将已打分需求的AI分数（10分制）批量写回TAPD"""
    from app.tapd_client import TAPDClient
    from app.quality_rules import convert_score_100_to_10
    
    tapd_client = TAPDClient()
    results = {"success": 0, "failed": 0, "details": []}
    
    for sid in story_ids:
        record = db.query(UserRequirementJob).filter(
            UserRequirementJob.story_id == sid
        ).first()
        if not record or record.reliability_score is None:
            results["failed"] += 1
            results["details"].append({"story_id": sid, "status": "skip", "reason": "未打分"})
            continue
        
        try:
            score_10 = convert_score_100_to_10(record.reliability_score)
            import json as _json
            try:
                detail_obj = _json.loads(record.reliability_detail or "{}")
            except Exception:
                detail_obj = {}
            flags = (detail_obj.get("precheck") or {}).get("flags") or []
            evidence = (detail_obj.get("precheck") or {}).get("evidence") or []
            # custom_field_27：仅<6分才写回补充问题
            try:
                questions = _json.loads(record.supplemental_questions or "[]")
            except Exception:
                questions = []
            if score_10 >= 6:
                supplement_text = ""
            else:
                supplement_text = "\n".join([f"{i}：{q}" for i, q in enumerate(questions, 1)]) if questions else ""
            await tapd_client.update_story_ai_score(
                workspace_id=record.workspace_id or "",
                story_id=record.story_id,
                score_10=score_10,
                reason=supplement_text,
            )
            record.ai_score_10 = score_10
            record.ai_score_reason = supplement_text
            results["success"] += 1
            results["details"].append({"story_id": sid, "status": "ok", "score": score_10, "reason": supplement_text[:30]})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"story_id": sid, "status": "error", "reason": str(e)[:100]})
    
    db.commit()
    return results


@router.post("/batch-writeback-reason")
async def batch_writeback_reason(
    story_ids: list[str] = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_dep),
):
    """将AI打分理由单独批量写回TAPD（custom_field_27）"""
    from app.tapd_client import TAPDClient

    tapd_client = TAPDClient()
    results = {"success": 0, "failed": 0, "details": []}

    for sid in story_ids:
        record = db.query(UserRequirementJob).filter(
            UserRequirementJob.story_id == sid
        ).first()
        if not record or record.reliability_score is None:
            results["failed"] += 1
            results["details"].append({"story_id": sid, "status": "skip", "reason": "未打分"})
            continue

        # 仅<6分才写回补充问题，>=6分清空
        import json as _json
        try:
            questions = _json.loads(record.supplemental_questions or "[]")
        except Exception:
            questions = []
        score_10 = convert_score_100_to_10(record.reliability_score) if record.reliability_score is not None else 0
        if score_10 >= 6:
            supplement_text = ""
        else:
            supplement_text = "\n".join([f"{i}：{q}" for i, q in enumerate(questions, 1)]) if questions else ""

        try:
            await tapd_client.update_story_custom_fields(
                workspace_id=record.workspace_id or "",
                story_id=record.story_id,
                fields={settings.custom_field_ai_score_reason: supplement_text},
            )
            record.ai_score_reason = supplement_text
            results["success"] += 1
            results["details"].append({"story_id": sid, "status": "ok", "reason": supplement_text[:30]})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"story_id": sid, "status": "error", "reason": str(e)[:100]})

    db.commit()
    return results


@router.post("/batch-writeback-classification")
async def batch_writeback_classification(
    story_ids: list[str] = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_dep),
):
    """将AI模块分类批量写回TAPD（custom_field_32）"""
    from app.tapd_client import TAPDClient
    from app.database import Classification

    tapd_client = TAPDClient()
    results = {"success": 0, "failed": 0, "details": []}

    for sid in story_ids:
        record = db.query(UserRequirementJob).filter(
            UserRequirementJob.story_id == sid
        ).first()
        if not record:
            results["failed"] += 1
            results["details"].append({"story_id": sid, "status": "skip", "reason": "未找到记录"})
            continue

        cls = db.query(Classification).filter(Classification.story_id == sid).first()
        if not cls or not cls.category_l1:
            results["failed"] += 1
            results["details"].append({"story_id": sid, "status": "skip", "reason": "未分类"})
            continue

        module_value = f"{cls.category_l1}-{cls.category_l2}" if cls.category_l2 else cls.category_l1
        try:
            await tapd_client.update_story_custom_fields(
                workspace_id=record.workspace_id or "",
                story_id=record.story_id,
                fields={settings.custom_field_ai_module: module_value},
            )
            results["success"] += 1
            results["details"].append({"story_id": sid, "status": "ok", "value": module_value})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"story_id": sid, "status": "error", "reason": str(e)[:100]})

    return results


@router.post("/batch-writeback-duplicate")
async def batch_writeback_duplicate(
    story_ids: list[str] = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_dep),
):
    """将重复需求状态批量写回TAPD（custom_field_31）"""
    from app.tapd_client import TAPDClient
    import json as _json

    tapd_client = TAPDClient()
    results = {"success": 0, "failed": 0, "details": []}

    for sid in story_ids:
        record = db.query(UserRequirementJob).filter(
            UserRequirementJob.story_id == sid
        ).first()
        if not record:
            results["failed"] += 1
            results["details"].append({"story_id": sid, "status": "skip", "reason": "未找到记录"})
            continue

        # 构造写回值
        try:
            dup_with = _json.loads(record.duplicate_with) if record.duplicate_with else []
        except Exception:
            dup_with = []

        if record.is_duplicate and dup_with:
            dup_value = "是;" + ",".join(str(d) for d in dup_with)
        elif record.is_duplicate:
            dup_value = "是"
        else:
            dup_value = "否"

        try:
            await tapd_client.update_story_custom_fields(
                workspace_id=record.workspace_id or "",
                story_id=record.story_id,
                fields={settings.custom_field_duplicate: dup_value},
            )
            results["success"] += 1
            results["details"].append({"story_id": sid, "status": "ok", "value": dup_value})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"story_id": sid, "status": "error", "reason": str(e)[:100]})

    return results


@router.get("/statistics")
async def get_statistics(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取统计数据（可视化用）"""
    q = db.query(UserRequirementJob)
    if user.role != "admin":
        user_display = user.display_name or user.username
        q = q.filter(UserRequirementJob.owner.like(f"%{user_display}%"))

    all_records = q.all()
    total = len(all_records)
    pending = sum(1 for r in all_records if r.status == "pending")
    scored = sum(1 for r in all_records if r.status == "scored")
    duplicate = sum(1 for r in all_records if r.status == "duplicate")
    confirmed = sum(1 for r in all_records if r.status == "confirmed")
    rejected = sum(1 for r in all_records if r.status == "rejected")

    scored_records = [r for r in all_records if r.reliability_score is not None]
    avg_score = sum(r.reliability_score for r in scored_records) / max(len(scored_records), 1)
    # 全局合格数（score >= 阈值）
    threshold = get_active_setting("reliability_threshold")
    pass_count = sum(1 for r in scored_records if r.reliability_score >= threshold)

    # 未达标且未写回评论的需求数（待处理提醒用）
    fail_pending = sum(
        1 for r in all_records
        if r.reliability_score is not None
        and r.reliability_score < threshold
        and not r.is_duplicate
        and not r.comment_written
    )

    # 分数分布（每 20 分一档）
    distribution = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
    for r in scored_records:
        s = r.reliability_score or 0
        if s < 20:
            distribution["0-20"] += 1
        elif s < 40:
            distribution["20-40"] += 1
        elif s < 60:
            distribution["40-60"] += 1
        elif s < 80:
            distribution["60-80"] += 1
        else:
            distribution["80-100"] += 1

    # 按处理人维度统计（owner 可能是分号分隔多人，拆分到个人）
    owner_stats: dict[str, dict] = {}
    for r in all_records:
        owner_field = (r.owner or "").strip()
        if not owner_field:
            owners = ["未分配"]
        else:
            owners = [o.strip() for o in owner_field.split(";") if o.strip()] or ["未分配"]
        for o in owners:
            if o not in owner_stats:
                owner_stats[o] = {
                    "owner": o,
                    "total": 0, "pending": 0, "scored": 0, "duplicate": 0,
                    "confirmed": 0, "rejected": 0,
                    "score_sum": 0.0, "score_count": 0,
                    "pass_count": 0, "fail_pending": 0,
                }
            st = owner_stats[o]
            st["total"] += 1
            st[r.status or "pending"] = st.get(r.status or "pending", 0) + 1
            if r.reliability_score is not None:
                st["score_sum"] += r.reliability_score
                st["score_count"] += 1
                if r.reliability_score >= threshold:
                    st["pass_count"] += 1
                if r.reliability_score < threshold and not r.is_duplicate and not r.comment_written:
                    st["fail_pending"] += 1

    by_owner = []
    for o, st in owner_stats.items():
        by_owner.append({
            "owner": st["owner"],
            "total": st["total"],
            "pending": st["pending"],
            "scored": st["scored"],
            "duplicate": st["duplicate"],
            "confirmed": st["confirmed"],
            "rejected": st["rejected"],
            "avg_score": round(st["score_sum"] / st["score_count"], 1) if st["score_count"] else None,
            "pass_rate": round(st["pass_count"] / st["score_count"] * 100, 1) if st["score_count"] else None,
            "fail_pending": st["fail_pending"],
        })
    # 按待处理数降序
    by_owner.sort(key=lambda x: (x["pending"], x["total"]), reverse=True)

    return {
        "total": total,
        "pending": pending,
        "scored": scored,
        "duplicate": duplicate,
        "confirmed": confirmed,
        "rejected": rejected,
        "avg_score": round(avg_score, 1),
        "pass_count": pass_count,
        "score_distribution": distribution,
        "fail_pending": fail_pending,
        "by_owner": by_owner,
    }


# ---------- GET /jobs/{job_id}/result：任务结果 ----------
@router.get("/jobs/{job_id}/result")
async def get_job_result(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取打分任务结果"""
    job = db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "status": job.status,
        "total": job.total,
        "processed": job.processed,
        "succeeded": job.succeeded,
        "failed": job.failed,
        "result": json.loads(job.result) if job.result else None,
        "error_message": job.error_message,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


# ---------- 内部工具 ----------
def _tapd_story_url(workspace_id: str, story_id: str) -> str:
    """生成 TAPD 需求详情页 URL"""
    if not workspace_id or not story_id:
        return ""
    return f"https://www.tapd.cn/{workspace_id}/prong/stories/view/{story_id}"


def _safe_json(val):
    """安全解析 JSON 字段，解析失败时返回空列表避免接口报错"""
    if not val:
        return None
    try:
        return json.loads(val)
    except (ValueError, TypeError):
        return []


def _serialize_requirement(r: UserRequirementJob) -> dict:
    # 构造重复需求 TAPD 写回值
    dup_ids = _safe_json(r.duplicate_with) or []
    if r.is_duplicate and dup_ids:
        duplicate_tapd_value = "是;" + ",".join(str(sid) for sid in dup_ids)
    elif r.is_duplicate:
        duplicate_tapd_value = "是"
    else:
        duplicate_tapd_value = "否"

    # 查询 AI 模块分类
    ai_module_value = ""
    try:
        from app.database import Classification
        from app.database import get_session_local
        _db = get_session_local()()
        cls = _db.query(Classification).filter(
            Classification.story_id == r.story_id
        ).first()
        if cls:
            if cls.category_l2:
                ai_module_value = f"{cls.category_l1}-{cls.category_l2}"
            else:
                ai_module_value = cls.category_l1 or ""
        _db.close()
    except Exception:
        pass

    return {
        "id": r.id,
        "story_id": r.story_id,
        "workspace_id": r.workspace_id,
        "title": r.title,
        "description": r.description,
        "tenant_version": r.tenant_version,
        "priority": r.priority,
        "creator": r.creator,
        "owner": r.owner,
        "reliability_score": r.reliability_score,
        "ai_score_10": r.ai_score_10,
        "ai_score_reason": r.ai_score_reason,
        "reliability_detail": _safe_json(r.reliability_detail),
        "manual_score": r.manual_score,
        "manual_score_comment": r.manual_score_comment,
        "manual_score_by": r.manual_score_by,
        "manual_score_at": r.manual_score_at.isoformat() if r.manual_score_at else None,
        "is_duplicate": r.is_duplicate,
        "duplicate_with": _safe_json(r.duplicate_with),
        "duplicate_tapd_value": duplicate_tapd_value,
        "similarity": r.similarity,
        "duplicate_detail": _safe_json(r.duplicate_detail),
        "ai_module": ai_module_value,
        "supplemental_questions": _safe_json(r.supplemental_questions),
        "comment_written": r.comment_written,
        "status": r.status,
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "tapd_created": r.tapd_created.isoformat() if r.tapd_created else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "tapd_url": _tapd_story_url(r.workspace_id, r.story_id),
    }


# ---------- 重复需求管理路由 ----------


class DuplicateActionRequest(BaseModel):
    record_ids: list[int]


# ---------- GET /duplicate/list：重复需求列表 ----------
@router.get("/duplicate/list")
async def list_duplicate_requirements(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    keyword: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取识别为重复的需求列表（含 top3 重复需求详情）"""
    q = db.query(UserRequirementJob).filter(UserRequirementJob.is_duplicate == True)  # noqa: E712

    if user.role != "admin":
        user_display = user.display_name or user.username
        q = q.filter(UserRequirementJob.owner.like(f"%{user_display}%"))

    if keyword:
        q = q.filter(UserRequirementJob.title.like(f"%{keyword}%"))

    total = q.count()
    records = q.order_by(
        UserRequirementJob.tapd_created.desc().nullslast(),
        UserRequirementJob.created_at.desc(),
    ) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_requirement(r) for r in records],
    }


# ---------- POST /duplicate/confirm：确认重复，写回 TAPD 状态 ----------
@router.post("/duplicate/confirm")
async def confirm_duplicate(
    req: DuplicateActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量确认重复：将 TAPD 需求状态改为"重复需求"

    需要先在 .env 配置 STORY_STATUS_DUPLICATE（如 status_7）。
    """
    if not req.record_ids:
        raise HTTPException(status_code=400, detail="请选择至少一条需求")

    dup_status = get_active_setting("story_status_duplicate")
    if not dup_status:
        raise HTTPException(
            status_code=400,
            detail="未配置 STORY_STATUS_DUPLICATE，请在 .env 或系统设置中填入重复需求对应的 TAPD status 值（如 status_7）",
        )

    records = db.query(UserRequirementJob).filter(
        UserRequirementJob.id.in_(req.record_ids)
    ).all()
    if not records:
        raise HTTPException(status_code=404, detail="未找到对应需求记录")

    success_count = 0
    fail_count = 0
    errors = []
    for rec in records:
        try:
            await tapd_client.update_story_status(
                workspace_id=rec.workspace_id,
                story_id=rec.story_id,
                status=dup_status,
            )
            rec.status = "duplicate"
            rec.is_duplicate = True
            success_count += 1
        except TAPDClientError as e:
            fail_count += 1
            errors.append({"story_id": rec.story_id, "error": str(e)})
        except Exception as e:
            fail_count += 1
            errors.append({"story_id": rec.story_id, "error": f"TAPD 状态更新失败: {e}"})

    db.commit()
    log_audit(db, "confirm_duplicate", user.username,
              target=f"{len(req.record_ids)} 条",
              detail=f"成功 {success_count}，失败 {fail_count}")

    return {
        "success": fail_count == 0,
        "total": len(req.record_ids),
        "succeeded": success_count,
        "failed": fail_count,
        "errors": errors,
    }


# ---------- POST /duplicate/reject：确认不重复，发回打分 ----------
@router.post("/duplicate/reject")
async def reject_duplicate(
    req: DuplicateActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量确认不重复：清除重复标记，状态改回 pending，并触发打分任务"""
    if not req.record_ids:
        raise HTTPException(status_code=400, detail="请选择至少一条需求")

    records = db.query(UserRequirementJob).filter(
        UserRequirementJob.id.in_(req.record_ids)
    ).all()
    if not records:
        raise HTTPException(status_code=404, detail="未找到对应需求记录")

    cleared_ids: list[int] = []
    for rec in records:
        rec.is_duplicate = False
        rec.duplicate_with = "[]"
        rec.duplicate_detail = "[]"
        rec.similarity = None
        rec.status = "pending"
        cleared_ids.append(rec.id)

    db.commit()
    log_audit(db, "reject_duplicate", user.username,
              target=f"{len(req.record_ids)} 条", detail="确认不重复，发回打分")

    # 触发打分后台任务
    job_id = None
    if cleared_ids:
        bg_job = create_background_job(
            db, job_type="user_requirement_score",
            total=len(cleared_ids), created_by=user.username,
            payload={"record_ids": cleared_ids, "user_id": user.id},
        )
        job_id = bg_job.job_id
        _run_score_records(bg_job.job_id, cleared_ids, user.id)

    return {
        "success": True,
        "cleared": len(cleared_ids),
        "job_id": job_id,
    }


# ---------- GET /owners：获取所有处理人列表（用于下拉筛选） ----------
# 内置处理人常量（TAPD 需求的处理人账号，历史数据 owner 未回填时使用）
_BUILTIN_OWNERS = [
    "王思域03",
    "徐玥玥01",
    "董仪彤",
    "杨润",
    "杨晶晶01",
    "梁峻嵩",
    "张莹莹",
    "布合丽且古丽托热",
    "尹春龙",
    "陈梦琦",
    "王佳良",
]


@router.get("/owners")
async def list_owners(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取处理人列表（内置常量 + 本地数据库 owner 去重）

    处理人 = 需求自身的 owner 字段（TAPD 需求的处理人账号）
    """
    owners = list(_BUILTIN_OWNERS)
    seen = set(owners)

    q = db.query(UserRequirementJob.owner).filter(
        UserRequirementJob.owner.isnot(None),
        UserRequirementJob.owner != "",
    ).distinct()
    # 操作员不需要按 created_by 过滤，因为 owner 字段本身就标识了处理人
    rows = q.all()
    for (owner_str,) in rows:
        if not owner_str:
            continue
        for acc in owner_str.split(";"):
            acc = acc.strip()
            if acc and acc not in seen:
                seen.add(acc)
                owners.append(acc)
    return {"owners": owners}
