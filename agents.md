# TAPD 需求智能处理 Agent 开发指南

> 本文件基于 TAPD 分类机器人项目的实战经验，结合新项目需求整理而成，用于快速启动新项目的开发与部署。

---

## 一、项目概述

### 1.1 项目目标

针对 TAPD 需求平台中的两类内容，分别构建智能处理流程：

| 内容来源 | 处理流程 | 输出 |
|---------|---------|------|
| **用户直接提交的需求** | 需求可靠性打分 → 重复需求识别 → 产品经理评估确认 | 可靠性评分、重复标记、补充问题评论、最终评估结果 |
| **产品经理填写的 PRD** | PRD 有效性打分 → 生成补充建议 | 有效性评分、补充建议清单、完整度对比报告 |

### 1.2 核心功能

#### 用户需求页面

- 调取 TAPD 中"需求待评估"状态的用户提交需求
- 自动进行需求可靠性打分（信息完整度、描述清晰度、可实现性等维度）
- 自动识别重复需求（与历史需求库对比）
- 可靠性不达标时，自动在 TAPD 评论中返回补充问题给提交人
- 可视化展示处理日志、打分分布、重复需求聚类
- **支持产品经理强行将选定需求直接提交至下一步**（绕过自动流程）

#### 产品经理 PRD 页面

- 调取产品经理已填写的 PRD（TAPD 中对应字段或附件）
- 对比用户提交的原始需求
- 给出 PRD 完整度打分（覆盖度、详细度、一致性等维度）
- 生成补充建议清单

---

## 二、技术栈（已验证可行）

### 2.1 后端

```
Python 3.10+
FastAPI              # Web 框架
Uvicorn              # ASGI 服务器
httpx                # 异步 HTTP 客户端（调用 TAPD / DeepSeek API）
SQLAlchemy 1.4       # ORM
aiosqlite            # 异步 SQLite 驱动
python-dotenv        # 环境变量
pydantic             # 数据校验
```

### 2.2 前端

```
Vue 3 + Composition API
Vite                 # 构建工具
Element Plus         # UI 组件库
Vue Router           # 路由
Pinia                # 状态管理（可选）
ECharts              # 可视化图表
```

### 2.3 大模型

```
DeepSeek API（deepseek-chat 模型）
- 用于需求可靠性打分
- 用于重复需求识别
- 用于 PRD 有效性打分与补充建议生成
```

### 2.4 部署

```
Windows 部署机
start_server.bat / stop_server.bat / restart_server.bat
SQLite 单文件数据库
前端构建产物由 FastAPI 静态托管
```

---

## 三、架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────┐
│                  浏览器前端                       │
│  ┌──────────────┐    ┌──────────────────────┐   │
│  │ 用户需求页面  │    │ 产品经理 PRD 页面     │   │
│  └──────────────┘    └──────────────────────┘   │
└─────────────────────┬───────────────────────────┘
                      │ HTTP API
┌─────────────────────┴───────────────────────────┐
│                FastAPI 后端                      │
│  ┌──────────┐ ┌──────────┐ ┌────────────────┐  │
│  │ TAPD     │ │ LLM      │ │ 任务调度器      │  │
│  │ Client   │ │ Client   │ │ (APScheduler)  │  │
│  └──────────┘ └──────────┘ └────────────────┘  │
│  ┌──────────────────────────────────────────┐   │
│  │       SQLite 数据库 (SQLAlchemy)         │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

### 3.2 目录结构

```
tapd-requirement-agent/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI 主应用
│   │   ├── config.py            # 配置管理（@property 实时读取）
│   │   ├── database.py          # 数据库模型与会话
│   │   ├── tapd_client.py       # TAPD API 客户端（@property token）
│   │   ├── llm_client.py        # DeepSeek LLM 客户端（@property api_key）
│   │   ├── auth.py              # 用户认证与会话
│   │   ├── security.py          # 配置二次锁
│   │   ├── audit.py             # 操作审计日志
│   │   ├── scheduler.py         # 定时任务调度
│   │   ├── jobs.py              # 后台任务管理
│   │   ├── reliability_scorer.py    # 需求可靠性打分模块
│   │   ├── duplicate_detector.py    # 重复需求识别模块
│   │   ├── prd_analyzer.py          # PRD 有效性打分模块
│   │   └── knowledge_base.py        # 知识库与提示词
│   ├── .env                    # 环境变量
│   ├── .env.example
│   ├── data/                   # SQLite 数据库
│   ├── logs/                   # 日志目录
│   │   ├── system/
│   │   ├── login/
│   │   ├── audit/
│   │   └── tapd/
│   └── run.py                  # 启动入口
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── UserRequirementView.vue   # 用户需求页面
│   │   │   ├── PrdAnalysisView.vue       # 产品经理 PRD 页面
│   │   │   ├── DashboardView.vue         # 仪表盘
│   │   │   ├── SettingsView.vue          # 系统设置
│   │   │   └── LoginView.vue             # 登录
│   │   ├── api/index.js                  # API 封装
│   │   ├── router/index.js
│   │   └── App.vue
│   ├── package.json
│   └── vite.config.js
├── docs/
├── scripts/
│   ├── start_server.bat
│   ├── stop_server.bat
│   └── restart_server.bat
└── README.md
```

