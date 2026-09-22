import pytest

from app.config import Settings
from app.tools.logging import LoggingTool


@pytest.mark.integration
class TestLoki:
    def test_search_logs_hits_seeded(self, l1_env):
        # seed_loki 已由 backend 在 session 就绪时灌入 {app="order-service"}（conftest 依赖 l1_env）
        tool = LoggingTool(Settings(loki_url=l1_env["loki"]))
        r = tool.search_logs('{app="order-service"}')
        assert r.success
        result = r.data.get("data", {}).get("result") or []
        assert result, r.data
        assert result[0]["stream"]["app"] == "order-service"

    def test_search_logs_unknown_label_empty(self, l1_env):
        tool = LoggingTool(Settings(loki_url=l1_env["loki"]))
        r = tool.search_logs('{app="no-such-app-xyz"}')
        assert r.success
        assert r.data["data"]["result"] == []

    def test_search_logs_isolated_endpoint_refused(self):
        tool = LoggingTool(Settings(loki_url="http://127.0.0.1:31999"))
        r = tool.search_logs('{app="order-service"}')
        assert not r.success
        assert "查询失败" in r.error

    def test_search_logs_bare_string_returns_readable_400(self, l1_env):
        # spec §9.2：真实 Loki 的 400 响应体必须被完整透传（#11 的核心收益）。
        # 这是本阶段唯一需要真实后端的断言：证明错误反馈在真实链路上可用。
        tool = LoggingTool(Settings(loki_url=l1_env["loki"]))
        r = tool.search_logs("order-service 500 error")
        assert not r.success
        assert "HTTP 400" in r.error
        assert "parse error" in r.error
