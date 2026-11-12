from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"
    log_json: bool = False

    database_url: str
    api_key: SecretStr

    timezone: ZoneInfo = ZoneInfo("America/Argentina/Buenos_Aires")

    ingest_interval_seconds: float = Field(default=3600.0, gt=0)
    ingest_concurrency: int = Field(default=10, gt=0)
    provider_timeout_seconds: float = Field(default=10.0, gt=0)

    evaluate_interval_seconds: float = Field(default=300.0, gt=0)

    notify_interval_seconds: float = Field(default=30.0, gt=0)
    notify_batch_size: int = Field(default=100, gt=0)
    send_timeout_seconds: float = Field(default=10.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
