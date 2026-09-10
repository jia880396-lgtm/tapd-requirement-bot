"""分类机器人 - 分类核心逻辑
拉取需求 -> LLM分类 -> 写回评论 -> 分配处理人

适配当前项目架构：使用绝对导入、复用现有 tapd_client 和 jobs 模块。
"""
import logging
import re
from datetime import datetime

from app.config import settings
from app.user_settings import get_active_setting
from app.database import (
    get_session_local, Classification, RunLog, BotStatus,
    get_status, set_status, UserRequirementJob,
)
from app.tapd_client import tapd_client, TAPDClientError
from app.jobs import create_background_job, update_background_job
from app.owner_mapping_cls import resolve_owner
from app.quality_rules import clean_plain_text
from app.classification_kb import CATEGORY_TREE, CATEGORY_DESCRIPTIONS

logger = logging.getLogger(__name__)

_current_job_id = None


def _set_current_job(job_id):
    global _current_job_id
    _current_job_id = job_id


def _clear_current_job():
    global _current_job_id
    _current_job_id = None


def _is_already_classified(db, story_id: str) -> bool:
    """检查需求是否已分类过"""
    existing = db.query(Classification).filter(
        Classification.story_id == story_id
    ).first()
    return existing is not None


def _is_api_key_configured() -> bool:
    """检查 DeepSeek API Key 是否已正确配置"""
    key = get_active_setting("deepseek_api_key") or ""
    return bool(key) and not key.startswith("sk-placeholder") and not key.startswith("请填入")


def _confidence_cn(level: str) -> str:
    """置信度转中文"""
    return {"high": "高", "medium": "中", "low": "低", "review": "待人工复核", "retry": "待重试"}.get(level, level)


def _guess_l2(title: str, description: str, l1: str) -> str:
    """二级分类关键词兜底：按 L2 名称与描述文本在需求文字中的命中程度选择最贴近的二级。

    用于二级必填场景下模型未给出二级分类时的兜底；无任何关键词命中时返回空串。
    """
    valid_l2 = CATEGORY_TREE.get(l1, [])
    if not valid_l2:
        return ""
    desc_map = CATEGORY_DESCRIPTIONS.get(l1, {})
    text = f"{title} {description or ''}"
    best, best_score = "", 0
    for l2 in valid_l2:
        l2_desc = desc_map.get(l2, "") if isinstance(desc_map, dict) else ""
        keywords = [kw for kw in re.split(r"[、，,；;]", l2_desc) if kw and len(kw) >= 2]
        score = sum(1 for kw in keywords if kw in text)
        if l2 in text:
            score += 3  # 二级名称直接命中加权
        if score > best_score:
            best, best_score = l2, score
    return best


def _validate_category_result(result: dict, title: str = "", description: str = "") -> dict:
    """校验 L1/L2 合法性并强制归类（不再因低置信度/非法分类送待人工复核）。

    - 置信度 low：保留模型分类结果，confidence 保持 low，供人工按置信度筛选复查
    - L1 非法：按标题关键词兜底猜测分类，confidence 强制 low，reason 注明原返回
    - L2 非法：置空后按关键词兜底；一级有二级列表但二级为空：关键词兜底填上
    - 仅 API 调用失败（无分类结果可用）仍走待人工复核（在 _classify_with_llm 中处理）
    """
    l1 = str(result.get("category_l1", "")).strip()
    l2 = str(result.get("category_l2", "")).strip()
    confidence = str(result.get("confidence", "low")).strip().lower()
    reason = str(result.get("reason", "")).strip()

    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    forced = False
    if l1 not in CATEGORY_TREE:
        guessed = _guess_category_from_title(title) if title else "配置"
        reason = f"[分类不合法已兜底] LLM 返回一级分类『{l1 or '空'}』，按标题关键词归为『{guessed}』。{reason}"
        l1, l2 = guessed, ""
        forced = True
    valid_l2 = CATEGORY_TREE.get(l1, [])
    if l2 and l2 not in valid_l2:
        reason = f"[二级分类不合法] 『{l1}』不包含二级分类『{l2}』，已重新兜底。{reason}"
        l2 = ""
        forced = True
    # 二级必填：一级存在二级列表但二级为空时，关键词兜底填上
    if not l2 and valid_l2:
        guessed_l2 = _guess_l2(title, description, l1)
        if guessed_l2:
            l2 = guessed_l2
            reason = f"[二级必填已兜底] 模型未给出二级分类，按关键词归为『{guessed_l2}』。{reason}"
            forced = True
        else:
            reason = f"[二级必填兜底失败] 『{l1}』存在二级分类但需求文字无任何命中关键词，请人工确认。{reason}"
            forced = True
    if forced:
        confidence = "low"

    return {"category_l1": l1, "category_l2": l2, "confidence": confidence, "reason": reason}


