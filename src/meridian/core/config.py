"""Application configuration. Everything is overridable via environment variables."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MERIDIAN_", env_file=".env", extra="ignore")

    app_name: str = "meridian"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./data/meridian.db"
    data_dir: str = "data"

    # LLM is optional and only writes narrative summaries. Planning math never
    # depends on it. Values: "none" | "openai-compatible"
    llm_provider: str = "none"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # Policy guardrails
    max_single_po_value: float = 25000.0
    approval_threshold: float = 5000.0
    default_service_level: float = 0.95
    forecast_horizon_days: int = 30
    review_period_days: int = 7

    seed_sample_data: bool = True


def get_settings() -> Settings:
    return Settings()
