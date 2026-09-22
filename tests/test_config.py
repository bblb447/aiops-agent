import os

import pytest

from app.config import Settings, get_settings

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


def test_loki_label_keys_defaults_empty():
    # _env_file=None 隔离本机 .env，确保测的是"字段默认值"而不是"你的 .env 恰好没配"
    assert Settings(_env_file=None).loki_label_keys == []


def test_loki_label_keys_parses_json_env(monkeypatch):
    monkeypatch.setenv("LOKI_LABEL_KEYS", '["app"]')
    assert Settings(_env_file=None).loki_label_keys == ["app"]


def test_loki_label_keys_strips_entries(monkeypatch):
    monkeypatch.setenv("LOKI_LABEL_KEYS", '["  app  ", " service_name "]')
    assert Settings().loki_label_keys == ["app", "service_name"]


def test_loki_label_keys_dedupes_keeping_first_order(monkeypatch):
    monkeypatch.setenv("LOKI_LABEL_KEYS", '["app", "service_name", "app"]')
    assert Settings().loki_label_keys == ["app", "service_name"]


def test_loki_label_keys_dedupes_after_strip(monkeypatch):
    # 去重必须在 strip 【之后】：" app " strip 成 "app" 后须与已有 "app" 判为同一项。
    # 若顺序反了（先 dedupe 再 strip），这里会得到 ["app", "app"] —— 回归钉子。
    monkeypatch.setenv("LOKI_LABEL_KEYS", '["app", " app "]')
    assert Settings(_env_file=None).loki_label_keys == ["app"]


@pytest.mark.parametrize("good", ["_private", "A1_", "service_name"])
def test_loki_label_keys_accepts_legal_unusual_names(monkeypatch, good):
    # 接受侧钉子：Loki/Prometheus 规则是 [a-zA-Z_][a-zA-Z0-9_]*，
    # 故下划线开头 / 含大写 / 多字符小写都合法，须原样通过。
    # 若日后被收窄成 ^[a-z][a-z0-9_]*$，本用例会失败（当前套件的缺口）。
    monkeypatch.setenv("LOKI_LABEL_KEYS", f'["{good}"]')
    assert Settings(_env_file=None).loki_label_keys == [good]


def test_loki_label_keys_rejects_empty_entry(monkeypatch):
    # spec §5：空串是【拒绝】，不是丢弃 —— 不得静默变成"只有一个 key"或空 key。
    monkeypatch.setenv("LOKI_LABEL_KEYS", '["app", ""]')
    with pytest.raises(Exception):
        Settings()


def test_loki_label_keys_rejects_blank_entry(monkeypatch):
    monkeypatch.setenv("LOKI_LABEL_KEYS", '["app", "   "]')
    with pytest.raises(Exception):
        Settings()


@pytest.mark.parametrize("bad", ["app-name", "1app", "app name", "app=1", "app{x}"])
def test_loki_label_keys_rejects_invalid_label_name(monkeypatch, bad):
    # spec §5：只接受 label key（Loki/Prometheus 规则 [a-zA-Z_][a-zA-Z0-9_]*）
    monkeypatch.setenv("LOKI_LABEL_KEYS", f'["{bad}"]')
    with pytest.raises(Exception):
        Settings()


def test_loki_label_keys_rejects_malformed_env(monkeypatch):
    # env 不是合法 JSON → 解析阶段即失败（fail fast，不在运行时降级）
    monkeypatch.setenv("LOKI_LABEL_KEYS", "app")
    with pytest.raises(Exception):
        Settings()
