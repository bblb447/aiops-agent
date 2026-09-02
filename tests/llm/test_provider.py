from unittest.mock import patch

from app.config import Settings
from app.llm.provider import LiteLLMProvider


def test_chat_returns_content():
    p = LiteLLMProvider(Settings(llm_api_key="sk-test"))
    with patch("app.llm.provider.litellm.completion") as mock:
        mock.return_value = {"choices": [{"message": {"content": "根因: 版本回归"}}]}
        out = p.chat([{"role": "user", "content": "分析"}])
    assert "版本回归" in out
    _, kwargs = mock.call_args
    assert kwargs["api_base"] == "https://api.deepseek.com"
    assert "deepseek-v4-flash" in kwargs["model"]


def test_make_agent_model_returns_smolagents_model():
    # LLM Provider 必须能为 Agent 产出 smolagents Model（不是只有直连 chat）。
    from smolagents import LiteLLMModel
    p = LiteLLMProvider(Settings(llm_api_key="sk-test", llm_model="deepseek-v4-flash"))
    model = p.make_agent_model()
    assert isinstance(model, LiteLLMModel)
    assert model.model_id == "openai/deepseek-v4-flash"
    assert model.kwargs.get("tool_choice") == "auto"


def test_make_agent_model_no_double_prefix():
    # 用户配置 openai/gpt-5 时不得变成 openai/openai/gpt-5。
    from smolagents import LiteLLMModel
    p = LiteLLMProvider(Settings(llm_api_key="sk-test", llm_model="openai/gpt-5"))
    model = p.make_agent_model()
    assert isinstance(model, LiteLLMModel)
    assert model.model_id == "openai/gpt-5"


def test_make_agent_model_plain_model_gets_openai_prefix():
    # 无 provider 前缀的裸模型名自动补 openai/（OpenAI 兼容端点）。
    from smolagents import LiteLLMModel
    p = LiteLLMProvider(Settings(llm_api_key="sk-test", llm_model="gpt-5"))
    model = p.make_agent_model()
    assert isinstance(model, LiteLLMModel)
    assert model.model_id == "openai/gpt-5"