---

## 四、数据库设计

### 4.1 核心表结构

```python
# 用户需求处理记录
class UserRequirementJob(Base):
    __tablename__ = "user_requirement_jobs"
    id = Column(Integer, primary_key=True)
    job_id = Column(String, unique=True)              # 任务 ID
    story_id = Column(String, index=True)             # TAPD 需求 ID
    workspace_id = Column(String)
    title = Column(Text)                              # 需求标题
    description = Column(Text)                        # 需求描述
    tenant_version = Column(String)                   # 租户版本（custom_field_17）
    priority = Column(String)                         # 需求重要程度（custom_field_18）
    creator = Column(String)                          # 提交人
    reliability_score = Column(Float)                 # 可靠性评分（0-100）
    reliability_detail = Column(Text)                 # JSON：各维度得分
    is_duplicate = Column(Boolean, default=False)     # 是否重复
    duplicate_with = Column(Text)                     # JSON：重复的需求 ID 列表
    supplemental_questions = Column(Text)             # JSON：需补充的问题清单
    comment_written = Column(Boolean, default=False)  # 是否已写回评论
    status = Column(String)                           # pending/scored/duplicate/confirmed/rejected
    created_by = Column(String)                       # 操作人
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

# PRD 分析记录
class PrdAnalysisJob(Base):
    __tablename__ = "prd_analysis_jobs"
    id = Column(Integer, primary_key=True)
    job_id = Column(String, unique=True)
    story_id = Column(String, index=True)             # 关联的 TAPD 需求 ID
    workspace_id = Column(String)
    prd_content = Column(Text)                        # PRD 原文
    original_requirement = Column(Text)               # 原始用户需求
    completeness_score = Column(Float)                # 完整度评分（0-100）
    coverage_detail = Column(Text)                    # JSON：覆盖度详情
    suggestions = Column(Text)                        # JSON：补充建议清单
    status = Column(String)                           # pending/analyzed/reviewed
    created_by = Column(String)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

# 后台任务记录（统一任务管理）
class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id = Column(Integer, primary_key=True)
    job_id = Column(String, unique=True)
    job_type = Column(String)                         # user_requirement / prd_analysis
    status = Column(String)                           # running/completed/failed/interrupted
    total = Column(Integer, default=0)
    processed = Column(Integer, default=0)
    succeeded = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    result = Column(Text)                             # JSON 结果
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    created_by = Column(String)

# 评论写回日志
class WritebackLog(Base):
    __tablename__ = "writeback_logs"
    id = Column(Integer, primary_key=True)
    story_id = Column(String, index=True)
    workspace_id = Column(String)
    action = Column(String)                           # reliability_comment / confirm / prd_suggestion
    content = Column(Text)
    success = Column(Boolean)
    error_message = Column(Text)
    created_at = Column(DateTime)
```

---

## 五、核心模块设计

### 5.1 TAPD 客户端（tapd_client.py）

**关键经验：token/api_key 必须用 @property 实时读取，避免网页端修改配置后不生效。**

```python
class TAPDClient:
    def __init__(self):
        self.timeout = 30.0

    @property
    def base_url(self):
        """实时从 settings 读取"""
        return settings.tapd_api_endpoint.rstrip("/")

    @property
    def token(self):
        """实时从 settings 读取"""
        return settings.tapd_auth_token

    def _headers(self, content_type="application/json"):
        _validate_token(self.token)  # 校验 token 有效性
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": content_type,
        }

    async def get_stories(self, workspace_id, limit=50, status=None, fields=None):
        """获取需求列表"""
        # fields 不传时返回所有字段（含自定义字段）
        ...

    async def get_story_detail(self, workspace_id, story_id):
        """获取单条需求详情"""
        ...

    async def add_comment(self, workspace_id, entry_type, entry_id, description, author=None):
        """添加评论（POST，form-data 格式）"""
        ...

    async def update_story_status(self, workspace_id, story_id, status):
        """更新需求状态（产品经理强行提交至下一步时使用）"""
        ...
```

