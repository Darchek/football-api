from functools import lru_cache

from pydantic import HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_MONITORED_TOURNAMENTS = ("fifa.world", "esp.1")


class Settings(BaseSettings):
    """Application settings loaded from environment variables or `.env`."""

    espn_base_url: HttpUrl
    telegram_api: HttpUrl
    monitored_tournaments: tuple[str, ...] = DEFAULT_MONITORED_TOURNAMENTS
    monitor_timezone: str = "Europe/Madrid"
    daily_scan_hour: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
