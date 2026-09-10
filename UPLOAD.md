# 上传到 GitHub 指引

本仓库**已剥离**所有需求数据与隐私凭证：`.env`、`.secret_key`、`*.db`、`*.jsonl`、`*.log`、构建产物（`static_dist`、`frontend/dist`、`backend/app/static`、`.venv`）均不纳入版本管理。内部网关地址、TAPD 工作空间 ID、内网 IP、绝对路径等也已脱敏为占位符。

## 一、本地运行前准备

1. 复制环境变量模板并填入你自己的凭证：
   ```bash
   cp backend/.env.example backend/.env
   # 编辑 backend/.env，填入你自己的 LLM Base URL、API Key、TAPD Auth Token、工作空间 ID
   ```
2. 安装依赖并启动（以 Windows 为例）：
   ```bash
   cd backend
   python -m venv .venv && .venv\Scripts\activate
   pip install -r requirements.txt
   # 启动后端
   uvicorn app.main:app --host 0.0.0.0 --port 8030
   cd ../frontend
   npm install && npm run build
   ```

## 二、推送到 GitHub（自行操作）

```bash
# 在本仓库根目录执行
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git branch -M main
git push -u origin main
```

> 提示：若提交作者信息（当前为占位 `tapd-requirement-bot <dev@example.com>`）想改为你自己的，可在 push 前执行：
> `git commit --amend --author="你的名字 <你的邮箱>"` 后再 push。

## 三、已排除的敏感文件清单（切勿误提交）

- `backend/.env` —— 含真实 API Key / TAPD Token
- `backend/.secret_key` —— JWT 随机密钥
- `*.db` / `*.sqlite` —— 需求业务数据
- `scripts/classify_2026_report.jsonl` 等 `*.jsonl` —— 含需求 ID 与分类结果
- `*.log` / `*.out.log` / `*.err.log` —— 运行日志
- `frontend/node_modules/`、`frontend/dist/`、`backend/static_dist/`、`backend/app/static/`、`backend/.venv/`

如需新增上述类型文件，请确认其不含隐私，或在 `.gitignore` 中显式忽略。
