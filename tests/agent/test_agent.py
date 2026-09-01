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
