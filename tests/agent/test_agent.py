from app.config import Settings
from app.incident.service import IncidentService
from app.incident.model import IncidentStatus as S
from app.agent.agent import investigate

class _FakeAgent:
    def __init__(self, tools=None, max_steps=None): self._tools = tools; self._max_steps = max_steps
    def run(self, prompt): return "根因: 最近发布导致版本回归，置信度 0.86"
    @property
    def tools(self): return self._tools
    @property
    def max_steps(self): return self._max_steps

class _NoConclusionAgent(_FakeAgent):
    def run(self, prompt): return ""

class _FailingAgent(_FakeAgent):
    def run(self, prompt):
        raise RuntimeError("LLM 网络超时")

def test_investigate_escalates_on_llm_failure(monkeypatch):
    svc = IncidentService()
    inc = svc.create("连接超时", "payment-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _FailingAgent(t, s.agent_max_steps))
    import pytest
    with pytest.raises(RuntimeError):
        investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.ESCALATED
    assert any("调查失败" in t.get("event", "") for t in got.timeline)
    assert got.root_cause is None

def test_adapter_forward_dispatches_to_tool(monkeypatch):
    # 覆盖适配器最高风险代码路径：_ToolAdapter.forward 动态派发 -> ToolResult
    # to_dict -> JSON 序列化，以及输入 schema 映射（metric/target）。
    import json
    import httpx
    from app.agent.agent import adapt_tools
    from app.tools.monitoring import MonitoringTool

    s = Settings(prometheus_url="http://127.0.0.1:9")
    tool = MonitoringTool(s)

    def fake_get(url, params=None, timeout=None):
        return httpx.Response(200, request=httpx.Request("GET", str(url)),
                              json={"status": "success", "data": {"result": [{"value": [0, "94.5"]}]}})
    monkeypatch.setattr(httpx, "get", fake_get)

    adapters = adapt_tools([tool])
    adapter = next(a for a in adapters if a.name == "query_metric")
    # 输入 schema 映射：metric/target 必须出现在 smolagents 的 inputs 里。
    assert {"metric", "target"} <= set(adapter.inputs)
    out = adapter.forward(metric="cpu_usage", target="srv")
    # 返回的是合法 JSON，且能解析出 Prometheus 的 data.data.result。
    parsed = json.loads(out)
    assert parsed["success"] is True
    assert parsed["tool"] == "query_metric"
    assert parsed["data"]["data"]["result"][0]["value"][1] == "94.5"


def test_investigate_transitions_to_root_cause(monkeypatch):
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _FakeAgent(t, s.agent_max_steps))
    out = investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    assert "版本回归" in out
    got = svc.get(inc.incident_id)
    assert got.status == S.ROOT_CAUSE_FOUND
    assert len(got.timeline) >= 3
    assert got.root_cause == out

def test_investigate_transitions_to_insufficient_evidence(monkeypatch):
    svc = IncidentService()
    inc = svc.create("无日志", "cart-service", "major")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _NoConclusionAgent(t, s.agent_max_steps))
    out = investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.INSUFFICIENT_EVIDENCE
    assert "结论" in str(got.timeline[-1].get("event", ""))

def test_build_agent_accepts_task4_tools():
    from smolagents import ToolCallingAgent
    from app.agent.agent import build_agent
    from app.tools.monitoring import MonitoringTool
    from app.tools.logging import LoggingTool
    from app.tools.cmdb import CMDBTool
    from app.tools.knowledge import KnowledgeTool
    s = Settings(llm_api_key="sk-test", llm_base_url="http://127.0.0.1:9999", llm_model="test-model")
    tools = [MonitoringTool(s), LoggingTool(s), CMDBTool(s), KnowledgeTool(s)]
    agent = build_agent(s, tools)
    assert isinstance(agent, ToolCallingAgent)
    assert {"query_metric", "search_logs", "get_service", "search_runbook"} <= set(agent.tools)
    assert agent.max_steps == s.agent_max_steps

def test_build_agent_accepts_empty_tools():
    from smolagents import ToolCallingAgent
    from app.agent.agent import build_agent
    s = Settings(llm_api_key="sk-test")
    agent = build_agent(s, [])
    assert isinstance(agent, ToolCallingAgent)
    assert agent.max_steps == s.agent_max_steps
    assert "final_answer" in agent.tools

def test_build_agent_tool_choice_auto():
    # DeepSeek 思考模式不接受 tool_choice="required"（BadRequestError），
    # 构造出的 LiteLLMModel 必须显式用 "auto"。
    from smolagents import LiteLLMModel
    from app.agent.agent import build_agent
    s = Settings(llm_api_key="sk-test")
    agent = build_agent(s, [])
    assert isinstance(agent.model, LiteLLMModel)
    assert agent.model.kwargs.get("tool_choice") == "auto"
