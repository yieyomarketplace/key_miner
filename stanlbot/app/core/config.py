# app/core/config.py
"""
Centralized configuration using Pydantic Settings.
Ensures environment variables are loaded, typed, and validated at startup.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import HttpUrl, SecretStr, field_validator
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env', 
        env_file_encoding='utf-8', 
        extra='ignore',
        case_sensitive=False
    )

    # Telegram Configuration
    TELEGRAM_BOT_TOKEN: SecretStr
    TELEGRAM_WEBHOOK_SECRET: SecretStr
    WEBHOOK_URL: HttpUrl

    # NVIDIA NIM Configuration
    NVIDIA_API_KEY: SecretStr
    NVIDIA_BASE_URL: HttpUrl = "https://integrate.api.nvidia.com/v1"

    # SQLite Cloud Configuration
    SQLITE_CLOUD_URL: SecretStr

    # Application Settings
    ENVIRONMENT: str = "production"
    LOG_LEVEL: str = "INFO"

    @field_validator('ENVIRONMENT')
    def validate_environment(cls, v):
        allowed = {"development", "staging", "production"}
        if v.lower() not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v.lower()

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance to prevent re-parsing .env on every call."""
    return Settings()