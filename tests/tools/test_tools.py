import httpx
from app.config import Settings
from app.tools.monitoring import MonitoringTool
from app.tools.logging import LoggingTool
from app.tools.cmdb import CMDBTool
from app.tools.knowledge import KnowledgeTool
from app.tools.factory import build_tools


def test_metric_queries_prometheus(monkeypatch):
    s = Settings(prometheus_url="http://prom:9090")
    tool = MonitoringTool(s)
    captured = {}
    def fake_get(url, params=None, timeout=None):
        captured["url"] = str(url); captured["params"] = params
        return httpx.Response(200, request=httpx.Request("GET", str(url)),
                              json={"status": "success", "data": {"result": [{"value": [0, "94.5"]}]}})
    monkeypatch.setattr(httpx, "get", fake_get)
    r = tool.query_metric("cpu_usage", target="server-01")
    assert r.success and r.data["data"]["result"]
    assert "prom:9090" in captured["url"]


def test_unconfigured_prometheus_returns_failure():
    tool = MonitoringTool(Settings())
    r = tool.query_metric("cpu_usage")
    assert not r.success
    assert "未配置" in r.error
    assert r.tool == "query_metric"


def test_unconfigured_loki_returns_failure():
    tool = LoggingTool(Settings())
    r = tool.search_logs("error")
    assert not r.success
    assert "未配置" in r.error


def test_unconfigured_cmdb_returns_failure():
    tool = CMDBTool(Settings())
    r = tool.get_service("order-service")
    assert not r.success
    assert "未配置" in r.error


def test_runbook_search(tmp_path, monkeypatch):
    # rag_enabled=False 显式走关键词路径（RAG 默认开启，测试环境不下载模型）。
    (tmp_path / "restart.md").write_text("当服务 CrashLoopBackOff 时，先检查最近发布再重启。", encoding="utf-8")
    monkeypatch.setattr("app.tools.knowledge.RUNBOOK_DIR", str(tmp_path))
    tool = KnowledgeTool(Settings(rag_enabled=False))
    r = tool.search_runbook("CrashLoopBackOff")
    assert r.success and "restart.md" in r.data.get("hits", [])


class _FakeRetriever:
    def __init__(self):
        self.indexed_chunks = None

    def index(self, chunks):
        self.indexed_chunks = chunks

    def search(self, query, k):
        return [{"source": "restart.md", "text": "当 CrashLoopBackOff 时重启。", "score": 0.99}]


def test_runbook_rag_returns_hits(tmp_path, monkeypatch):
    (tmp_path / "restart.md").write_text("# 重启\n\n当 CrashLoopBackOff 时重启。", encoding="utf-8")
    monkeypatch.setattr("app.tools.knowledge.RUNBOOK_DIR", str(tmp_path))
    tool = KnowledgeTool(Settings())
    fake = _FakeRetriever()
    monkeypatch.setattr(tool, "_get_retriever", lambda: fake)
    r = tool.search_runbook("CrashLoopBackOff")
    assert r.success
    assert r.data["hits"][0]["text"] == "当 CrashLoopBackOff 时重启。"
    assert fake.indexed_chunks and fake.indexed_chunks[0]["source"] == "restart.md"


def test_runbook_rag_failure_falls_back_to_keyword(tmp_path, monkeypatch):
    (tmp_path / "restart.md").write_text("当服务 CrashLoopBackOff 时，先检查最近发布再重启。", encoding="utf-8")
    monkeypatch.setattr("app.tools.knowledge.RUNBOOK_DIR", str(tmp_path))
    tool = KnowledgeTool(Settings())

    def broken():
        raise RuntimeError("embedding 失败")

    monkeypatch.setattr(tool, "_get_retriever", broken)
    r = tool.search_runbook("CrashLoopBackOff")
    assert r.success and "restart.md" in r.data.get("hits", [])
    assert not tool._rag_enabled


def test_build_tools_returns_four_tools():
    tools = build_tools(Settings())
    names = {t.__class__.__name__ for t in tools}
    assert names == {"MonitoringTool", "LoggingTool", "CMDBTool", "KnowledgeTool"}
