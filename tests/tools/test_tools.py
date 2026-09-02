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


def test_metric_range_queries_prometheus(monkeypatch):
    # 时间序列区间查询：start/end/step 必须传给 /api/v1/query_range，
    # 这是时间关联 RCA（CPU 何时开始上涨）的基础。
    s = Settings(prometheus_url="http://prom:9090")
    tool = MonitoringTool(s)
    captured = {}
    def fake_get(url, params=None, timeout=None):
        captured["url"] = str(url); captured["params"] = params
        return httpx.Response(200, request=httpx.Request("GET", str(url)),
                              json={"status": "success", "data": {"result": [{"values": [[0, "80"], [60, "95"]]}]}})
    monkeypatch.setattr(httpx, "get", fake_get)
    r = tool.query_metric_range("cpu_usage", target="server-01", start=1000, end=2000, step="60s")
    assert r.success and r.data["data"]["result"][0]["values"]
    assert "/api/v1/query_range" in captured["url"]
    assert captured["params"]["query"] == 'cpu_usage{instance=~"server-01.*"}'
    assert captured["params"]["start"] == 1000
    assert captured["params"]["end"] == 2000
    assert captured["params"]["step"] == "60s"


def test_unconfigured_prometheus_range_returns_failure():
    tool = MonitoringTool(Settings())
    r = tool.query_metric_range("cpu_usage", start=0, end=1, step="60s")
    assert not r.success
    assert r.tool == "query_metric_range"


def test_unconfigured_loki_returns_failure():
    tool = LoggingTool(Settings())
    r = tool.search_logs("error")
    assert not r.success
    assert "未配置" in r.error


def test_search_logs_accepts_explicit_window(monkeypatch):
    # 日志查询必须支持显式 start/end，才能围绕 incident 起止时间关联分析。
    s = Settings(loki_url="http://loki:3100")
    tool = LoggingTool(s)
    captured = {}
    def fake_get(url, params=None, timeout=None):
        captured["url"] = str(url); captured["params"] = params
        return httpx.Response(200, request=httpx.Request("GET", str(url)),
                              json={"status": "success", "data": {"result": []}})
    monkeypatch.setattr(httpx, "get", fake_get)
    r = tool.search_logs("ERROR", limit=20, start=100, end=200)
    assert r.success
    assert "/loki/api/v1/query_range" in captured["url"]
    assert captured["params"]["start"] == "100"
    assert captured["params"]["end"] == "200"
    assert captured["params"]["limit"] == 20
    assert captured["params"]["query"] == "ERROR"


def test_search_logs_defaults_to_30min_window(monkeypatch):
    # 未显式给时间窗时，保持默认"最近 30 分钟"行为（向后兼容）。
    s = Settings(loki_url="http://loki:3100")
    tool = LoggingTool(s)
    captured = {}
    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return httpx.Response(200, request=httpx.Request("GET", str(url)),
                              json={"status": "success", "data": {"result": []}})
    monkeypatch.setattr(httpx, "get", fake_get)
    tool.search_logs("ERROR")
    start = int(captured["params"]["start"]); end = int(captured["params"]["end"])
    assert end - start == 30 * 60 * 10**9


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


def test_query_workload_tool(monkeypatch):
    # query_workload 复用 WorkloadService：成功返回结构化负载。
    from app.workload.service import WorkloadService
    s = Settings(prometheus_url="http://prom:9090")
    tool = MonitoringTool(s)
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["q"] = (params or {}).get("query", "")
        v = 0.012 if "status=~" in captured["q"] else (125.4 if "http_requests_total" in captured["q"]
                                                       else (0.73 if "container_cpu" in captured["q"] else 0.68))
        return httpx.Response(200, request=httpx.Request("GET", str(url)),
                              json={"status": "success", "data": {"result": [{"metric": {}, "value": [0, str(v)]}]}})
    monkeypatch.setattr(httpx, "get", fake_get)
    r = tool.query_workload("order-service")
    assert r.success is True
    assert r.data["service"] == "order-service"
    assert r.data["qps"] == 125.4
    assert r.tool == "query_workload"


def test_query_workload_unconfigured_returns_failure():
    tool = MonitoringTool(Settings())
    r = tool.query_workload("order-service")
    assert not r.success
    assert "未配置" in r.error
    assert r.tool == "query_workload"


def test_query_workload_exposed_via_adapter():
    from app.agent.agent import adapt_tools
    tool = MonitoringTool(Settings(prometheus_url="http://x"))
    adapters = adapt_tools([tool])
    assert "query_workload" in {a.name for a in adapters}


def test_build_tools_returns_four_tools():
    tools = build_tools(Settings())
    names = {t.__class__.__name__ for t in tools}
    assert names == {"MonitoringTool", "LoggingTool", "CMDBTool", "KnowledgeTool"}
