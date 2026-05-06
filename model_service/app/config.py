from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    database_url: str
    mlflow_tracking_uri: str
    model_name: str = "bank_churn_classifier"
    redis_url: str
    webhook_secret: str
    log_level: str = "INFO"
    drift_window_size: int = 500
    agent_url: str = "http://agent:8001"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
