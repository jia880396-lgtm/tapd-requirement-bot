# TAPD 需求智能处理 Agent

基于 [agents.md](agents.md) 文档搭建的 TAPD 需求智能处理系统。

## 快速开始

### 1. 后端环境

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\pip install -r requirements.txt
# Linux/Mac:
# source .venv/bin/activate && pip install -r requirements.txt
```

### 2. 配置（必做）

```bash
# 复制配置模板
copy .env.example .env
# Linux/Mac: cp .env.example .env
```

然后用文本编辑器打开 `backend\.env`，**填入以下 3 个 Key**：

| 配置项 | 说明 | 获取方式 |
|---|---|---|
| `TAPD_AUTH_TOKEN` | TAPD API Token（40位十六进制） | TAPD 公司管理 → API 账号 → 复制 API Token |
| `DEEPSEEK_API_KEY` | 大模型 API Key | 百炼/DeepSeek 控制台创建 |
| `VISION_API_KEY` | 视觉模型 Key（可选，用于截图识别） | 智谱 AI 控制台创建 |

其他配置项（如 `TAPD_WORKSPACE_IDS`、`STORY_STATUS_FILTER`、自定义字段编号等）请按实际项目调整。

### 3. 前端构建（首次需要）

```bash
cd frontend
npm install
npm run build
```

构建完成后自动部署到 `backend\static_dist`。也可直接运行 `scripts\build_and_deploy.bat`。

### 4. 启动服务

```bash
# Windows:
scripts\start_server.bat
# 或:
cd backend
.venv\Scripts\python.exe run.py
```

访问 http://localhost:8030 ，默认账号 `admin / admin123`（请登录后立即修改密码）。

## 目录结构

```
tapd-requirement-bot/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 主应用
│   │   ├── config.py             # 配置管理
│   │   ├── database.py           # 数据库模型与会话
│   │   ├── tapd_client.py        # TAPD API 客户端
│   │   ├── llm_client.py         # 大模型 LLM 客户端
│   │   ├── auth.py               # 用户认证与权限
│   │   ├── scheduler.py          # 定时调度
│   │   ├── jobs.py               # 后台任务管理
│   │   ├── reliability_scorer.py # 需求可靠性打分
│   │   ├── duplicate_detector.py # 重复需求识别
│   │   ├── classifier.py         # AI 模块分类
│   │   ├── prd_analyzer.py       # PRD 分析
│   │   ├── vision_client.py      # 图片理解（截图文字识别）
│   │   └── routers/              # API 路由
│   ├── .env.example              # 配置模板
│   └── requirements.txt          # Python 依赖
├── frontend/
│   └── src/
│       ├── views/                # 页面组件
│       ├── layouts/              # 布局组件
│       ├── router/               # 路由配置
│       ├── api/                  # API 请求封装
│       └── stores/               # Pinia 状态管理
├── scripts/
│   ├── start_server.bat          # 启动服务
│   ├── stop_server.bat           # 停止服务
│   ├── restart_server.bat        # 重启服务
│   └── build_and_deploy.bat      # 前端构建+部署
└── docs/                         # 项目文档
```

## 关键约束

- TAPD / 大模型凭证用 `@property` 实时读取，配置页面修改后立即生效
- TAPD POST 接口用 `data=`（form-data），不是 `json=`
- 任务异常中断会在启动时自动标记为 `interrupted`
- 权限：admin 全权限 / operator 仅自己任务