### 5.2 LLM 客户端（llm_client.py）

```python
class DeepSeekClient:
    def __init__(self):
        self.timeout = 60.0
        self.max_retries = 3

    @property
    def api_key(self):
        return settings.deepseek_api_key

    @property
    def base_url(self):
        return settings.deepseek_base_url.rstrip("/")

    @property
    def model(self):
        return settings.deepseek_model

    async def score_reliability(self, title, description):
        """需求可靠性打分"""
        # 返回 {score, dimensions: {完整度, 清晰度, 可实现性}, questions: [...]}
        ...

    async def detect_duplicate(self, title, description, historical_requirements):
        """重复需求识别"""
        # 返回 {is_duplicate, duplicate_with: [...], similarity: 0-1}
        ...

    async def analyze_prd(self, prd_content, original_requirement):
        """PRD 有效性打分与补充建议"""
        # 返回 {completeness_score, coverage: {...}, suggestions: [...]}
        ...
```

### 5.3 需求可靠性打分（reliability_scorer.py）

```python
RELIABILITY_PROMPT = """你是一个需求评审专家。请对以下需求进行可靠性打分。

## 评分维度

1. **信息完整度**（30分）：需求是否包含背景、目标、预期行为、使用场景
2. **描述清晰度**（30分）：描述是否清晰、无歧义、可理解
3. **可实现性**（20分）：需求是否在技术上可实现、范围是否明确
4. **业务价值**（20分）：需求是否有明确的业务价值和使用方

## 输出要求

严格输出以下 JSON：
```json
{
  "total_score": 0-100,
  "dimensions": {
    "completeness": {"score": 0-30, "comment": "..."},
    "clarity": {"score": 0-30, "comment": "..."},
    "feasibility": {"score": 0-20, "comment": "..."},
    "business_value": {"score": 0-20, "comment": "..."}
  },
  "pass": true/false,
  "supplemental_questions": ["问题1", "问题2"],
  "reason": "一句话总结"
}
```

## 需求内容

标题：{title}
描述：{description}
"""
```

### 5.4 重复需求识别（duplicate_detector.py）

```python
DUPLICATE_DETECTION_PROMPT = """你是一个需求重复性识别专家。请判断以下需求是否与历史需求重复。

## 判定标准

- **重复**：核心诉求一致，仅表述不同或细节差异
- **相似不重复**：相关但解决不同问题
- **不重复**：完全不同的需求

## 输出 JSON

```json
{
  "is_duplicate": true/false,
  "duplicate_with": ["需求ID1", "需求ID2"],
  "similarity": 0.0-1.0,
  "reason": "判定依据"
}
```

## 待判断需求

{current_requirement}

## 历史需求库（最近 N 条）

{historical_requirements}
"""
```

### 5.5 PRD 分析（prd_analyzer.py）

```python
PRD_ANALYSIS_PROMPT = """你是一个 PRD 评审专家。请对比用户原始需求和产品经理填写的 PRD，给出完整度打分和补充建议。

## 评分维度

1. **需求覆盖度**（30分）：PRD 是否覆盖了用户需求的所有要点
2. **功能详细度**（25分）：功能描述是否详细到可开发
3. **交互完整度**（20分）：是否描述了异常流程、边界条件
4. **验收标准**（25分）：是否有明确的验收标准

## 输出 JSON

```json
{
  "completeness_score": 0-100,
  "coverage": {
    "covered_points": ["已覆盖点1", "已覆盖点2"],
    "missing_points": ["遗漏点1", "遗漏点2"]
  },
  "dimensions": {
    "requirement_coverage": 0-30,
    "functional_detail": 0-25,
    "interaction_completeness": 0-20,
    "acceptance_criteria": 0-25
  },
  "suggestions": [
    {"category": "功能/交互/验收", "priority": "high/medium/low", "suggestion": "..."}
  ],
  "reason": "一句话总结"
}
```

## 用户原始需求

{original_requirement}

## PRD 内容

{prd_content}
"""
```

---

## 六、API 设计

