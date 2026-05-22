from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend runtime settings."""

    app_name: str = "Studysis Backend"
    app_version: str = "1.3.0"
    api_v1_prefix: str = "/api/v1"
    host: str = "127.0.0.1"
    port: int = 8000

    data_dir: Path = Field(default=Path("data"))
    export_dir: Path = Field(default=Path("exports"))
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])

    ai_enabled: bool = False
    ai_provider: str = "none"
    ai_timeout_seconds: float = 30.0
    ai_temperature: float = 0.2
    ai_max_tokens: int = 900
    ai_outline_max_blocks: int = 80
    ai_chapter_parallelism: int = 4

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    ollama_keep_alive: str = "15m"

    cloud_api_base_url: str = ""
    cloud_api_key: str = ""
    cloud_api_model: str = ""
    cloud_api_path: str = "/chat/completions"
    cloud_thinking_type: str = "disabled"
    cloud_clear_thinking: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""

    return Settings()


settings = get_settings()
