"""TAPD API 客户端

关键经验（参考 agents.md 5.1 / 8.1 / 8.2 / 8.3 / 8.4）：
1. token 用 @property 实时读取，避免网页改配置后不生效
2. 自定义字段中文名无法通过 API 获取，必须硬编码映射
3. owner 中文名 ≠ TAPD 账号，需建映射表
4. GET 用 params=，POST（评论/状态）用 data=（form-data）
5. token 需校验避免中文占位符导致 ascii 编码错误

【实测补充】
"客户问题描述"和"需求方案（产品经理填写）"并非独立 custom_field，
而是嵌在 description 富文本里的两个 info 面板（cherry-panel-block）。
本客户端会从 description 中切分并解析这两段内容。
"""
import logging
import re
from typing import Optional

import httpx

from app.config import settings
from app.user_settings import get_active_setting

logger = logging.getLogger(__name__)

# ---------- 共享 httpx 连接池（复用 TCP 连接，50 条需求可省 ~7s） ----------
_shared_client = None  # type: httpx.AsyncClient | None


async def _get_shared_client(timeout: float = 30.0):
    """获取或创建共享 AsyncClient（连接池复用）"""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        return _shared_client
    _shared_client = httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    return _shared_client


# ---------- TAPD owner 中文名 ↔ 账号映射 ----------
# TAPD 返回 owner 格式："徐玥玥01;"（带分号结尾）
# 写回 TAPD 时用纯账号："徐玥玥01"（不带分号）
# 中文名 ≠ TAPD 账号，注意同音不同字（"伊"→"仪"）
OWNER_NAME_TO_TAPD = {
    "王思域": "王思域03",
    "徐玥玥": "徐玥玥01",
    "董伊彤": "董仪彤",  # 注意"伊"→"仪"字不同
    # 后续按实际人员补充
}

# 中文占位符 token（防止误填）
_PLACEHOLDER_TOKENS = {
    "", "请填入40位十六进制TAPD_API_Token", "your_tapd_token_here",
    "TAPD_AUTH_TOKEN", "TAPD_API_Token",
}


class TAPDClientError(Exception):
    pass


def _validate_token(token: str) -> None:
    """校验 TAPD token：非空且不含非 ASCII 字符（避免中文占位符导致编码错误）"""
    if not token or token in _PLACEHOLDER_TOKENS:
        raise TAPDClientError("TAPD_AUTH_TOKEN 未配置，请在系统设置中填入有效的 API Token")
    try:
        token.encode("ascii")
    except UnicodeEncodeError:
        raise TAPDClientError("TAPD_AUTH_TOKEN 含非 ASCII 字符（疑似中文占位符），请检查配置")


def _strip_owner_semicolon(owner: Optional[str]) -> str:
    """去除 owner 字段结尾的分号：'徐玥玥01;' -> '徐玥玥01'"""
    if not owner:
        return ""
    return owner.rstrip(";").strip()


def _parse_owner(owner_raw: Optional[str]) -> list:
    """TAPD owner 可能是 '徐玥玥01;' 或 '徐玥玥01;王思域03;' 多人，返回账号列表"""
    if not owner_raw:
        return []
    # 按分号拆分并去空
    accounts = [a.strip() for a in owner_raw.split(";") if a.strip()]
    return accounts


# ---------- description 富文本解析 ----------
# TAPD 的 description 富文本里嵌套了两个 info 面板：
#   <strong>客户问题描述</strong> ... <strong>需求方案（产品经理填写）</strong> ...
# 这里通过定位"客户问题描述"和"需求方案"两个标题关键词，把 description 切成两段。

# 标题关键词（兼容各种写法）
_USER_REQ_TITLE_PATTERN = re.compile(r"客户问题描述")
_PRD_TITLE_PATTERN = re.compile(r"需求方案\s*（产品经理填写）|需求方案\(产品经理填写\)|需求方案")


# 描述富文本中的图片地址（相对路径如 /tfl/captures/... 或外部完整 URL）
_IMAGE_SRC_PATTERN = re.compile(r'<img[^>]+src="([^"]+)"')


def extract_image_urls(description: str) -> list:
    """从需求描述富文本中提取图片地址列表（保持原始形态，交给下载方法处理）。"""
    if not description:
        return []
    return [u.strip() for u in _IMAGE_SRC_PATTERN.findall(description) if u.strip()]


