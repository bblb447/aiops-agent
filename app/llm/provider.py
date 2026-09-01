import litellm

from app.config import Settings
from app.llm.base import LLMProvider


class LiteLLMProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def chat(self, messages: list[dict]) -> str:
        resp = litellm.completion(
            model=f"openai/{self._settings.llm_model}",
            api_base=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key,
            messages=messages,
            temperature=0.1,
        )
        return resp["choices"][0]["message"]["content"]
