"""配置管理模块

关键经验：所有需要热更新的配置项必须用 @property 实时读取，
避免网页端修改 settings 后不生效（参考 agents.md 8.1 节）。
"""
import os
from functools import lru_cache
from dotenv import load_dotenv

# 加载 .env 文件（启动时加载一次，后续通过 @property 实时读 os.environ）
load_dotenv(override=False)


# 配置二次锁：避免多个并发请求同时写入 .env
import threading
_CONFIG_LOCK = threading.Lock()


class Settings:
    """全局配置类

    所有 TAPD/DeepSeek 等关键配置项用 @property 实时读取 os.environ，
    这样网页端修改 .env 后立即生效，无需重启服务。
    """

    # ---------- 服务配置（启动时固定） ----------
    @property
    def host(self) -> str:
        return os.getenv("HOST", "0.0.0.0")

    @property
    def port(self) -> int:
        return int(os.getenv("PORT", "8030"))

    @property
    def environment(self) -> str:
        return os.getenv("ENVIRONMENT", "development")

    @property
    def db_path(self) -> str:
        return os.getenv("DB_PATH", "./data/requirement_agent.db")

    @property
    def secret_key(self) -> str:
        """JWT 签名密钥。

        优先使用环境变量 SECRET_KEY；但已知弱占位值（如模板默认/“请修改…”）
        一律视为未配置，改由本地持久化的随机密钥兜底，避免可被伪造的弱密钥。
        生成的随机密钥写入 backend/.secret_key，首次生成后保持不变，重启不失效。
        """
        _WEAK_SECRET_KEYS = {
            "", "tapd-requirement-agent-dev-secret",
            "请修改为随机字符串", "change-me", "changeme", "secret", "test",
        }
        env_val = os.getenv("SECRET_KEY")
        if env_val and env_val not in _WEAK_SECRET_KEYS:
            return env_val
        try:
            import secrets
            key_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                ".secret_key",
            )
            if os.path.exists(key_path):
                with open(key_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            new_key = secrets.token_urlsafe(48)
            with open(key_path, "w", encoding="utf-8") as f:
                f.write(new_key)
            try:
                os.chmod(key_path, 0o600)
            except Exception:
                pass
            return new_key
        except Exception:
            # 兜底：每次启动随机（会让已签发 token 失效，但保证不被弱密钥伪造）
            import secrets
            return secrets.token_urlsafe(48)

    # ---------- TAPD 配置（@property 实时读取） ----------
    @property
    def tapd_api_endpoint(self) -> str:
        return os.getenv("TAPD_API_ENDPOINT", "https://api.tapd.cn")

    @property
    def tapd_auth_token(self) -> str:
        """TAPD API Token（40 位十六进制）"""
        return os.getenv("TAPD_AUTH_TOKEN", "")

    @property
    def tapd_workspace_ids(self) -> str:
        """工作空间 ID，多个用逗号分隔"""
        return os.getenv("TAPD_WORKSPACE_IDS", "your_tapd_workspace_id")

    @property
    def tapd_api_user(self) -> str:
        """TAPD Basic 认证用的 API User（部分接口需要）"""
        return os.getenv("TAPD_API_USER", "")

    # ---------- DeepSeek 配置（@property 实时读取） ----------
    @property
    def deepseek_api_key(self) -> str:
        return os.getenv("DEEPSEEK_API_KEY", "")

    @property
    def deepseek_base_url(self) -> str:
        return os.getenv("DEEPSEEK_BASE_URL", "https://your-llm-gateway.example.com/v1")

    @property
    def deepseek_model(self) -> str:
        return os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # ---------- 业务配置 ----------
    @property
    def bot_name(self) -> str:
        return os.getenv("BOT_NAME", "需求处理机器人")

    @property
    def schedule_interval_minutes(self) -> int:
        return int(os.getenv("SCHEDULE_INTERVAL_MINUTES", "30"))

    # ---------- 模块技能自动复盘（Phase 4） ----------
    @property
    def skill_auto_review_enabled(self) -> bool:
        """是否启用模块技能定时复盘（默认关闭，需管理员在设置页开启）。"""
        return os.getenv("SKILL_AUTO_REVIEW_ENABLED", "false").lower() == "true"

    @property
    def skill_auto_review_interval_hours(self) -> int:
        """定时复盘间隔（小时），默认 24 小时。"""
        return int(os.getenv("SKILL_AUTO_REVIEW_INTERVAL_HOURS", "24"))

    @property
    def batch_size(self) -> int:
        return int(os.getenv("BATCH_SIZE", "50"))

    @property
    def story_status_filter(self) -> str:
        """需求状态过滤（逗号分隔），如 status_2"""
        return os.getenv("STORY_STATUS_FILTER", "status_2")

    @property
    def reliability_threshold(self) -> float:
        """可靠性达标阈值，默认 60"""
        return float(os.getenv("RELIABILITY_THRESHOLD", "60"))

    @property
    def duplicate_history_limit(self) -> int:
        """重复需求识别时拉取的历史需求数，默认 500"""
        return int(os.getenv("DUPLICATE_HISTORY_LIMIT", "500"))

    @property
    def question_max_count(self) -> int:
        """未达标时生成的补充问题数量上限，默认 3"""
        return int(os.getenv("QUESTION_MAX_COUNT", "3"))

    @property
    def question_focus(self) -> str:
        """补充问题聚焦方向，默认聚焦问题场景"""
        return os.getenv("QUESTION_FOCUS", "problem_scenario")

    @property
    def scoring_strictness(self) -> str:
        """评分松紧度：loose / standard / strict。默认标准档，避免宽松档导致通过率失真。"""
        return os.getenv("SCORING_STRICTNESS", "standard")

    # ---------- PRD 评分标准配置 ----------
    @property
    def prd_strictness(self) -> str:
        """PRD 评分松紧度：loose / standard / strict"""
        return os.getenv("PRD_STRICTNESS", "standard")

    @property
    def prd_pass_threshold(self) -> int:
        """PRD 合格阈值，默认 60"""
        return int(os.getenv("PRD_PASS_THRESHOLD", "60"))

    @property
    def prd_weight_coverage(self) -> int:
        """需求覆盖度权重，默认 30"""
        return int(os.getenv("PRD_WEIGHT_COVERAGE", "30"))

    @property
    def prd_weight_functional(self) -> int:
        """功能详细度权重，默认 25"""
        return int(os.getenv("PRD_WEIGHT_FUNCTIONAL", "25"))

    @property
    def prd_weight_interaction(self) -> int:
        """交互完整度权重，默认 20"""
        return int(os.getenv("PRD_WEIGHT_INTERACTION", "20"))

    @property
    def prd_weight_acceptance(self) -> int:
        """验收标准权重，默认 25"""
        return int(os.getenv("PRD_WEIGHT_ACCEPTANCE", "25"))

    @property
    def story_status_duplicate(self) -> str:
        """重复需求对应的 TAPD status 值（如 status_7），确认重复时写回 TAPD 用"""
        return os.getenv("STORY_STATUS_DUPLICATE", "")

    # ---------- 图片理解（视觉模型）配置 ----------
    # DeepSeek 文本模型不支持图片输入（2026-08 实测），图片理解走
    # OpenAI 兼容的视觉模型端点；未配置 VISION_API_KEY 时自动跳过图片增强。
    @property
    def vision_base_url(self) -> str:
        """视觉模型 OpenAI 兼容端点，默认汇智 AI 网关"""
        return os.getenv("VISION_BASE_URL", "https://your-llm-gateway.example.com/v1")

    @property
    def vision_api_key(self) -> str:
        return os.getenv("VISION_API_KEY", "")

    @property
    def vision_model(self) -> str:
        return os.getenv("VISION_MODEL", "glm-4v-flash")

    @property
    def story_status_product_designing(self) -> str:
        """「产品设计中」对应的 TAPD status 值，手动更改 TAPD 状态时用"""
        return os.getenv("STORY_STATUS_PRODUCT_DESIGNING", "status_21")

    @property
    def story_status_prd_review(self) -> str:
        """「待评审」对应的 TAPD status 值，PRD 分析界面拉取需求时用"""
        return os.getenv("STORY_STATUS_PRD_REVIEW", "status_8")

    # ---------- TAPD 自定义字段映射（硬编码） ----------
    @property
    def custom_field_tenant_version(self) -> str:
        return os.getenv("CUSTOM_FIELD_TENANT_VERSION", "custom_field_17")

    @property
    def custom_field_priority(self) -> str:
        return os.getenv("CUSTOM_FIELD_PRIORITY", "custom_field_18")

    @property
    def custom_field_prd(self) -> str:
        """产品经理填写的 PRD（"需求方案"）所在字段，诊断脚本确认后填入"""
        return os.getenv("CUSTOM_FIELD_PRD", "custom_field_19")

    @property
    def custom_field_user_requirement(self) -> str:
        """用户原始需求（"客户问题描述"）所在字段"""
        return os.getenv("CUSTOM_FIELD_USER_REQUIREMENT", "custom_field_20")

    @property
    def custom_field_ai_score(self) -> str:
        """需求AI打分（10分制）写回TAPD的自定义字段"""
        return os.getenv("CUSTOM_FIELD_AI_SCORE", "custom_field_22")

    @property
    def custom_field_ai_score_reason(self) -> str:
        """AI打分理由写回TAPD的自定义字段（限10字以内）"""
        return os.getenv("CUSTOM_FIELD_AI_SCORE_REASON", "custom_field_27")

    @property
    def custom_field_duplicate(self) -> str:
        """重复需求写回TAPD的自定义字段"""
        return os.getenv("CUSTOM_FIELD_DUPLICATE", "custom_field_31")

    @property
    def custom_field_ai_module(self) -> str:
        """AI模块分类写回TAPD的自定义字段（格式：一级-二级）"""
        return os.getenv("CUSTOM_FIELD_AI_MODULE", "custom_field_32")

    # ---------- 日志目录 ----------
    @property
    def log_dir(self) -> str:
        return os.getenv("LOG_DIR", "./logs")

    # ---------- 分类机器人配置 ----------
    @property
    def auto_assign_owner(self) -> bool:
        """是否自动分配处理人"""
        return os.getenv("AUTO_ASSIGN_OWNER", "false").lower() == "true"

    @property
    def auto_write_comment(self) -> bool:
        """是否自动写回评论"""
        return os.getenv("AUTO_WRITE_COMMENT", "false").lower() == "true"

    @property
    def owner_update_comment(self) -> bool:
        """评论中是否包含处理人信息"""
        return os.getenv("OWNER_UPDATE_COMMENT", "true").lower() == "true"

    @property
    def login_max_attempts(self) -> int:
        """登录最大尝试次数"""
        return int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))

    @property
    def login_lock_minutes(self) -> int:
        """账号锁定时长（分钟）"""
        return int(os.getenv("LOGIN_LOCK_MINUTES", "15"))

    @property
    def backup_retention_days(self) -> int:
        """备份保留天数"""
        return int(os.getenv("BACKUP_RETENTION_DAYS", "14"))

    @property
    def allowed_origins(self) -> str:
        """允许的跨域来源"""
        return os.getenv("ALLOWED_ORIGINS", "")

    @property
    def allowed_origins_list(self) -> list:
        """允许的跨域来源列表"""
        origins = self.allowed_origins
        return [o.strip() for o in origins.split(",") if o.strip()] if origins else []

    # ---------- 写入 .env（设置页面调用） ----------
    def update_env(self, updates: dict) -> None:
        """更新 .env 文件中的配置项（带二次锁）

        Args:
            updates: {key: value} 字典
        """
        with _CONFIG_LOCK:
            env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            existing_keys = {}
            for i, line in enumerate(lines):
                if "=" in line and not line.strip().startswith("#"):
                    key = line.split("=", 1)[0].strip()
                    existing_keys[key] = i

            for key, value in updates.items():
                new_line = f"{key}={value}\n"
                if key in existing_keys:
                    lines[existing_keys[key]] = new_line
                else:
                    lines.append(new_line)

            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

            # 同步更新当前进程的 os.environ（避免重启）
            for key, value in updates.items():
                os.environ[key] = str(value)


settings = Settings()