### 6.1 用户需求处理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/user-requirements/fetch` | 从 TAPD 拉取用户提交的需求 |
| POST | `/api/user-requirements/score` | 启动可靠性打分任务 |
| GET | `/api/user-requirements/jobs/{job_id}/result` | 获取打分结果 |
| POST | `/api/user-requirements/duplicate-check` | 启动重复需求识别 |
| POST | `/api/user-requirements/{story_id}/write-comment` | 写回补充问题评论到 TAPD |
| POST | `/api/user-requirements/{story_id}/force-advance` | 产品经理强行提交至下一步 |
| GET | `/api/user-requirements/logs` | 获取处理日志（分页） |
| GET | `/api/user-requirements/statistics` | 获取统计数据（可视化用） |

### 6.2 PRD 分析

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/prd/list` | 获取可分析的 PRD 列表 |
| POST | `/api/prd/analyze` | 启动 PRD 有效性打分 |
| GET | `/api/prd/jobs/{job_id}/result` | 获取分析结果 |
| GET | `/api/prd/{story_id}/compare` | 对比用户需求与 PRD |

### 6.3 通用接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录 |
| GET | `/api/settings` | 获取系统设置 |
| POST | `/api/settings` | 保存系统设置 |
| GET | `/api/health` | 健康检查 |

---

## 七、前端设计

### 7.1 用户需求页面（UserRequirementView.vue）

```
┌──────────────────────────────────────────────────────┐
│  Tab 切换：[用户需求处理] [PRD 分析]                    │
├──────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│  │ 待处理数  │ │ 平均可靠性 │ │ 重复需求  │ │ 已确认   │ │
│  └──────────┘ └──────────┘ └──────────┘ └─────────┘ │
│                                                      │
│  [拉取需求] [启动打分] [识别重复] [写回评论]            │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │  需求列表表格                                    │  │
│  │  ☐ | 标题 | 提交人 | 可靠性分 | 重复 | 状态 | 操作│  │
│  │  ☐ | ...  | ...   | 75      | 否   | 待评估 | ...│  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  ┌──────────────┐  ┌──────────────────────────────┐ │
│  │ 处理日志流     │  │ 可视化图表区                   │ │
│  │ [10:30] 拉取..│  │ - 可靠性分布直方图             │ │
│  │ [10:31] 打分..│  │ - 重复需求聚类图              │ │
│  │ [10:32] 写回..│  │ - 处理状态饼图                │ │
│  └──────────────┘  └──────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

### 7.2 PRD 分析页面（PrdAnalysisView.vue）

```
┌──────────────────────────────────────────────────────┐
│  Tab 切换：[用户需求处理] [PRD 分析]                    │
├──────────────────────────────────────────────────────┤
│  [拉取 PRD] [启动分析]                                 │
│                                                      │
│  ┌──────────────────┐  ┌──────────────────────────┐ │
│  │ 左侧：PRD 列表     │  │ 右侧：分析详情             │ │
│  │ ☐ 需求A (完整度85)│  │ 用户原始需求：            │ │
│  │ ☐ 需求B (完整度60)│  │ ...                      │ │
│  │ ☐ 需求C (待分析)  │  │ PRD 内容：                │ │
│  │                   │  │ ...                      │ │
│  │                   │  │ 完整度评分：85/100        │ │
│  │                   │  │ 覆盖度：                  │ │
│  │                   │  │ ✓ 已覆盖：...             │ │
│  │                   │  │ ✗ 遗漏：...               │ │
│  │                   │  │ 补充建议：                │ │
│  │                   │  │ 1. [高] 补充异常流程      │ │
│  │                   │  │ 2. [中] 明确验收标准      │ │
│  └──────────────────┘  └──────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

---

## 八、关键实现细节（踩坑经验）

### 8.1 配置热更新（必须用 @property）

```python
# ❌ 错误：初始化时读取一次，网页端修改后不生效
class TAPDClient:
    def __init__(self):
        self.token = settings.tapd_auth_token  # 缓存了！

# ✅ 正确：用 @property 实时读取
class TAPDClient:
    @property
    def token(self):
        return settings.tapd_auth_token  # 每次调用都读最新值
