import os
from app.config import get_settings

def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")
    s = get_settings()
    assert s.llm_base_url == "https://api.deepseek.com"
    assert s.llm_api_key == "sk-test"
    assert s.llm_model == "deepseek-v4-flash"
    assert s.agent_max_steps > 0

def test_settings_defaults():
    s = get_settings()
    assert s.agent_max_steps == 10
    assert s.agent_max_read_tools == 4
