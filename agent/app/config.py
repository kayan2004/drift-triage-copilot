from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", frozen=True, extra="forbid")

    # Core
    app_env: Literal["local", "dev", "prod"] = "local"
    log_level: str = "INFO"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-6"

    # Service wiring
    agent_database_url: str
    model_service_url: str
    webhook_secret: str
    drift_webhook_path: str = "/webhooks/drift"

    # Queue layer
    queue_redis_url: str = "redis://redis:6379/1"
    enable_queue: bool = True
    enable_queue_fallback: bool = False
    worker_concurrency: int = 4
    job_timeout_s: int = 120
    max_retries: int = 3
    retry_backoff_base_s: float = 2.0
    retry_backoff_max_s: float = 60.0
    worker_reach_deadline_s: float = 5.0
    dlq_alert_webhook: str | None = None

    @property
    def alembic_database_url(self) -> str:
        """Sync-driver URL for Alembic migrations."""
        return self.agent_database_url.replace("+asyncpg", "")

    @model_validator(mode="after")
    def _check_api_key(self) -> "Settings":
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
