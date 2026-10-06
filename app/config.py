import re
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Loki / Prometheus label 命名规则（spec §5）
_LABEL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash"

    prometheus_url: str = ""
    loki_url: str = ""
    cmdb_url: str = ""

    k8s_api_url: str = ""
    k8s_token: str = ""
    k8s_ca_path: str = ""

    loki_label_keys: list[str] = []

    @field_validator("loki_label_keys")
    @classmethod
    def _normalize_label_keys(cls, v: list[str]) -> list[str]:
        # spec §5：只接受 label key；空项【拒绝】而非丢弃；保序去重；非法名 fail fast。
        out: list[str] = []
        seen: set[str] = set()
        for raw in v:
            key = str(raw).strip()
            if not key:
                raise ValueError("loki_label_keys 含空项：空 label key 无效")
            if not _LABEL_NAME_RE.match(key):
                raise ValueError(
                    f"loki_label_keys 含非法 label key: {raw!r}"
                    "（须匹配 [a-zA-Z_][a-zA-Z0-9_]*）"
                )
            if key not in seen:
                seen.add(key)
                out.append(key)
        return out

    rag_enabled: bool = True
    rag_top_k: int = 3

    agent_max_steps: int = 10
    agent_max_read_tools: int = 4

    app_env: str = "development"                 # "development" | "production"
    authenticator: str = ""                      # "" | "dev" | "oidc_jwt"
    executor_principal_id: str = ""              # 空 = 未配置；装配处强制非空


@lru_cache
def get_settings() -> Settings:
    return Settings()
