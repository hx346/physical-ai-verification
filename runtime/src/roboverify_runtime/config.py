"""运行时配置（环境变量优先，pydantic-settings 校验）。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库内 schemas/ 目录的默认相对位置：runtime/src/roboverify_runtime -> 上三级
_DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROBOVERIFY_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://roboverify:roboverify@localhost:15432/roboverify"
    log_level: str = "INFO"
    schema_dir: Path = _DEFAULT_SCHEMA_DIR
    kernel_version: str = "0.0.1"

    # 内核计算参数（关键参数配置化，禁止散落魔法值）
    monte_carlo_n_default: int = 10_000
    worker_poll_interval_s: float = 2.0
    worker_lock_ttl_s: int = 300
    # 能力标签（逗号分隔）：sim-worker 设 "gz"，只认领 requires 匹配的任务
    worker_capabilities: str = ""
    job_max_attempts: int = 3


settings = Settings()
