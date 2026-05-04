from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    agent_database_url: str
    model_service_url: str
    redis_url: str
    webhook_secret: str
    anthropic_api_key: str
    log_level: str = "INFO"
    drift_webhook_path: str = "/webhooks/drift"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