async def _classify_with_llm(title: str, description: str, skill=None, temperature: float = None, images: list = None) -> dict:
    """调用 LLM 进行需求分类（复用当前项目的 llm_client）

    skill: 可选，指定模块 Skill 版本（dict）。未传时自动读取生效 Skill；
           生效 Skill 不存在则回退 classification_kb 硬编码常量，保证行为不变。
    temperature: 可选，评测时传 0 保证可复现。
    """
    import httpx
    import json
    from app.skill_store import (
        _CLASSIFICATION_SYSTEM_TEMPLATE,
        build_category_tree_text,
        build_term_mapping_text,
        build_rules_text,
        get_active_skill,
    )

    if skill is None:
        try:
            skill = get_active_skill("classification")
        except Exception:
            skill = None

    if skill and skill.get("prompt_text"):
        # 以 Skill 的 prompt_text 为基准模板（对齐其他三个模块），
        # kb_context 为空时回退内置模块定义知识库。
        base_template = skill["prompt_text"]
        rules = skill.get("rules") or {}
        category_tree = rules.get("category_tree") or CATEGORY_TREE
        category_descriptions = rules.get("category_descriptions") or CATEGORY_DESCRIPTIONS
        term_mapping = rules.get("term_mapping") or TERM_MAPPING
        cross_rules = rules.get("cross_module_rules") or CROSS_MODULE_RULES
        kb_context = skill.get("kb_context") or ""
    else:
        base_template = _CLASSIFICATION_SYSTEM_TEMPLATE
        category_tree, category_descriptions, term_mapping, cross_rules = (
            CATEGORY_TREE, CATEGORY_DESCRIPTIONS, TERM_MAPPING, CROSS_MODULE_RULES
        )
        kb_context = ""

    if not kb_context:
        from app.knowledge_base import get_classification_context
        kb_context = get_classification_context()

    system_prompt = base_template.format(
        category_tree=build_category_tree_text(category_tree, category_descriptions),
        term_mapping=build_term_mapping_text(term_mapping),
        rules=build_rules_text(cross_rules),
        kb_context=kb_context,  # 旧模板无此占位符时自动忽略
    )

    # Phase 2：若有误判案例，把 few-shot 示例注入 system prompt（行为不变：无案例则跳过）
    if skill and skill.get("skill_id"):
        try:
            from app.skill_store import build_fewshot_examples
            fs = build_fewshot_examples(skill["skill_id"], k=3)
            if fs:
                system_prompt = (
                    system_prompt
                    + "\n\n## 误判案例参考（few-shot，仅作学习样例，不影响上方对当前需求的判定）\n\n"
                    + fs
                )
        except Exception:
            pass

    # 所有模块统一使用纯文本输入，避免 HTML 标记和实体影响判断。
    clean_desc = clean_plain_text(description, limit=3000)
    clean_title = clean_plain_text(title, limit=300)

    user_prompt = f"""请对以下需求进行模块分类：

需求标题：{clean_title}

需求描述：{clean_desc[:3000]}

请输出分类结果JSON。"""

    # 注意：base_url 可能已含 /v1（如百炼 OpenAI 兼容端点），统一拼接 /chat/completions
    url = f"{get_active_setting('deepseek_base_url').rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {get_active_setting('deepseek_api_key')}",
        "Content-Type": "application/json",
    }
    # 构造 messages：有图片时用 multimodal 格式（text + image_url）
    import base64 as _b64
    if images:
        user_content = [
            {"type": "text", "text": user_prompt},
        ]
        for img in images:
            if not img:
                continue
            # compress_image 返回 bytes，需 base64 编码后嵌入 data URL
            b64 = _b64.b64encode(img).decode() if isinstance(img, (bytes, bytearray)) else img
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    payload = {
        "model": get_active_setting("deepseek_model"),
        "messages": messages,
        "temperature": temperature if temperature is not None else 0.1,
        "max_tokens": 1200,  # 二级必填 + reason 引用关键词后输出变长，防止 JSON 截断
        "response_format": {"type": "json_object"},
    }

    last_error = None
    _images_fallback_done = False
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]

                # 解析 JSON（兼容 markdown 代码块）
                text = content.strip()
                if text.startswith("```"):
                    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
                    text = re.sub(r"\s*```$", "", text).strip()
                result = json.loads(text)

                if "category_l1" not in result:
                    raise ValueError(f"Missing category_l1 in result: {result}")

                validated = _validate_category_result(result, title=clean_title, description=clean_desc)
                # 二级必填强化重试：一级存在二级列表但二级为空（且兜底失败）时，
                # 带二级清单的强化提示再问一次（复用重试循环，不额外加代码路径）。
                valid_l2 = CATEGORY_TREE.get(validated.get("category_l1", ""), [])
                if valid_l2 and not validated.get("category_l2"):
                    _l2_msg = (user_prompt.rstrip()
                        + f"\n\n【二次确认】你输出的一级分类『{validated['category_l1']}』包含二级分类："
                        + "、".join(valid_l2)
                        + "。请从中选择最贴近的一个作为 category_l2，重新输出完整 JSON，不得留空。")
                    if images and not _images_fallback_done:
                        import base64 as _b64_2
                        _l2_content = [{"type": "text", "text": _l2_msg}]
                        for img in images:
                            if not img:
                                continue
                            b64 = _b64_2.b64encode(img).decode() if isinstance(img, (bytes, bytearray)) else img
                            _l2_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
                        payload["messages"][1]["content"] = _l2_content
                    else:
                        payload["messages"][1]["content"] = _l2_msg
                    continue  # 进入下一轮（attempt 计数 +1）

                return validated

        except Exception as e:
            last_error = e
            logger.warning(f"DeepSeek API attempt {attempt}/3 failed: {e}")
            # API 400 且传了图片：去掉图片回退纯文本重试
            if images and not _images_fallback_done and isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 400:
                logger.info("API 400 with images, falling back to text-only mode")
                _images_fallback_done = True
                payload["messages"] = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
                images = None
                continue  # 跳过 sleep，立即重试
            if attempt < 3:
                import asyncio
                await asyncio.sleep(1.5 * attempt)

    logger.error(f"DeepSeek API call failed after 3 retries: {last_error}")
    return {
        "category_l1": "待人工复核",
        "category_l2": "",
        "confidence": "retry",
        "reason": f"[API调用失败，待重试] {str(last_error)[:100]}",
    }


