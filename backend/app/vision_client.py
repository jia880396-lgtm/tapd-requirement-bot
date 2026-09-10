"""可配置的图片理解客户端。

DeepSeek 文本模型不支持图片输入（2026-08 实测确认：OpenAI 端点报 400、
Anthropic 端点静默丢弃图片），因此需求截图的理解走外部 OpenAI 兼容的
视觉模型端点（如智谱 GLM-4V-Flash、通义 Qwen-VL）。

配置项（.env 或系统设置 / 用户设置）：
- VISION_BASE_URL：视觉模型 OpenAI 兼容端点，默认智谱开放平台
- VISION_API_KEY：视觉模型 API Key；未配置时 vision_configured()=False
- VISION_MODEL：模型名，默认 glm-4v-flash（免费）

所有调用失败均返回空串而非抛异常：图片增强是可选能力，不能拖垮主流程。
"""
import base64
import io
import logging

import httpx

from app.user_settings import get_active_setting

logger = logging.getLogger(__name__)

# 压缩后的最大宽度：控制视觉模型输入 token 成本（图片是 token 大头）
_MAX_WIDTH = 1280
# 单张图片最大尺寸（压缩后仍超限则放弃该图，防止超大图拖慢调用）
_MAX_BYTES = 2 * 1024 * 1024

_PLACEHOLDER_KEYS = ("请填入", "your_", "placeholder")


def vision_configured() -> bool:
    """视觉模型是否已配置（未配置时调用方应跳过图片增强）。"""
    key = get_active_setting("vision_api_key") or ""
    return bool(key) and len(key) >= 10 and not key.lower().startswith(_PLACEHOLDER_KEYS)


def compress_image(image_bytes: bytes, max_width: int = _MAX_WIDTH) -> bytes:
    """压缩图片（缩宽 + 转 JPEG）。PIL 不可用或压缩失败时返回原图。"""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(image_bytes))
        if im.width > max_width:
            ratio = max_width / im.width
            im = im.resize((max_width, max(1, int(im.height * ratio))), Image.LANCZOS)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        out = buf.getvalue()
        # 压缩没变小（如原图已是小 JPEG）就用原图
        return out if 0 < len(out) < len(image_bytes) else image_bytes
    except Exception as e:
        logger.warning(f"[vision] 图片压缩失败，使用原图: {e}")
        return image_bytes


async def describe_image(image_bytes: bytes, context: str = "") -> str:
    """调用视觉模型描述一张需求截图，返回文字描述。

    未配置视觉模型、图片超限或调用失败时返回空串（不抛异常）。
    context 为需求文字，帮助模型结合上下文理解截图。
    """
    if not vision_configured() or not image_bytes:
        return ""
    try:
        compressed = compress_image(image_bytes)
        if len(compressed) > _MAX_BYTES:
            logger.warning(f"[vision] 图片压缩后仍超限（{len(compressed)} bytes），跳过")
            return ""
        b64 = base64.b64encode(compressed).decode()

        prompt = (
            "这是一张旺店通ERP（电商ERP软件）相关的截图。请：\n"
            "1. 完整提取截图中所有可见文字（界面标题、按钮、字段名、报错信息、单据编号等），尽量原文照抄；\n"
            "2. 用一两句话描述截图展示的业务界面或场景。\n"
        )
        if context:
            prompt += f"\n关联需求文字（帮助你理解截图）：{context[:500]}"

        payload = {
            "model": get_active_setting("vision_model"),
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            "max_tokens": 800,
        }
        base_url = get_active_setting("vision_base_url").rstrip("/")
        headers = {"Authorization": f"Bearer {get_active_setting('vision_api_key')}"}
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        logger.warning(f"[vision] 图片描述失败: {e}")
        return ""


async def enrich_record_with_images(db, record, max_images: int = 3) -> bool:
    """下载需求记录中的截图 → 视觉模型描述 → 追加进 record.description。

    返回是否发生变更。单图失败跳过，绝不抛异常；视觉模型未配置时直接跳过。
    描述文字拼接为「【需求截图内容（AI识别）】」段，供打分/分类/重复/PRD 共用。
    """
    import json as _json

    from app.tapd_client import tapd_client

    if not vision_configured():
        return False
    try:
        paths = _json.loads(record.image_paths or "[]")
    except Exception:
        paths = []
    if not paths:
        return False

    workspace_id = record.workspace_id or ""
    blocks = []
    for i, path in enumerate(paths[:max_images]):
        try:
            content = await tapd_client.download_image(workspace_id, path)
            if not content:
                continue
            desc = await describe_image(content, context=(record.title or "")[:200])
            if desc:
                blocks.append(f"[截图{i + 1}] {desc}")
        except Exception as e:  # noqa: BLE001 — 单图失败不拖垮整条需求
            logger.warning(f"[vision] 截图处理失败 {str(path)[:60]}: {e}")

    if blocks:
        # 识别文字写入独立列 image_descriptions，不污染原始描述；
        # 一体化主模型（图片直入）不需要该文字，重复识别等场景由调用方按需拼接。
        record.image_descriptions = "\n".join(blocks)
        try:
            db.commit()
        except Exception:
            db.rollback()
            return False
        return True
    return False


async def enrich_prd_record(db, record, max_images: int = 3) -> bool:
    """PRD 分析记录图片增强：截图视觉描述追加进记录。

    注入目标：优先追加到 original_requirement（客户截图帮助判断 PRD 覆盖度），
    原始需求为空时追加到 prd_content（PRD 内嵌截图帮助理解方案内容）。
    单图失败跳过，绝不抛异常；视觉模型未配置时直接跳过。
    """
    import json as _json

    from app.tapd_client import tapd_client

    if not vision_configured():
        return False
    try:
        paths = _json.loads(record.image_paths or "[]")
    except Exception:
        paths = []
    if not paths:
        return False

    workspace_id = record.workspace_id or ""
    blocks = []
    for i, path in enumerate(paths[:max_images]):
        try:
            content = await tapd_client.download_image(workspace_id, path)
            if not content:
                continue
            desc = await describe_image(content, context=(record.title or "")[:200])
            if desc:
                blocks.append(f"[截图{i + 1}] {desc}")
        except Exception as e:  # noqa: BLE001 — 单图失败不拖垮整条记录
            logger.warning(f"[vision] PRD 截图处理失败 {str(path)[:60]}: {e}")

    if blocks:
        # 识别文字写入独立列 image_descriptions，不污染原始需求/PRD 原文；
        # PRD 分析调用方按需拼接。
        record.image_descriptions = "\n".join(blocks)
        try:
            db.commit()
        except Exception:
            db.rollback()
            return False
        return True
    return False
