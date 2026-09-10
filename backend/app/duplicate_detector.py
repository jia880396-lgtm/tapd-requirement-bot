"""重复需求识别模块

调用 LLM 对比历史需求库（最近 500 条），识别重复需求。
"""
import json
import re
from collections import Counter
from typing import List

from sqlalchemy.orm import Session

from app.config import settings
from app.user_settings import get_active_setting
from app.database import UserRequirementJob
from app.llm_client import deepseek_client, LLMClientError
from app.jobs import append_process_log
from app.quality_rules import clean_plain_text


_CANDIDATE_LIMIT = 25
_DUPLICATE_SIMILARITY_THRESHOLD = 0.80


def duplicate_threshold() -> float:
    """重复判定硬阈值：优先用模块 Skill 的 similarity_threshold，否则回退 0.80。"""
    try:
        from app.skill_store import get_active_skill
        s = get_active_skill("duplicate")
        if s:
            return float(s.get("params", {}).get("similarity_threshold", _DUPLICATE_SIMILARITY_THRESHOLD))
    except Exception:
        pass
    return _DUPLICATE_SIMILARITY_THRESHOLD


def _tokens(text: str) -> set[str]:
    """轻量中文词元：连续英文数字、常见业务词和双字片段，用于候选召回而非最终定性。"""
    normalized = clean_plain_text(text).lower()
    chunks = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", normalized)
    pairs = {chunk[i:i + 2] for chunk in chunks if re.fullmatch(r"[\u4e00-\u9fff]+", chunk) for i in range(len(chunk) - 1)}
    return set(chunks) | pairs


def _lexical_similarity(left: UserRequirementJob, right: UserRequirementJob) -> float:
    l_tokens = _tokens(f"{left.title or ''} {left.description or ''}")
    r_tokens = _tokens(f"{right.title or ''} {right.description or ''}")
    if not l_tokens or not r_tokens:
        return 0.0
    return len(l_tokens & r_tokens) / len(l_tokens | r_tokens)


def select_duplicate_candidates(record: UserRequirementJob, historical_records: List[UserRequirementJob], limit: int = _CANDIDATE_LIMIT) -> List[UserRequirementJob]:
    """先用无外部依赖的词元 Jaccard 召回候选，再交由 LLM 精判，避免整库 prompt 溢出。"""
    ranked = []
    for item in historical_records:
        if str(item.story_id) == str(record.story_id) or item.is_duplicate:
            continue
        score = _lexical_similarity(record, item)
        title_overlap = bool(_tokens(record.title or "") & _tokens(item.title or ""))
        if score > 0 or title_overlap:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: (pair[0], pair[1].tapd_created or pair[1].created_at), reverse=True)
    return [item for _, item in ranked[:limit]]


def _format_historical_requirements(records: List[UserRequirementJob]) -> str:
    """把经过召回筛选的候选需求格式化为 LLM 可读文本。"""
    if not records:
        return "(暂无高相关候选需求)"
    lines = []
    for r in records[:_CANDIDATE_LIMIT]:
        desc = clean_plain_text(r.description, limit=300)
        lines.append(f"- [ID:{r.story_id}] {clean_plain_text(r.title, limit=120)}\n  描述：{desc}")
    return "\n".join(lines)


async def detect_duplicate_for_record(
    db: Session,
    job_id: str,
    record_id: int,
    historical_records: List[UserRequirementJob],
) -> dict:
    """对单条需求进行重复识别

    Returns:
        {is_duplicate, duplicate_with, similarity, reason}
    """
    record = db.query(UserRequirementJob).filter(UserRequirementJob.id == record_id).first()
    if not record:
        return {}

    try:
        # 先从历史库召回高相关候选（最多 25 条），再让 LLM 精判，避免整库 prompt 溢出。
        candidates = select_duplicate_candidates(record, historical_records)
        historical_text = _format_historical_requirements(candidates)
        # 截图 AI 识别文字按需拼接（重复识别无图片直入，依赖此文字理解截图信息）
        desc_text = clean_plain_text(record.description)
        if (record.image_descriptions or "").strip():
            desc_text = (desc_text or "").strip() + "\n\n【需求截图内容（AI识别）】\n" + (record.image_descriptions or "").strip()
        result = await deepseek_client.detect_duplicate(
            title=clean_plain_text(record.title),
            description=desc_text,
            historical_requirements=historical_text,
        )

        # 仅接受本轮候选集中真实存在的 story_id，过滤 LLM 幻觉、自身 ID 和已判重复记录。
        candidate_map = {str(item.story_id): item for item in candidates}
        raw_dup_with = result.get("duplicate_with", []) or []
        dup_with = [str(sid) for sid in raw_dup_with if str(sid) in candidate_map and str(sid) != str(record.story_id)]
        try:
            similarity_val = max(0.0, min(float(result.get("similarity", 0)), 1.0))
        except (TypeError, ValueError):
            similarity_val = 0.0
        is_duplicate = bool(result.get("is_duplicate", False)) and bool(dup_with) and similarity_val >= duplicate_threshold()
        if not is_duplicate:
            dup_with = []
            similarity_val = min(similarity_val, duplicate_threshold() - 0.01)
        result["duplicate_with"] = dup_with
        result["similarity"] = round(similarity_val, 3)
        result["is_duplicate"] = is_duplicate
        result["candidate_count"] = len(candidates)

        record.is_duplicate = is_duplicate
        record.duplicate_with = json.dumps(result.get("duplicate_with", []), ensure_ascii=False)
        record.similarity = similarity_val

        # 组装 top3 重复需求详情（duplicate_detail）：从历史库查每条 story_id 的标题
        top_detail = []
        for sid in dup_with[:3]:
            # 双保险：再次过滤自身 story_id（避免历史遗留或 LLM 幻觉）
            if str(sid) == str(record.story_id):
                continue
            match = candidate_map.get(str(sid))
            if match:
                top_detail.append({
                    "story_id": sid,
                    "title": match.title or "",
                    "similarity": similarity_val,
                    "duplicate_type": result.get("duplicate_type", ""),
                    "reason": result.get("reason", ""),
                })
        record.duplicate_detail = json.dumps(top_detail, ensure_ascii=False)

        if record.is_duplicate:
            record.status = "duplicate"
        db.commit()

        # 写回"重复需求"字段到 TAPD
        try:
            from app.config import settings as _settings
            from app.tapd_client import TAPDClient as _TAPDClient
            _dup_field = _settings.custom_field_duplicate
            if is_duplicate:
                ids_str = ",".join(dup_with)
                dup_value = f"是;{ids_str}" if ids_str else "是"
            else:
                dup_value = "否"
            _tc = _TAPDClient()
            await _tc.update_story_custom_fields(
                workspace_id=record.workspace_id or "",
                story_id=record.story_id,
                fields={_dup_field: dup_value},
            )
        except Exception:
            pass  # 写回失败不阻塞主流程

        append_process_log(
            db, job_id, "user_requirement",
            f"需求 {record.story_id} 重复识别完成：{'重复' if record.is_duplicate else '不重复'}（相似度 {result.get('similarity', 0)}）",
            story_id=record.story_id,
            level="warning" if record.is_duplicate else "info",
        )
        return result

    except LLMClientError as e:
        append_process_log(
            db, job_id, "user_requirement",
            f"需求 {record.story_id} 重复识别失败：{e}",
            story_id=record.story_id,
            level="error",
        )
        raise
    except Exception as e:
        append_process_log(
            db, job_id, "user_requirement",
            f"需求 {record.story_id} 重复识别异常：{e}",
            story_id=record.story_id,
            level="error",
        )
        raise