def _guess_category_from_title(title: str) -> str:
    """当 LLM 返回"其它"/"其他"时，根据标题关键词猜测最可能的分类"""
    platform_keywords = ["美团", "京东", "拼多多", "淘宝", "天猫", "抖音", "快手",
                         "小红书", "微信", "苏宁", "唯品会", "得物", "Shopee", "TEMU",
                         "亚马逊", "eBay", "平台", "对接", "API", "奇门"]
    if any(kw in title for kw in platform_keywords):
        return "对接"

    keyword_map = {
        "订单": "订单", "售后": "售后", "退货": "售后", "退款": "售后",
        "采购": "采购", "供应商": "采购",
        "库存": "仓储", "入库": "仓储", "出库": "仓储", "仓库": "仓储",
        "商品": "商品", "货品": "商品", "SKU": "商品",
        "报表": "报表", "统计": "报表", "数据": "报表",
        "登录": "登录", "密码": "登录",
        "账款": "账款", "财务": "账款", "发票": "账款",
        "铺货": "铺货", "刊登": "铺货",
        "档口": "档口",
        "配置": "配置", "设置": "配置", "模板": "配置",
        "分享": "分享", "面单": "分享",
        "跨境": "跨境",
        "供分销": "供分销", "分销": "供分销",
    }
    for kw, cat in keyword_map.items():
        if kw in title:
            return cat

    return "配置"