```

### 8.2 TAPD 自定义字段处理

TAPD 的自定义字段名为 `custom_field_1` 到 `custom_field_200`，**中文名无法通过 API 获取**（需要特殊权限）。解决方法：

1. 用诊断脚本（`debug_tapd_fields.py`）拉取一条真实需求，查看所有字段值
2. 对照 TAPD 网页端，确认哪个 `custom_field_xxx` 对应哪个中文名
3. 在代码中硬编码映射：
   ```python
   TENANT_VERSION_KEY = "custom_field_17"   # 租户所属版本
   PRIORITY_KEY = "custom_field_18"         # 需求重要程度
   ```

### 8.3 TAPD owner 字段格式

- TAPD 返回的 owner 格式：`"徐玥玥01;"`（带分号结尾）
- 写回 TAPD 时用纯账号：`"徐玥玥01"`（不带分号）
- 中文名 ≠ TAPD 账号，需要建立映射表：
  ```python
  OWNER_NAME_TO_TAPD = {
      '王思域': '王思域03',
      '徐玥玥': '徐玥玥01',
      '董伊彤': '董仪彤',  # 注意"伊"→"仪"字不同
      # ...
  }
  ```

### 8.4 TAPD API 调用注意

- GET 请求用 `params=` 传参
- POST 请求（如添加评论、更新需求）用 `data=` 传参（form-data 格式）
- Content-Type 设为 `application/x-www-form-urlencoded`
- Token 校验：避免中文占位符导致 ascii 编码错误
  ```python
  def _validate_token(token):
      if not token or token in _PLACEHOLDER_TOKENS:
          raise TAPDClientError("TAPD_AUTH_TOKEN 未配置")
      try:
          token.encode("ascii")
      except UnicodeEncodeError:
          raise TAPDClientError("TAPD_AUTH_TOKEN 含非 ASCII 字符")
  ```

### 8.5 后台任务管理

- 用 `BackgroundJob` 表统一记录所有任务（不要用 `RunLog`）
- 启动时调用 `mark_interrupted_jobs_on_startup()` 把异常中断的任务标记为 `interrupted`
- 前端用轮询（`setInterval` 每 2 秒）查询任务进度

### 8.6 LLM 调用重试机制

```python
for attempt in range(1, self.max_retries + 1):
    try:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            result = self._parse_json_content(content)  # 兼容 markdown 代码块
            return result
    except Exception as e:
        last_error = e
        if attempt < self.max_retries:
            await asyncio.sleep(1.5 * attempt)  # 指数退避
