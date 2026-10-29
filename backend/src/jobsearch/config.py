"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server-side configuration. Secrets never leave the server."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://jobsearch:jobsearch@db:5432/jobsearch"

    # AI provider
    ai_provider: str = "anthropic"
    anthropic_api_key: str = ""
    ai_model: str = "claude-haiku-5-5"

    # Scheduling / worker
    collect_schedule: str = "0 */6 * * *"
    leader_election: bool = False
    # How often the worker drains the manual (re)analysis queue so dashboard feedback is prompt.
    analysis_poll_seconds: int = 5

    # Misc
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ai_enabled(self) -> bool:
        """True when a real provider is configured; otherwise the stub is used."""
        return bool(self.anthropic_api_key) and self.ai_provider == "anthropic"


@lru_cache
def get_settings() -> Settings:
    return Settings()
