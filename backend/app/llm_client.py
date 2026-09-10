"""DeepSeek LLM 客户端

关键经验（参考 agents.md 5.2 / 8.6 / 8.7）：
1. api_key 用 @property 实时读取
2. 重试机制：max_retries + 指数退避
3. JSON 解析容错：剥离 markdown 代码块包裹
"""
import asyncio
import base64
import json
import re
from typing import Optional

import httpx

from app.config import settings
from app.user_settings import get_active_setting


# 中文占位符 api_key
# ---------- 共享 httpx 连接池 ----------
_llm_shared_client = None  # type: httpx.AsyncClient | None


async def _get_llm_client(timeout: float = 120.0):
    """获取或创建共享 AsyncClient"""
    global _llm_shared_client
    if _llm_shared_client is not None and not _llm_shared_client.is_closed:
        return _llm_shared_client
    _llm_shared_client = httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )
    return _llm_shared_client


_PLACEHOLDER_API_KEYS = {
    "", "请填入你的DEEPSEEK_API_KEY", "your_deepseek_api_key_here",
}


class LLMClientError(Exception):
    pass


def _validate_api_key(api_key: str) -> None:
    if not api_key or api_key in _PLACEHOLDER_API_KEYS:
        raise LLMClientError("DEEPSEEK_API_KEY 未配置，请在系统设置中填入有效的 API Key")


def _parse_json_content(content: str) -> dict:
    """LLM 返回的 JSON 可能被 markdown 代码块包裹，需容错处理（参考 8.7）"""
    if not content:
        raise LLMClientError("LLM 返回空内容")
    text = content.strip()
    if text.startswith("```"):
        # 去除开头的 ```json 或 ```
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        # 去除结尾的 ```
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # 最后尝试提取第一个 {...} 块
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        raise LLMClientError(f"LLM 返回内容无法解析为 JSON: {e}\n原始内容:\n{content[:500]}")


class DeepSeekClient:
    """DeepSeek LLM 客户端

    重要：api_key/base_url/model 必须用 @property 实时读取。
    """

    def __init__(self):
        self.timeout = 120.0
        self.max_retries = 3

    # ---------- @property 实时读取 ----------
    @property
    def api_key(self) -> str:
        return get_active_setting("deepseek_api_key")

    @property
    def base_url(self) -> str:
        return get_active_setting("deepseek_base_url").rstrip("/")

    @property
    def model(self) -> str:
        return get_active_setting("deepseek_model")

    def _headers(self) -> dict:
        _validate_api_key(self.api_key)
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ---------- 通用 chat completion 调用 ----------
    async def chat(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        images: Optional[list] = None,
    ) -> str:
        """通用 chat completion 调用，带重试与指数退避（参考 8.6）

        Args:
            images: 可选，图片字节列表。非空时 user 消息为多模态 content
                    （text + image_url base64），用于一体化的视觉模型；
                    为空时行为与原来完全一致（纯文本）。

        Returns:
            LLM 输出的原始文本
        """
        url = f"{self.base_url}/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if images:
            # 多模态输入：OpenAI 兼容 image_url 格式（图片由调用方先压缩）
            content: list = [{"type": "text", "text": prompt}]
            for img in images:
                if not img:
                    continue
                b64 = base64.b64encode(img).decode()
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            # deepseek-v4-flash 默认启用思考模式（会忽略 temperature 且输出 reasoning_content），
            # 这里显式关闭以保持与旧 deepseek-chat 一致的行为，确保稳定 JSON 输出
            "thinking": {"type": "disabled"},
        }
        headers = self._headers()

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                client = await _get_llm_client(self.timeout)
                resp = await client.post(url, json=payload, headers=headers)
                # 图片自动降级：模型不支持图片输入（带图返回 400/422 且报错与图片相关）时，
                # 去掉图片按纯文本重试，保证主模型切回纯文本模型后行为正确。
                if images and resp.status_code in (400, 422):
                    _msg = ""
                    try:
                        _msg = str(resp.json().get("error", {}).get("message", ""))
                    except Exception:
                        _msg = resp.text[:200]
                    if any(k in _msg.lower() for k in ("image", "unknown variant", "unsupported")):
                        images = None
                        payload["messages"] = [{"role": "user", "content": prompt}]
                        continue
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    await asyncio.sleep(1.5 * attempt)  # 指数退避

        raise LLMClientError(f"LLM 调用失败（重试 {self.max_retries} 次）: {last_error}")

    # ---------- 业务方法：需求可靠性打分 ----------
    async def score_reliability(self, title: str, description: str, quality_precheck: str = "无确定性缺陷", skill=None, temperature: float = None, images: Optional[list] = None) -> dict:
        """需求可靠性打分（注入旺店通业务知识库）

        Args:
            skill: 可选，指定模块 Skill 版本（dict，由 get_active_skill 提供），用于评测覆盖。
            temperature: 可选，覆盖默认采样温度（评测时传 0 保证可复现）。
            images: 可选，图片字节列表（一体化视觉模型时直接把截图交给模型）。
        """
        from app.prompts import get_reliability_prompt
        prompt = get_reliability_prompt(title, description, quality_precheck=quality_precheck, skill=skill)
        if images:
            prompt += "\n\n## 需求截图\n\n以下为需求附带的截图（请结合截图核对并补充事实核查证据）："
        content = await self.chat(
            prompt,
            system="你是旺店通 ERP 系统的需求评审专家，严格按 JSON 格式输出。",
            temperature=temperature if temperature is not None else 0.2,
            images=images,
        )
        return _parse_json_content(content)

    # ---------- 业务方法：重复需求识别 ----------
    async def detect_duplicate(
        self,
        title: str,
        description: str,
        historical_requirements: str,
        skill=None,
        temperature: float = None,
    ) -> dict:
        """重复需求识别（注入旺店通业务知识库）

        Args:
            historical_requirements: 历史需求列表的文本（已格式化）
            skill: 可选，指定模块 Skill 版本（用于评测覆盖）。
            temperature: 可选，覆盖默认采样温度。
        """
        from app.prompts import get_duplicate_prompt
        prompt = get_duplicate_prompt(title, description, historical_requirements, skill=skill)
        content = await self.chat(
            prompt,
            system="你是旺店通 ERP 系统的需求重复性识别专家，严格按 JSON 格式输出。",
            temperature=temperature if temperature is not None else 0.2,
        )
        return _parse_json_content(content)

    # ---------- 业务方法：PRD 分析 ----------
    async def analyze_prd(self, prd_content: str, original_requirement: str, quality_precheck: str = "无", skill=None, temperature: float = None) -> dict:
        """PRD 有效性打分与补充建议（注入旺店通业务知识库）

        Args:
            skill: 可选，指定模块 Skill 版本（用于评测覆盖）。
            temperature: 可选，覆盖默认采样温度。
        """
        from app.prompts import get_prd_prompt
        prompt = get_prd_prompt(prd_content, original_requirement, quality_precheck=quality_precheck, skill=skill)
        content = await self.chat(
            prompt,
            system="你是旺店通 ERP 系统的 PRD 评审专家，严格按 JSON 格式输出。",
            temperature=temperature if temperature is not None else 0.2,
        )
        return _parse_json_content(content)


deepseek_client = DeepSeekClient()
