"""Centralised configuration via pydantic-settings.

All environment variables are prefixed with ``QST_``. The ``.env`` file is
loaded automatically if present. Every module that previously read env vars
directly should ``from .config import settings`` instead.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_url: str = Field(default="", description="SQLAlchemy DB URL. Default: CWD/data/db.sqlite")
    pii_key: str = Field(default="", alias="QST_PII_KEY")
    api_keys: list[str] = Field(default_factory=list, description="If non-empty, X-API-Key header required")
    log_level: str = "INFO"
    log_json: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    max_page_size: int = 200
    default_page_size: int = 50
    webhook_timeout_s: float = 5.0
    max_free_text_length: int = 10_000

    model_config = ConfigDict(
        env_prefix="QST_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )


settings = Settings()
