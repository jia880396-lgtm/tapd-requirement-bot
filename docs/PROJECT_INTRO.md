# TAPD 需求智能处理 Agent

## 一句话介绍

一个对接 TAPD 项目管理平台的 AI 工具，能自动拉取客户需求、评估需求质量（打分）、识别重复需求、生成 PRD 方案，帮助产品/研发团队快速筛选和处理用户需求。

## 核心功能

```
TAPD API ──→ 拉取需求 ──→ AI 处理流水线 ──→ 结果展示/推送
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              可靠性打分    重复识别     PRD 分析
             (质量评估)   (去重合并)   (方案生成)
```

### 1. 需求拉取
- 从 TAPD 平台按项目/时间范围批量拉取用户需求
- 异步后台执行，前端实时轮询进度（支持数千条需求的拉取+打分）
- httpx 连接池复用，批量 DB upsert 优化性能

### 2. 可靠性打分（核心）
- **四维评分**：信息完整度(30)、描述清晰度(30)、可实现性(20)、业务价值(20)，总分100
- **预检系统**（`quality_rules.py`）：确定性规则先检测缺陷，生成 cap 上限和扣分值
  - 检测：模板占位符未替换、客户信息缺失、无单号、无量化数据、效果/价值模糊、无截图等
- **LLM 评分**（`reliability_scorer.py`）：DeepSeek 大模型按六项证据(A~F)对档打分
- **规范化**：LLM 原始分被预检 cap 和扣分约束，防止打分偏高
- **三种松紧度**：loose / standard / strict，prompt 四段联动替换
- **图片策略**：有图加分(cap+2)、无图小扣分(-1)、文本引用图片也视为有图

### 3. 重复需求识别
- 先按标题相似度粗筛候选集，再调用 LLM 语义判断是否重复
- 输出重复组，支持人工确认/排除

### 4. PRD 分析
- 基于原始需求 + 截图，调用 LLM 生成结构化 PRD 文档
- 包含功能点、验收标准、优先级建议

### 5. 需求分类
- 自动将需求分类到预设知识库（如 ERP模块、极速版、慧小助等）
- 支持自定义分类规则

### 6. 自动化调度
- 定时自动拉取+打分（可配置间隔和松紧度）
- 支持按负责人过滤、按标签过滤

## 技术架构

| 层级 | 技术栈 |
|------|--------|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy / SQLite(WAL) |
| 前端 | Vue 3 / Element Plus / Pinia / Vite |
| AI | DeepSeek API（打分/重复识别/PRD） / 通义千问VL（图片识别） |
| 数据源 | TAPD Open API |
| 部署 | 单机部署，.bat 一键启停，端口 8030 |

## 项目结构

```
backend/app/
├── main.py                  # FastAPI 入口
├── tapd_client.py           # TAPD API 客户端（连接池复用）
├── llm_client.py            # DeepSeek 客户端（连接池复用）
├── reliability_scorer.py    # 打分主流程
├── quality_rules.py         # 确定性预检规则
├── prompts.py               # 所有 LLM prompt 模板
├── knowledge_base.py        # 领域知识/评分校准常量
├── duplicate_detector.py    # 重复需求识别
├── prd_analyzer.py          # PRD 方案生成
├── vision_client.py         # 图片 OCR/识别（通义千问VL）
├── classifier.py            # 需求分类
├── skill_engine.py          # Skill 执行引擎
├── scheduler.py             # 定时任务调度
├── jobs.py                  # 后台任务管理
└── routers/                 # API 路由层
    ├── user_requirements.py # 需求拉取/打分/查询
    ├── prd.py               # PRD 相关
    ├── classification.py    # 分类相关
    └── ...

frontend/src/views/
├── UserRequirementView.vue  # 主页面：需求列表、拉取、打分
├── PrdAnalysisView.vue      # PRD 分析页面
├── ClassificationView.vue   # 分类管理页面
├── DashboardView.vue        # 仪表盘/统计
└── SettingsView.vue         # 系统配置
```

## 快速启动

```bash
# 后端
cd backend
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
copy .env.example .env  # 填入 TAPD_AUTH_TOKEN 和 DEEPSEEK_API_KEY

# 前端构建
cd frontend && npm install && npm run build

# 启动
scripts\start_server.bat   # 访问 http://localhost:8030
```

## 关键配置（.env）

| 配置项 | 说明 |
|--------|------|
| `TAPD_AUTH_TOKEN` | TAPD API 认证 token |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `CUSTOM_FIELD_USER_REQUIREMENT` | TAPD 中用户需求描述字段的 custom_field ID |
| `STORY_STATUS_FILTER` | 需要处理的需求状态（如"新需求"） |
| `SCORING_STRICTNESS` | 打分松紧度：loose / standard / strict |
