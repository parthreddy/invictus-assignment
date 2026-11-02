"""Configuration, read from the environment only. No secret is ever hardcoded.

Locally these come from a .env file 
"""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Runtime connection: a NON-superuser role, so Row-Level Security applies.
    database_url: str = (
        "postgresql+psycopg://riverbend_app:riverbend_app@localhost:5432/riverbend"
    )
    # Admin connection: used only by the one-off bootstrap to create tables/roles.
    admin_database_url: str = (
        "postgresql+psycopg://riverbend:riverbend@localhost:5432/riverbend"
    )

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    monthly_spend_cap_usd: Decimal = Decimal("5.00")

    # none | slow | down -- lets local demos exercise provider-failure paths.
    llm_fault_mode: str = "none"

    # Worker retry policy (overridable so outage demos can run without long waits).
    worker_max_attempts: int = 3
    worker_backoff_base_seconds: float = 2.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
