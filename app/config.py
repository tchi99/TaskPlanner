from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

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
    database_schema: str = "taskplanner"

    # Local mode requires an explicit opt-in and is forbidden in production.
    auth_mode: Literal["local", "supabase"] = "supabase"
    supabase_url: str | None = None
    supabase_allowed_sub: str | None = None
    supabase_audience: str = "authenticated"
    cors_origins: str = "http://localhost:5173"

    def validate_security(self) -> None:
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        if not origins or any(
            origin == "*" or
            urlsplit(origin).scheme not in ("http", "https") or
            not urlsplit(origin).netloc or
            urlsplit(origin).path not in ("", "/") or
            urlsplit(origin).query or urlsplit(origin).fragment or
            urlsplit(origin).username or urlsplit(origin).password
            for origin in origins
        ):
            raise ValueError("Explicit, non-wildcard CORS origins are required")
        if self.env == "production" and any(
            not origin.startswith("https://") for origin in origins
        ):
            raise ValueError("Production CORS origins must use HTTPS")
        if self.auth_mode == "local":
            if self.env not in ("development", "test"):
                raise ValueError("Local authentication mode is forbidden outside development/tests")
            return
        if not self.supabase_url or not self.supabase_allowed_sub:
            raise ValueError("Supabase URL and authorized user ID must be configured")
        parsed = urlsplit(self.supabase_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
                parsed.password or parsed.path not in ("", "/") or
                parsed.query or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError("Supabase URL must be a HTTPS project origin")
        try:
            if str(UUID(self.supabase_allowed_sub)) != self.supabase_allowed_sub:
                raise ValueError("Authorized user ID must be a canonical UUID")
        except (ValueError, AttributeError) as exc:
            raise ValueError("Authorized user ID must be a canonical UUID") from exc
        if not self.supabase_audience.strip():
            raise ValueError("Supabase token audience must be configured")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    # Optional, server-side-only Google Calendar read credentials.
    google_calendar_ids: str = "primary"
    google_access_token: SecretStr | None = None
    google_refresh_token: SecretStr | None = None
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    # TP-050: optional server-side AI suggestions.
    openai_api_key: SecretStr | None = None
    openai_decomposition_model: str = "gpt-4o-mini"
    openai_arbitration_model: str = "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