async def classify_single_record(db, record) -> dict | None:
    """对单条已入库需求进行LLM分类并写回TAPD（供自动流程调用）

    Args:
        db: 数据库 Session
        record: UserRequirementJob 实例

    Returns:
        {"l1": str, "l2": str} 或 None（失败/跳过时）
    """
    if not record or not record.story_id:
        return None

    # 已分类则直接返回
    existing = db.query(Classification).filter(
        Classification.story_id == record.story_id
    ).first()
    if existing:
        return {"l1": existing.category_l1, "l2": existing.category_l2}

    # 调用 LLM 分类（与打分流程对齐：拼接截图识别文字 + 图片直入）
    import json as _json
    _desc = record.description or ""
    # 拼接 GLM 识别的截图文字
    _img_desc = (record.image_descriptions or "").strip()
    if _img_desc:
        _desc = _desc.strip() + "\n\n【需求截图内容（AI识别）】\n" + _img_desc

    # 检查模型是否支持识图，支持则下载图片直入
    _images = []
    def _model_supports_images():
        name = (get_active_setting("deepseek_model") or "").lower()
        return any(k in name for k in ("vl", "vision", "omni", "gpt-4o", "gemini", "claude"))

    if _model_supports_images():
        try:
            _paths = _json.loads(record.image_paths or "[]")
        except Exception:
            _paths = []
        if _paths:
            from app.tapd_client import tapd_client as _tc
            from app.vision_client import compress_image
            for _p in _paths[:3]:
                try:
                    _content = await _tc.download_image(record.workspace_id or "", _p)
                    if _content:
                        _images.append(compress_image(_content))
                except Exception:
                    continue

    # 调用 LLM 分类
    try:
        result = await _classify_with_llm(record.title or "", _desc, images=_images or None)
    except Exception as e:
        logger.warning(f"classify_single_record LLM失败 {record.story_id}: {e}")
        return None

    category_l1 = result.get("category_l1", "对接")
    category_l2 = result.get("category_l2", "")
    confidence = result.get("confidence", "low")
    reason = result.get("reason", "")

    if category_l1 in ("其它", "其他"):
        category_l1 = "对接"
        reason = f"[已纠正其它] {reason}"

    # 写入 Classification 表
    cls_record = Classification(
        story_id=record.story_id,
        story_title=record.title or "",
        story_description=(record.description or "")[:2000],
        category_l1=category_l1,
        category_l2=category_l2,
        confidence=confidence,
        reason=reason,
        workspace_id=record.workspace_id or "",
        created_by="auto_flow",
    )
    db.add(cls_record)
    db.commit()

    # 写回 TAPD custom_field_32
    try:
        module_value = f"{category_l1}-{category_l2}" if category_l2 else category_l1
        from app.tapd_client import TAPDClient
        tc = TAPDClient()
        await tc.update_story_custom_fields(
            workspace_id=record.workspace_id or "",
            story_id=record.story_id,
            fields={settings.custom_field_ai_module: module_value},
        )
        cls_record.writeback_completed = True
        db.commit()
    except Exception as e:
        logger.warning(f"classify_single_record TAPD写回失败 {record.story_id}: {e}")

    return {"l1": category_l1, "l2": category_l2}


