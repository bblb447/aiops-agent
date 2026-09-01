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
