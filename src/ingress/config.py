"""
Configuration for Ingress (db url, etc.).
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    db_url: str = Field(default="sqlite:///./data/ingress.db", alias="INGRESS_DB_URL")

    class Config:
        env_prefix = "INGRESS_"


settings = Settings()


def get_db_url() -> str:
    """Convenience accessor (allows override in tests)."""
    return settings.db_url