def _strip_html(html: str) -> str:
    """简易 HTML 转纯文本：去标签、转义符、合并空白"""
    if not html:
        return ""
    # 把 <br> / <br/> / <br /> 替换为换行
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    # </p> </div> </td> </tr> 替换为换行
    text = re.sub(r"</\s*(p|div|td|tr|li|h[1-6])\s*>", "\n", text, flags=re.IGNORECASE)
    # 去掉所有其他标签
    text = re.sub(r"<[^>]+>", "", text)
    # HTML 实体
    text = (text.replace("&nbsp;", " ")
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", '"')
                .replace("&#39;", "'"))
    # 合并多个连续空白（保留换行）
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    return text.strip()


def _split_description(description: str) -> dict:
    """把 description 富文本切分为 {user_requirement, prd_content, full_text, image_urls}

    切分逻辑：
    1. 在原文中查找 "客户问题描述" 标题位置 -> user_req_start
    2. 查找 "需求方案" 标题位置 -> prd_start（用 start() 让标题本身归到 prd 段）
    3. user_requirement = (user_req_start, prd_start) 之间的内容
    4. prd_content = prd_start 之后的内容（解析后去掉开头的标题文字）
    5. image_urls 为原文中所有 <img src> 地址（供图片下载，不因去标签而丢失）
    """
    result = {"user_requirement": "", "prd_content": "", "full_text": "", "image_urls": []}
    if not description:
        return result

    result["image_urls"] = extract_image_urls(description)

    # 先定位标题在原始 HTML 中的位置
    m_user = _USER_REQ_TITLE_PATTERN.search(description)
    m_prd = _PRD_TITLE_PATTERN.search(description)

    user_start = m_user.end() if m_user else -1
    # 用 start() 让"需求方案"标题本身归到 prd 段，避免污染 user_requirement
    prd_start = m_prd.start() if m_prd else -1

    # 切分原始 HTML（保留图片 alt 等，但解析时再去标签）
    if user_start >= 0 and prd_start >= 0 and user_start < prd_start:
        # 两者都找到，且顺序正确
        user_html = description[user_start:prd_start]
        prd_html = description[prd_start:]
        result["user_requirement"] = _strip_html(user_html)
        result["prd_content"] = _strip_html(prd_html)
    elif user_start >= 0 and prd_start < 0:
        # 只有客户问题描述
        result["user_requirement"] = _strip_html(description[user_start:])
    elif prd_start >= 0 and user_start < 0:
        # 只有需求方案
        result["prd_content"] = _strip_html(description[prd_start:])
    else:
        # 两者都没找到，整段当作用户需求
        result["user_requirement"] = _strip_html(description)

    # 去掉 prd_content 开头的标题文字（"需求方案（产品经理填写）" 或 "需求方案"）
    result["prd_content"] = re.sub(
        r"^\s*需求方案\s*[（(]产品经理填写[)）]\s*",
        "",
        result["prd_content"],
    ).strip()
    # 兜底：如果 prd_content 开头还有"需求方案"字样，也去掉
    result["prd_content"] = re.sub(
        r"^\s*需求方案\s*",
        "",
        result["prd_content"],
    ).strip()

    result["full_text"] = _strip_html(description)
    return result