async def process_batch(job_id: str = None, created_by: str = "", owner: str = None, user_id: int | None = None):
    """批量处理需求的主流程：拉取 -> 分类 -> 写评论 -> 分配处理人

    Args:
        owner: 若指定，仅拉取该处理人名下的需求（用于操作员只处理自己需求）
    """
    if user_id is not None:
        SessionLocal = get_session_local()
        settings_db = SessionLocal()
        try:
            from app.user_settings import activate_user_business_settings
            activate_user_business_settings(settings_db, user_id)
        finally:
            settings_db.close()

    if not _is_api_key_configured():
        error_msg = "DeepSeek API Key 未配置或无效，跳过本次处理。"
        logger.error(error_msg)
        set_status("bot_state", "error")
        set_status("last_error", error_msg)
        if job_id:
            update_background_job(None, job_id, status="failed", error_message=error_msg)
        return {"fetched": 0, "classified": 0, "skipped": 0, "errored": 0, "comments": 0, "error": error_msg}

    start_time = datetime.now()
    set_status("last_run_start", start_time.isoformat())
    set_status("bot_state", "running")
    if job_id:
        _set_current_job(job_id)

    SessionLocal = get_session_local()
    db = SessionLocal()
    run_log = RunLog(run_time=start_time, status="running")
    db.add(run_log)
    db.commit()
    db.refresh(run_log)
    run_log_id = run_log.id

    total_fetched = 0
    total_classified = 0
    total_skipped = 0
    total_errored = 0
    total_comments = 0
    total_owners_assigned = 0
    error_msgs = []
    was_stopped = False

    try:
        for workspace_id in get_active_setting("tapd_workspace_ids").split(","):
            workspace_id = workspace_id.strip()
            if not workspace_id:
                continue

            # 检查停止
            from app.database import BackgroundJob
            if job_id:
                bg = db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
                if bg and bg.status == "interrupted":
                    was_stopped = True
                    break

            logger.info(f"Processing workspace: {workspace_id}")

            stories = await tapd_client.get_stories(
                workspace_id=workspace_id,
                limit=get_active_setting("batch_size"),
                status=get_active_setting("story_status_filter") or None,
                owner=owner,
            )
            total_fetched += len(stories)

            # 更新后台任务的 total，让前端能看到正确进度
            if job_id:
                update_background_job(db, job_id, total=total_fetched)

            for item in stories:
                if job_id:
                    bg = db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id).first()
                    if bg and bg.status == "interrupted":
                        was_stopped = True
                        break

                story = item.get("Story", {})
                story_id = story.get("id", "")
                title = story.get("name", "")
                description = story.get("description", "")
                module = story.get("module", "")

                if not story_id:
                    continue

                # 提取业务字段（与用户需求列表保持一致）
                extracted = tapd_client.extract_fields(item)
                tenant_version = extracted.get("tenant_version", "") or ""
                priority = extracted.get("priority_custom", "") or ""
                # original_owner 为 list，转为分号分隔字符串
                owner_list = extracted.get("owner", []) or []
                original_owner = ";".join(owner_list) if isinstance(owner_list, list) else str(owner_list)
                # TAPD 原始提交/更新时间，用于列表展示和排序
                tapd_created = None
                tapd_updated = None
                for field_name, field_value in (("created", extracted.get("created", "")), ("updated", extracted.get("modified", ""))):
                    if not field_value:
                        continue
                    try:
                        parsed_time = datetime.strptime(str(field_value), "%Y-%m-%d %H:%M:%S")
                        if field_name == "created":
                            tapd_created = parsed_time
                        else:
                            tapd_updated = parsed_time
                    except (ValueError, TypeError):
                        pass

                if _is_already_classified(db, story_id):
                    total_skipped += 1
                    continue

                # 与 classify_single_record 对齐：查本地记录获取截图信息，支持图片直入
                import json as _json2
                _local_rec = db.query(UserRequirementJob).filter(
                    UserRequirementJob.story_id == story_id,
                    UserRequirementJob.workspace_id == workspace_id,
                ).first()
                _cls_desc = description or ""
                _cls_images = []
                if _local_rec:
                    # 拼接 GLM 识别的截图文字
                    _local_img_desc = (_local_rec.image_descriptions or "").strip()
                    if _local_img_desc:
                        _cls_desc = _cls_desc.strip() + "\n\n【需求截图内容（AI识别）】\n" + _local_img_desc
                # 检查模型是否支持识图
                def _cls_model_supports_images():
                    _name = (get_active_setting("deepseek_model") or "").lower()
                    return any(_k in _name for _k in ("vl", "vision", "omni", "gpt-4o", "gemini", "claude"))
                if _cls_model_supports_images():
                    _img_paths = []
                    if _local_rec:
                        try:
                            _img_paths = _json2.loads(_local_rec.image_paths or "[]")
                        except Exception:
                            _img_paths = []
                    if _img_paths:
                        from app.vision_client import compress_image as _ci
                        for _ip in _img_paths[:3]:
                            try:
                                _ic = await tapd_client.download_image(workspace_id, _ip)
                                if _ic:
                                    _cls_images.append(_ci(_ic))
                            except Exception:
                                continue

                try:
                    result = await _classify_with_llm(title, _cls_desc, images=_cls_images or None)
                    category_l1 = result.get("category_l1", "对接")
                    category_l2 = result.get("category_l2", "")
                    confidence = result.get("confidence", "low")
                    reason = result.get("reason", "")

                    if category_l1 in ("其它", "其他"):
                        category_l1 = "对接"
                        reason = f"[已纠正其它] {reason}"

                    comment_text = (
                        f"🤖 AI分类 | 一级: {category_l1} | 二级: {category_l2} | "
                        f"置信度: {_confidence_cn(confidence)} | 依据: {reason}"
                    )
                    if confidence == "low":
                        comment_text += "\n⚠️ 低置信度分类，建议人工确认后按需调整。"

                    # 低置信度、非法结果与 API 失败均进入人工复核，不写回评论、不自动派单。
                    needs_review = confidence in {"review", "retry"} or category_l1 == "待人工复核"
                    owner_info = resolve_owner(category_l1, category_l2) if not needs_review else None
                    assigned_owner = None
                    if owner_info:
                        assigned_owner = owner_info["display_name"]
                        if settings.owner_update_comment:
                            comment_text += f"\n📋 处理人: {assigned_owner}"
                    elif needs_review:
                        comment_text += "\n📋 结果已进入待人工复核队列，未自动分配处理人。"

                    comment_id = None
                    comment_written = False
                    if settings.auto_write_comment and not needs_review:
                        try:
                            comment_resp = await tapd_client.add_comment(
                                workspace_id=workspace_id,
                                entry_type="story",
                                entry_id=story_id,
                                description=comment_text,
                            )
                            # 兼容当前 tapd_client 返回完整响应的格式
                            comment_data = comment_resp.get("data", {}) if isinstance(comment_resp, dict) else {}
                            comment_obj = comment_data.get("Comment", comment_data)
                            comment_id = str(comment_obj.get("id", "")) if comment_obj else ""
                            if comment_id:
                                comment_written = True
                                total_comments += 1
                        except Exception as e:
                            logger.error(f"Failed to write comment for {story_id}: {e}")
                            error_msgs.append(f"评论写回失败 {story_id}: {str(e)[:100]}")

                    owner_assigned = False
                    if settings.auto_assign_owner and assigned_owner and not needs_review:
                        try:
                            await tapd_client.update_story_owner(
                                workspace_id=workspace_id,
                                story_id=story_id,
                                owner=owner_info["username"],
                            )
                            owner_assigned = True
                            total_owners_assigned += 1
                        except Exception as e:
                            logger.warning(f"Failed to assign owner for {story_id}: {e}")
                            error_msgs.append(f"处理人分配失败 {story_id}: {str(e)[:80]}")

                    record = Classification(
                        story_id=story_id,
                        story_title=title,
                        story_description=(description or "")[:2000],
                        category_l1=category_l1,
                        category_l2=category_l2,
                        confidence=confidence,
                        reason=reason,
                        original_module=module,
                        workspace_id=workspace_id,
                        comment_id=comment_id,
                        comment_written=comment_written,
                        assigned_owner=assigned_owner,
                        owner_assigned=owner_assigned,
                        created_by=created_by,
                        tenant_version=tenant_version,
                        priority=priority,
                        original_owner=original_owner,
                        tapd_created=tapd_created,
                        tapd_updated=tapd_updated,
                    )
                    db.add(record)
                    db.commit()

                    # 写回"AI模块分类"自定义字段到 TAPD
                    try:
                        if category_l2:
                            module_value = f"{category_l1}-{category_l2}"
                        else:
                            module_value = category_l1
                        await tapd_client.update_story_custom_fields(
                            workspace_id=workspace_id,
                            story_id=story_id,
                            fields={settings.custom_field_ai_module: module_value},
                        )
                        record.writeback_completed = True
                        db.commit()
                    except Exception as e:
                        logger.warning(f"AI模块分类写回TAPD失败 {story_id}: {e}")

                    total_classified += 1

                    # 更新任务进度
                    if job_id:
                        update_background_job(db, job_id,
                                              processed=total_classified + total_skipped + total_errored,
                                              succeeded=total_classified,
                                              failed=total_errored)

                except Exception as e:
                    logger.error(f"Error processing story {story_id}: {e}")
                    total_errored += 1
                    error_msgs.append(f"处理失败 {story_id}: {str(e)[:100]}")
                    db.rollback()

            if was_stopped:
                break

        # 更新运行日志
        run_log = db.query(RunLog).get(run_log_id)
        if run_log:
            run_log.stories_fetched = total_fetched
            run_log.stories_classified = total_classified
            run_log.stories_skipped = total_skipped
            run_log.stories_errored = total_errored
            run_log.comments_written = total_comments
            run_log.owners_assigned = total_owners_assigned
            run_log.status = "stopped" if was_stopped else "success"
            run_log.details = f"处理完成: 获取{total_fetched}, 分类{total_classified}, 跳过{total_skipped}, 错误{total_errored}, 评论{total_comments}, 分配处理人{total_owners_assigned}"
            run_log.error_message = "; ".join(error_msgs[-5:]) if error_msgs else None
            db.commit()

    except Exception as e:
        logger.error(f"Batch processing error: {e}")
        run_log = db.query(RunLog).get(run_log_id)
        if run_log:
            run_log.status = "error"
            run_log.error_message = str(e)[:500]
            db.commit()

    finally:
        end_time = datetime.now()
        set_status("last_run_end", end_time.isoformat())
        set_status("last_run_duration", str(end_time - start_time))
        summary = f"获取{total_fetched} 分类{total_classified} 跳过{total_skipped} 错误{total_errored} 分配处理人{total_owners_assigned}"
        set_status("last_run_summary", f"{'已停止: ' if was_stopped else ''}{summary}")
        set_status("bot_state", "idle")

        if job_id:
            result_data = {
                "fetched": total_fetched, "classified": total_classified,
                "skipped": total_skipped, "errored": total_errored,
                "comments": total_comments, "owners_assigned": total_owners_assigned,
                "stopped": was_stopped,
            }
            import json
            update_background_job(db, job_id,
                                  status="completed" if not was_stopped else "interrupted",
                                  result=json.dumps(result_data))
            _clear_current_job()

        db.close()

    logger.info(f"Batch done: fetched={total_fetched}, classified={total_classified}, skipped={total_skipped}, errored={total_errored}")
    return {
        "fetched": total_fetched, "classified": total_classified,
        "skipped": total_skipped, "errored": total_errored,
        "comments": total_comments, "owners_assigned": total_owners_assigned,
        "stopped": was_stopped,
    }
