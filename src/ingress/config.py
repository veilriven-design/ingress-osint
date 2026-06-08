"""
Configuration for Ingress (db url, etc.).
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INGRESS_")

    db_url: str = Field(default="sqlite:///./data/ingress.db", alias="INGRESS_DB_URL")


settings = Settings()


def get_db_url() -> str:
    """Convenience accessor (allows override in tests)."""
    return settings.db_url
