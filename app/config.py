from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BOT_TOKEN: str
    ADMIN_IDS: str = ""
    TARGET_CHANNEL: str = ""

    TEXT_LLM_BASE_URL: str = "https://openrouter.ai/api/v1"
    TEXT_LLM_API_KEY: str = ""
    TEXT_LLM_MODEL: str = "google/gemma-3-27b-it:free"

    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    TELETHON_API_ID: int = 0
    TELETHON_API_HASH: str = ""
    TELETHON_SESSION_NAME: str = "sl_digital_user"
    TELETHON_SESSION_STRING: str = ""

    HF_API_KEY: str = ""
    HF_MODEL: str = "black-forest-labs/FLUX.1-schnell"
    STABILITY_API_KEY: str = ""
    MODELSLAB_API_KEY: str = ""
    FAL_API_KEY: str = ""

    VK_ACCESS_TOKEN: str = ""
    VK_USER_ACCESS_TOKEN: str = ""
    VK_GROUP_ID: int = 0
    VK_API_VERSION: str = "5.199"

    TIMEZONE: str = "Europe/Moscow"
    DAILY_POST_TIME: str = "10:00"

    @property
    def admin_ids_list(self) -> List[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip().isdigit()]


@lru_cache()
def get_config() -> Config:
    return Config()
