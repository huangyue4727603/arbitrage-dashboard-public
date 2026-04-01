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
    """Get next proxy URL from the rotating IP pool."""
    from app.services.proxy_manager import proxy_manager
    proxy = proxy_manager.next_proxy()
    return proxy or ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
