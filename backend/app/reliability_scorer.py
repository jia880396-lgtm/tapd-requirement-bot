"""需求可靠性打分模块

调用 LLM 对用户需求进行可靠性打分，结果写入 UserRequirementJob 表。
"""
import json
from app.tapd_client import TAPDClient
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.user_settings import get_active_setting
from app.database import UserRequirementJob
from app.llm_client import deepseek_client, LLMClientError
from app.jobs import append_process_log
from app.quality_rules import inspect_requirement_text, requirement_precheck_score, normalize_dimension_scores


_RELIABILITY_LIMITS = {"completeness": 30, "clarity": 30, "feasibility": 20, "business_value": 20}


def _format_precheck(precheck: dict, score_rules: dict) -> str:
    evidence = precheck.get("evidence", []) or ["未检测到特定缺陷模式"]
    caps = score_rules.get("caps", {})
    cap_text = "；".join(f"{key}≤{value}" for key, value in caps.items() if value < _RELIABILITY_LIMITS[key])
    return "；".join(evidence) + (f"。维度得分上限：{cap_text}" if cap_text else "")


async def score_single_requirement(
    db: Session,
    job_id: str,
    record_id: int,
) -> dict:
    """对单条需求进行可靠性打分

    Returns:
        打分结果 dict，包含 total_score / dimensions / pass / supplemental_questions / reason
    """
    record = db.query(UserRequirementJob).filter(UserRequirementJob.id == record_id).first()
    if not record:
        return {}

    try:
        # 统一清洗输入，并将确定性缺陷转为可审计的预检约束。
        precheck = inspect_requirement_text(record.title, record.description)

        # 图片检测：有图加分，无图小扣分
        # 判定「有图」的三种情况（任一成立即可）：
        #   1) image_paths 非空（实际下载到了截图文件）
        #   2) image_descriptions 非空（GLM 已识别过截图内容）
        #   3) 描述文本中引用了图片（如「如图2所示」「见截图」等）
        try:
            _img_paths = json.loads(record.image_paths or '[]')
        except Exception:
            _img_paths = []
        _img_desc = (record.image_descriptions or '').strip()
        _desc_text = (record.description or '')
        _has_img_ref = bool(re.search(
            r'如图\s*\d|见图|截图|见下方|如附件|如下图所示|如图所示|如附件',
            _desc_text))
        _has_images = bool(_img_paths) or bool(_img_desc) or _has_img_ref
        if _has_images:
            precheck['flags'].append('has_images')
            if _img_paths:
                precheck['evidence'].append(f'附带 {len(_img_paths)} 张截图')
            elif _img_desc:
                precheck['evidence'].append('有截图（AI已识别内容）')
            else:
                precheck['evidence'].append('描述中引用了截图')
        else:
            precheck['flags'].append('no_images')
            precheck['evidence'].append('需求未附带截图（小幅扣分）')

        score_rules = requirement_precheck_score(precheck)

        # 截图 AI 识别文字按需拼接（与重复识别/PRD 分析一致）：作为图片直入的文字兜底，
        # 使"【需求截图内容（AI识别）】段已并入描述"在打分链路也成立，落实"有图加分"原则。
        img_text = (record.image_descriptions or "").strip()
        if img_text:
            precheck["description"] = (precheck["description"] or "").strip() + "\n\n【需求截图内容（AI识别）】\n" + img_text

        # 图片直入（一体化视觉模型）：下载需求截图（最多 3 张）直接随 prompt 交给主模型，
        # 不再依赖 GLM 文字中转。主模型为纯文本模型时跳过下载（模型名不含视觉关键字），
        # 截图文字仍由后台任务的 GLM 注入提供。
        def _model_supports_images() -> bool:
            name = (deepseek_client.model or "").lower()
            return any(k in name for k in ("vl", "vision", "omni", "gpt-4o", "gemini", "claude"))

        images = []
        if _model_supports_images():
            try:
                paths = json.loads(record.image_paths or "[]")
            except Exception:
                paths = []
            if paths:
                from app.tapd_client import tapd_client
                from app.vision_client import compress_image
                for p in paths[:3]:
                    try:
                        content = await tapd_client.download_image(record.workspace_id or "", p)
                        if content:
                            images.append(compress_image(content))
                    except Exception:
                        continue

        result = await deepseek_client.score_reliability(
            title=precheck["title"],
            description=precheck["description"],
            quality_precheck=_format_precheck(precheck, score_rules),
            images=images or None,
        )

        # 以维度分为唯一可信来源：代码层限制各维度权重和预检上限后重算总分，
        # 不直接接受 LLM 给出的 total_score，消除模型锚点分与维度分不一致问题。
        dimensions = result.get("dimensions", {})
        normalized, total_score, score_warnings = normalize_dimension_scores(
            dimensions, score_rules["caps"], score_rules.get("deductions"),
        )
        normalized_dimensions = {}
        for key, score in normalized.items():
            source = dimensions.get(key, {}) if isinstance(dimensions, dict) else {}
            comment = source.get("comment", "") if isinstance(source, dict) else ""
            normalized_dimensions[key] = {"score": score, "comment": comment}
        result["dimensions"] = normalized_dimensions
        result["total_score"] = total_score

        threshold = float(get_active_setting("reliability_threshold"))
        is_pass = total_score >= threshold and not precheck["has_hard_defect"]
        result["pass"] = is_pass

        # 保留模型对『可改进但已通过』需求的建议；写回 TAPD 的动作仍由未达标状态控制。
        raw_questions = result.get("supplemental_questions", [])
        questions = [str(q).strip() for q in raw_questions if str(q).strip()][:int(get_active_setting("question_max_count"))]
        if not questions and (not is_pass or precheck["flags"]):
            questions = ["请补充具体客户、业务场景、操作步骤和期望效果。"]

        record.reliability_score = total_score
        # evidence 为模型的事实核查结论（A~F），存库供人工复核与案例库标注使用；
        # 模型未返回或格式非法时不影响主流程。
        evidence = result.get("evidence", {})
        if not isinstance(evidence, dict):
            evidence = {}
        record.reliability_detail = json.dumps({
            "dimensions": normalized_dimensions,
            "reason": result.get("reason", ""),
            "evidence": evidence,
            "precheck": {"flags": precheck["flags"], "evidence": precheck["evidence"], "caps": score_rules["caps"]},
            "normalization_warnings": score_warnings,
        }, ensure_ascii=False)
        record.supplemental_questions = json.dumps(questions, ensure_ascii=False)

        record.status = "scored"

        # 写回 AI 打分到 TAPD（10分制）+ 补充问题（替代打分理由）
        from app.quality_rules import convert_score_100_to_10
        score_10 = convert_score_100_to_10(total_score)
        record.ai_score_10 = score_10  # 本地也存一份
        # custom_field_27：仅打分<6分（不及格）才写回补充问题，>=6分不写回
        if score_10 >= 6:
            supplement_text = ""
        else:
            supplement_text = "\n".join([f"{i}：{q}" for i, q in enumerate(questions, 1)]) if questions else ""
        record.ai_score_reason = supplement_text
        try:
            if record.workspace_id and record.story_id:
                tapd_client = TAPDClient()
                await tapd_client.update_story_ai_score(
                    workspace_id=record.workspace_id,
                    story_id=record.story_id,
                    score_10=score_10,
                    reason=supplement_text,
                )
                append_process_log(
                    db, job_id, "user_requirement",
                    f"需求 {record.story_id} AI打分+补充问题已写回TAPD: {score_10}/10",
                    story_id=record.story_id, level="info",
                )
        except Exception as e:
            # 写回失败不阻塞主流程
            append_process_log(
                db, job_id, "user_requirement",
                f"需求 {record.story_id} AI打分写回TAPD失败: {e}",
                story_id=record.story_id, level="warning",
            )

        db.commit()

        append_process_log(
            db, job_id, "user_requirement",
            f"需求 {record.story_id} 打分完成：{total_score}/100 ({'通过' if is_pass else '未达标'})" + (f"；预检：{'、'.join(precheck['flags'])}" if precheck["flags"] else ""),
            story_id=record.story_id,
            level="success" if is_pass else "warning",
        )
        return result

    except LLMClientError as e:
        append_process_log(
            db, job_id, "user_requirement",
            f"需求 {record.story_id} 打分失败：{e}",
            story_id=record.story_id,
            level="error",
        )
        raise
    except Exception as e:
        append_process_log(
            db, job_id, "user_requirement",
            f"需求 {record.story_id} 打分异常：{e}",
            story_id=record.story_id,
            level="error",
        )
        raise