```

### 8.7 JSON 解析容错

LLM 返回的 JSON 可能被 markdown 代码块包裹，需要容错处理：

```python
def _parse_json_content(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    return json.loads(text)
```

### 8.8 数据更新用 upsert

```python
# 分类记录用 upsert 逻辑更新已有记录
existing = db.query(Classification).filter_by(story_id=story_id).first()
if existing:
    existing.category_l1 = new_l1
    existing.updated_at = datetime.now()
else:
    db.add(Classification(story_id=story_id, ...))
db.commit()
```

### 8.9 权限控制

| 角色 | 权限 |
|------|------|
| admin | 全部操作，含"强行提交"、"手动触发"、"停止执行" |
| operator | 只能查看和处理自己的任务（按 `created_by` 隔离） |
| viewer | 已移除，不再使用 |

### 8.10 前端构建与部署

```bash
# 前端构建
cd frontend
npm run build

# 构建产物在 frontend/dist/
# 复制到后端静态目录
cp -r dist/* backend/static_dist/

# 后端托管静态文件
app.mount("/", StaticFiles(directory="static_dist", html=True), name="static")
```

**部署时注意**：覆盖前端文件后，必须删除旧的 `assets/` 目录中的旧 hash 文件，避免浏览器加载到旧版本。

---

## 九、环境变量配置（.env）

```ini
# TAPD 配置
TAPD_API_ENDPOINT=https://api.tapd.cn
TAPD_AUTH_TOKEN=请填入40位十六进制TAPD_API_Token
TAPD_WORKSPACE_IDS=your_tapd_workspace_id

# 大模型配置（OpenAI 兼容端点）
DEEPSEEK_API_KEY=请填入你的API_KEY
DEEPSEEK_BASE_URL=https://your-llm-gateway.example.com/v1
DEEPSEEK_MODEL=qwen3.8-flash

# 服务配置
HOST=0.0.0.0
PORT=8030
DB_PATH=./data/requirement_agent.db
ENVIRONMENT=production

# 机器人配置
BOT_NAME=需求处理机器人
SCHEDULE_INTERVAL_MINUTES=30
BATCH_SIZE=50

# 需求状态过滤（逗号分隔）
STORY_STATUS_FILTER=status_2

# 自定义字段映射（硬编码，因 TAPD custom_fields_config 接口需特殊权限）
CUSTOM_FIELD_TENANT_VERSION=custom_field_17
CUSTOM_FIELD_PRIORITY=custom_field_18
```

---

## 十、部署脚本

### 10.1 start_server.bat

```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
echo 启动 TAPD 需求处理 Agent...
.venv\Scripts\python.exe run.py
pause
```

### 10.2 stop_server.bat

```bat
@echo off
chcp 65001 >nul
echo 停止 TAPD 需求处理 Agent...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8030 ^| findstr LISTENING') do (
    taskkill /PID %%a /F
)
echo 已停止
pause
```

### 10.3 restart_server.bat

```bat
@echo off
chcp 65001 >nul
call stop_server.bat
timeout /t 2 >nul
call start_server.bat
```

---

## 十一、开发流程建议

### 11.1 第一阶段：基础搭建（1-2天）

1. 搭建后端 FastAPI 骨架（main.py、config.py、database.py）
2. 实现 TAPD 客户端（拉取需求、添加评论、更新状态）
3. 实现 LLM 客户端基础调用
4. 搭建前端框架（登录、布局、路由）

### 11.2 第二阶段：核心功能（2-3天）

1. 实现需求可靠性打分模块
2. 实现重复需求识别模块
3. 实现 PRD 分析模块
4. 实现后台任务调度
5. 实现评论写回 TAPD

### 11.3 第三阶段：前端页面（2-3天）

1. 用户需求页面（表格、打分展示、日志流、可视化图表）
2. PRD 分析页面（对比展示、建议清单）
3. 产品经理强行提交功能
4. 仪表盘与统计

### 11.4 第四阶段：完善与部署（1-2天）

1. 权限控制与审计日志
2. 系统设置页面（配置热更新）
3. 前端构建与部署
4. 编写部署文档

---

## 十二、诊断脚本模板

新项目部署到新电脑时，先用诊断脚本验证 TAPD 连接和字段映射：

```python
# debug_tapd_fields.py
"""诊断脚本：验证 TAPD 连接、查看字段映射"""
import asyncio
import httpx
from app.config import settings
from app.tapd_client import tapd_client

async def main():
    ws_id = settings.tapd_workspace_ids.split(",")[0].strip()
    stories = await tapd_client.get_stories(ws_id, limit=1, status="status_2")
    if stories:
        story = stories[0].get("Story", stories[0])
        print("所有字段：")
        for k, v in story.items():
            if v and str(v).strip():
                print(f"  {k} = {v}")
    else:
        print("未获取到需求")

asyncio.run(main())
```

---

## 十三、经验教训清单

| # | 教训 | 解决方案 |
|---|------|---------|
| 1 | token 初始化时缓存，网页修改不生效 | 用 `@property` 实时读取 |
| 2 | TAPD 中文占位符导致 ascii 编码错误 | `_validate_token()` 校验 |
| 3 | `custom_fields_config` 接口需特殊权限 | 硬编码字段映射 |
| 4 | owner 中文名 ≠ TAPD 账号 | 建立映射表，注意同音不同字 |
| 5 | LLM 返回 JSON 被 markdown 包裹 | 正则去除 ```` ```json ```` 包裹 |
| 6 | 前端构建后旧 hash 文件残留 | 部署时清空 assets 目录 |
| 7 | koa-connect wrapper 导致 ctx 泄漏 | 用原生中间件（本项目用 FastAPI 无此问题） |
| 8 | 任务异常中断后状态卡住 | 启动时 `mark_interrupted_jobs_on_startup()` |
| 9 | 浏览器缓存旧 JS | 部署后提示用户 `Ctrl+F5` 强制刷新 |
| 10 | TAPD POST 接口用 form-data 不是 JSON | `data=` 而非 `json=` |

---

## 十四、快速启动 Checklist

- [ ] Python 3.10+ 已安装
- [ ] Node.js 18+ 已安装
- [ ] 创建虚拟环境 `.venv`，安装后端依赖
- [ ] 执行 `npm install` 安装前端依赖
- [ ] 配置 `backend/.env`（TAPD Token、DeepSeek API Key）
- [ ] 运行诊断脚本验证 TAPD 连接
- [ ] 确认自定义字段映射（custom_field_17/18 等）
- [ ] 运行 `npm run build` 构建前端
- [ ] 复制构建产物到 `backend/static_dist/`
- [ ] 启动服务 `start_server.bat`
- [ ] 浏览器访问 `http://localhost:8030`
- [ ] 登录并验证功能

---

*本文件基于 TAPD 分类机器人项目实战经验整理，可直接用于新项目快速启动。*
