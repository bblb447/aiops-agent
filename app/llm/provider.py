import litellm

from app.config import Settings
from app.llm.base import LLMProvider


class LiteLLMProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def chat(self, messages: list[dict]) -> str:
        resp = litellm.completion(
            model=self._resolve_model_id(),
            api_base=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key,
            messages=messages,
            temperature=0.1,
        )
        return resp["choices"][0]["message"]["content"]

    def make_agent_model(self):
        from smolagents import LiteLLMModel
        return LiteLLMModel(
            model_id=self._resolve_model_id(),
            api_base=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key,
            tool_choice="auto",
            temperature=0.1,
        )

    def _resolve_model_id(self) -> str:
        model = self._settings.llm_model
        # 已带 provider 前缀（如 openai/gpt-5）则原样使用，避免 openai/openai/gpt-5。
        return model if "/" in model else f"openai/{model}"