class TAPDClient:
    """TAPD API 客户端

    重要：所有需要热更新的字段（token/workspace_id 等）必须用 @property，
    不要在 __init__ 里缓存。
    """

    def __init__(self):
        self.timeout = 30.0

    # ---------- @property 实时读取配置 ----------
    @property
    def base_url(self) -> str:
        return get_active_setting("tapd_api_endpoint").rstrip("/")

    @property
    def token(self) -> str:
        return get_active_setting("tapd_auth_token")

    @property
    def api_user(self) -> str:
        """部分 TAPD 接口需要 Basic 认证（api_user + token），可空"""
        return get_active_setting("tapd_api_user")

    def _headers(self, content_type: str = "application/json") -> dict:
        _validate_token(self.token)
        # TAPD 支持 Bearer Token 或 Basic Auth（api_user:token）
        headers = {"Content-Type": content_type}
        if self.api_user:
            # Basic Auth：httpx 会自动 base64 编码
            headers_auth = httpx.BasicAuth(self.api_user, self.token)
            return headers, headers_auth
        else:
            headers["Authorization"] = f"Bearer {self.token}"
            return headers, None

    # ---------- 需求列表 ----------
    async def get_stories(
        self,
        workspace_id: str,
        limit: int = 50,
        status: Optional[str] = None,
        fields: Optional[str] = None,
        page: int = 1,
        order: str = "created desc",
        owner: Optional[str] = None,
    ) -> list:
        """获取需求列表

        Args:
            workspace_id: 工作空间 ID
            limit: 每页数量（TAPD 上限 200）
            status: 需求状态过滤，如 "status_2"；多个用逗号
            fields: 返回字段，不传则返回所有字段（含自定义字段）
            page: 页码
            order: 排序，默认 "created desc"（最新优先）
            owner: 处理人账号过滤，如 "徐玥玥01"；多人用分号分隔

        Returns:
            需求列表，每项形如 {"Story": {...}}
        """
        url = f"{self.base_url}/stories"
        params = {
            "workspace_id": workspace_id,
            "limit": str(min(limit, 200)),
            "page": str(page),
            "order": order,
        }
        if status:
            params["status"] = status
        if fields:
            params["fields"] = fields
        if owner:
            params["owner"] = owner

        headers, auth = self._headers()
        client = await _get_shared_client(self.timeout)
        resp = await client.get(url, params=params, headers=headers, auth=auth)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", []) or []

    async def get_stories_all(
        self,
        workspace_id: str,
        status: Optional[str] = None,
        limit_per_page: int = 200,
        max_pages: int = 50,
    ) -> list:
        """分页拉取所有需求（用于历史库）"""
        all_stories = []
        for page in range(1, max_pages + 1):
            batch = await self.get_stories(
                workspace_id=workspace_id,
                limit=limit_per_page,
                status=status,
                page=page,
            )
            if not batch:
                break
            all_stories.extend(batch)
            if len(batch) < limit_per_page:
                break
        return all_stories

    # ---------- 需求详情 ----------
    async def get_story_detail(self, workspace_id: str, story_id: str) -> dict:
        """获取单条需求详情"""
        url = f"{self.base_url}/stories"
        params = {"workspace_id": workspace_id, "id": story_id}
        headers, auth = self._headers()
        client = await _get_shared_client(self.timeout)
        resp = await client.get(url, params=params, headers=headers, auth=auth)
        resp.raise_for_status()
        data = resp.json()
        stories = data.get("data", []) or []
        if not stories:
            return {}
        return stories[0].get("Story", stories[0])

    # ---------- 图片获取（TAPD 客服提供方案，2026-08 验证可用） ----------
    async def get_image_download_url(self, workspace_id: str, image_path: str) -> str:
        """files/get_image：用描述中的图片路径换取临时下载链接。

        链接有效期约 3 秒，必须立即下载，禁止缓存链接。
        image_path 为需求描述 <img src> 中的路径（如 /tfl/captures/...）。
        """
        url = f"{self.base_url}/files/get_image"
        params = {"workspace_id": workspace_id, "image_path": image_path}
        headers, auth = self._headers()
        client = await _get_shared_client(self.timeout)
        resp = await client.get(url, params=params, headers=headers, auth=auth)
        resp.raise_for_status()
        data = resp.json()
        attachment = (data.get("data") or {}).get("Attachment") or {}
        return attachment.get("download_url") or ""

    async def download_image(self, workspace_id: str, image_path: str) -> Optional[bytes]:
        """下载需求中的一张图片，返回字节内容；失败返回 None（单图失败不拖垮整条需求）。

        - 相对路径（/tfl/...）：先 get_image 换临时链接再立即下载
        - 完整 URL（http/https，如 OSS 外链）：直接下载
        """
        try:
            if image_path.startswith(("http://", "https://")):
                download_url = image_path
            else:
                download_url = await self.get_image_download_url(workspace_id, image_path)
                if not download_url:
                    logger.warning(f"[tapd] get_image 未返回下载链接: {image_path[:80]}")
                    return None
            headers, auth = self._headers()
            client = await _get_shared_client(60.0)
            resp = await client.get(download_url, headers=headers, auth=auth)
            resp.raise_for_status()
            content = resp.content
            # 链接失效时 TAPD 返回空壳响应（十几字节），用文件头校验兜底
            valid_magic = (
                content[:4] == b"\x89PNG"          # PNG
                or content[:3] == b"\xff\xd8\xff"  # JPEG
                or content[:6] in (b"GIF87a", b"GIF89a")
                or content[:4] == b"RIFF"          # WEBP
                or content[:2] == b"BM"            # BMP
            )
            if not valid_magic or len(content) < 100:
                logger.warning(f"[tapd] 图片内容无效（可能链接已失效）: {image_path[:80]}")
                return None
            return content
        except Exception as e:
            logger.warning(f"[tapd] 下载图片失败 {image_path[:80]}: {e}")
            return None

    # ---------- 添加评论 ----------
    async def add_comment(
        self,
        workspace_id: str,
        entry_type: str,
        entry_id: str,
        description: str,
        author: Optional[str] = None,
    ) -> dict:
        """添加评论

        Args:
            entry_type: 类型，需求用 "story"，缺陷用 "bug"
            entry_id: 需求 ID
            description: 评论内容
            author: 作者（TAPD 账号，不带分号）

        Returns:
            TAPD 返回的评论数据

        注意：POST 接口用 form-data（data=），不是 JSON（参考 8.4）
        """
        url = f"{self.base_url}/comments"
        # POST 用 form-data，Content-Type 设为 application/x-www-form-urlencoded
        headers, auth = self._headers(content_type="application/x-www-form-urlencoded")
        form_data = {
            "workspace_id": workspace_id,
            "entry_type": entry_type,
            "entry_id": entry_id,
            "description": description,
        }
        if author:
            form_data["author"] = author

        client = await _get_shared_client(self.timeout)
        resp = await client.post(url, data=form_data, headers=headers, auth=auth)
        resp.raise_for_status()
        return resp.json()

    # ---------- 更新需求处理人 ----------
    async def update_story_owner(
        self,
        workspace_id: str,
        story_id: str,
        owner: str,
    ) -> dict:
        """更新需求处理人(Owner)

        Args:
            owner: TAPD 账号（不带分号），如 "徐玥玥01"

        Returns:
            TAPD 返回的 Story 数据
        """
        url = f"{self.base_url}/stories"
        headers, auth = self._headers(content_type="application/x-www-form-urlencoded")
        form_data = {
            "workspace_id": workspace_id,
            "id": story_id,
            "owner": owner,
        }
        client = await _get_shared_client(self.timeout)
        resp = await client.post(url, data=form_data, headers=headers, auth=auth)
        if resp.status_code != 200:
            raise TAPDClientError(f"TAPD写回处理人失败: HTTP {resp.status_code}")
        data = resp.json()
        if data.get("status") != 1:
            error_info = data.get("info") or data.get("message") or str(data)
            raise TAPDClientError(f"TAPD写回处理人失败: {error_info}")
        return data.get("data", {}).get("Story", {})

    # ---------- 更新需求状态 ----------
    async def update_story_status(
        self,
        workspace_id: str,
        story_id: str,
        status: str,
    ) -> dict:
        """更新需求状态（产品经理强行提交至下一步时使用）

        Args:
            status: 目标状态值，如 "status_3"
        """
        url = f"{self.base_url}/stories"
        headers, auth = self._headers(content_type="application/x-www-form-urlencoded")
        form_data = {
            "workspace_id": workspace_id,
            "id": story_id,
            "status": status,
        }
        client = await _get_shared_client(self.timeout)
        resp = await client.post(url, data=form_data, headers=headers, auth=auth)
        resp.raise_for_status()
        return resp.json()

    # ---------- 写回AI打分 ----------
    async def update_story_ai_score(
        self,
        workspace_id: str,
        story_id: str,
        score_10: int,
        reason: str = "",
    ) -> dict:
        """将AI打分（10分制）及理由写回TAPD自定义字段

        Args:
            score_10: 10分制的AI打分值（1-10整数）
            reason: AI打分理由，建议10字以内
        """
        from app.config import settings
        score_field = settings.custom_field_ai_score
        reason_field = settings.custom_field_ai_score_reason
        url = f"{self.base_url}/stories"
        headers, auth = self._headers(content_type="application/x-www-form-urlencoded")
        form_data = {
            "workspace_id": workspace_id,
            "id": story_id,
            score_field: str(score_10),
        }
        if reason:
            form_data[reason_field] = reason
        client = await _get_shared_client(self.timeout)
        resp = await client.post(url, data=form_data, headers=headers, auth=auth)
        if resp.status_code != 200:
            raise TAPDClientError(f"TAPD写回AI打分失败: HTTP {resp.status_code}")
        data = resp.json()
        if data.get("status") != 1:
            error_info = data.get("info") or data.get("message") or str(data)
            raise TAPDClientError(f"TAPD写回AI打分失败: {error_info}")
        return data.get("data", {}).get("Story", {})

    async def update_story_custom_fields(
        self,
        workspace_id: str,
        story_id: str,
        fields: dict,
    ) -> dict:
        """通用方法：批量更新需求的自定义字段

        Args:
            fields: {field_name: value} 例如 {"custom_field_28": "是;1234"}
        """
        if not fields:
            return {}
        url = f"{self.base_url}/stories"
        headers, auth = self._headers(content_type="application/x-www-form-urlencoded")
        form_data = {
            "workspace_id": workspace_id,
            "id": story_id,
        }
        for k, v in fields.items():
            if v is not None:
                form_data[k] = str(v)  # 允许空字符串清空字段
        if len(form_data) <= 2:
            return {}
        client = await _get_shared_client(self.timeout)
        resp = await client.post(url, data=form_data, headers=headers, auth=auth)
        if resp.status_code != 200:
            raise TAPDClientError(f"TAPD自定义字段写回失败: HTTP {resp.status_code}")
        data = resp.json()
        if data.get("status") != 1:
            error_info = data.get("info") or data.get("message") or str(data)
            raise TAPDClientError(f"TAPD自定义字段写回失败: {error_info}")
        return data.get("data", {}).get("Story", {})

    # ---------- 字段提取辅助 ----------
    @staticmethod
    def extract_fields(story: dict) -> dict:
        """从 TAPD Story 对象中提取标准化字段

        - 自定义字段 custom_field_x 映射为业务字段名
        - "客户问题描述"和"需求方案"从 description 富文本中解析（非独立 custom_field）
        """
        if not story:
            return {}
        # TAPD 返回的可能是 {"Story": {...}} 或直接 {...}
        s = story.get("Story", story) if isinstance(story, dict) else {}

        description_raw = s.get("description", "") or ""
        # 从 description 富文本中切分出"客户问题描述"和"需求方案"
        desc_parts = _split_description(description_raw)

        return {
            "story_id": s.get("id", ""),
            "workspace_id": s.get("workspace_id", ""),
            "title": s.get("name", ""),
            "description": description_raw,  # 原始富文本（保留用于详情展示）
            "description_text": desc_parts["full_text"],  # 去标签纯文本（完整）
            "image_urls": desc_parts["image_urls"],  # 描述中截图地址（供视觉识别下载）
            "creator": _strip_owner_semicolon(s.get("creator", "")),
            "owner": _parse_owner(s.get("owner", "")),
            "status": s.get("status", ""),
            "priority_tapd": s.get("priority", ""),
            "created": s.get("created", ""),
            "modified": s.get("modified", ""),
            "tenant_version": s.get(get_active_setting("custom_field_tenant_version"), ""),
            "priority_custom": s.get(get_active_setting("custom_field_priority"), ""),
            # 这两个字段从 description 富文本解析得到（不是 custom_field）
            "prd_content": desc_parts["prd_content"],
            "user_requirement": desc_parts["user_requirement"],
            # 其他常用 custom_field 也保留（诊断脚本发现）
            "customer_code": s.get("custom_field_12", ""),       # 客户标识
            "submitter": s.get("custom_field_14", ""),            # 需求提交人（带分号）
            "business_priority": s.get("custom_field_20", ""),    # 业务优先级数字
            "dev_owner": s.get("custom_field_eight", ""),         # 开发负责人
            # 保留所有 custom_field_x 供诊断
            "all_custom_fields": {
                k: v for k, v in s.items() if k.startswith("custom_field_")
            },
        }

    # ---------- 连接检查 ----------
    async def check_connection(self) -> bool:
        """检查 TAPD API 连接是否正常（使用短超时避免阻塞状态接口）"""
        try:
            ws_id = get_active_setting("tapd_workspace_ids").split(",")[0].strip()
            if not ws_id:
                return False
            url = f"{self.base_url}/stories"
            params = {"workspace_id": ws_id, "limit": "1"}
            headers, auth = self._headers()
            client = await _get_shared_client(5.0)
            resp = await client.get(url, params=params, headers=headers, auth=auth)
            resp.raise_for_status()
            return True
        except Exception:
            return False


tapd_client = TAPDClient()
