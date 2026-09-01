from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash"

    prometheus_url: str = ""
    loki_url: str = ""
    cmdb_url: str = ""

    agent_max_steps: int = 10

@lru_cache
def get_settings() -> Settings:
    return Settings()
