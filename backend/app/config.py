import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 7
    ARBITRAGE_API_URL: str = ""
    HTTP_PROXY: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


def get_proxy() -> str:
    """Get HTTP proxy URL from settings or environment."""
    settings = get_settings()
    if settings.HTTP_PROXY:
        return settings.HTTP_PROXY
    return os.environ.get("http_proxy", "") or os.environ.get("HTTP_PROXY", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
