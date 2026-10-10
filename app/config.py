from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TASKPLANNER_",
        env_file=".env",
        extra="ignore",
    )

    env: str = "development"
    database_url: str = "sqlite:///./taskplanner.db"

    # Optional, server-side-only Google Calendar read credentials.
    google_calendar_ids: str = "primary"
    google_access_token: SecretStr | None = None
    google_refresh_token: SecretStr | None = None
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
