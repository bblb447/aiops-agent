"""E2E RCA 场景测试：真实 Agent + 真实工具 + fixture 数据，验证诊断闭环。

固定故障场景：server-01 CPU 95.2%（阈值 80），命中内存泄漏 runbook。
脚本化模型按计划产出工具调用（query_metric -> search_runbook -> submit_rca_result -> final_answer），
证明 Alert(Incident) -> Agent -> Tools -> 结构化 RCA 全链路可用。
"""
import json

import httpx

from smolagents.models import ChatMessage, MessageRole, Model

from app.agent.agent import investigate
from app.config import Settings
from app.incident.model import IncidentStatus as S
from app.incident.service import IncidentService
from app.tools.factory import build_tools


class _ScriptedDiagnosisModel(Model):
    """按计划依次产出工具调用，模拟一次带证据的诊断。"""

    def __init__(self, plan):
        super().__init__(model_id="scripted-diagnosis")
        self.plan = list(plan)
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        if self.plan:
            tc = self.plan.pop(0)
        else:
            tc = {"name": "final_answer", "arguments": {"answer": "兜底结论"}}
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=json.dumps({"name": tc["name"], "arguments": tc["arguments"]}, ensure_ascii=False),
        )


def _prometheus_fixture(url, params=None, timeout=None):
    if "/api/v1/query" in str(url):
        return httpx.Response(
            200,
            request=httpx.Request("GET", str(url)),
            json={
                "status": "success",
                "data": {"result": [{"metric": {"instance": "server-01"}, "value": [1710000000, "95.2"]}]},
            },
        )
    return httpx.Response(404, request=httpx.Request("GET", str(url)), json={})


def test_e2e_cpu_gc_release_scenario(monkeypatch, tmp_path):
    runbook = tmp_path / "memory-leak.md"
    runbook.write_text(
        "# 内存泄漏排查\n当服务内存持续上涨并伴随 Full GC 时，优先怀疑最近发布引入内存泄漏。",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.tools.knowledge.RUNBOOK_DIR", tmp_path)
    monkeypatch.setattr(httpx, "get", _prometheus_fixture)

    plan = [
        {"name": "query_metric", "arguments": {"metric": "cpu_usage", "target": "server-01"}},
        {"name": "search_runbook", "arguments": {"keyword": "内存泄漏"}},
        {"name": "submit_rca_result", "arguments": {
            "root_cause": "内存泄漏",
            "confidence": 0.85,
            "evidence": [
                {"source": "prometheus", "fact": "cpu_usage=95.2"},
                {"source": "runbook", "fact": "命中内存泄漏排查"},
            ],
            "hypotheses": ["内存泄漏", "流量突增"],
        }},
        {"name": "final_answer", "arguments": {"answer": "调查完成：根因内存泄漏"}},
    ]
    model = _ScriptedDiagnosisModel(plan)
    monkeypatch.setattr("app.llm.provider.LiteLLMProvider.make_agent_model", lambda self: model)

    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical",
                     target="server-01", observed_value=95.2, threshold=80)
    s = Settings(llm_api_key="sk-test", rag_enabled=False, prometheus_url="http://prom:9090")
    out = investigate(s, svc, inc.incident_id, tools=build_tools(s))

    got = svc.get(inc.incident_id)
    assert got.status == S.ROOT_CAUSE_FOUND
    assert got.failure_code is None
    assert got.rca is not None
    assert got.rca.root_cause == "内存泄漏"
    assert got.rca.confidence == 0.85
    assert got.rca.evidence[0].source == "prometheus"
    assert got.rca.hypotheses == ["内存泄漏", "流量突增"]
    # root_cause 由 rca 派生；final_answer 文本只是结束说明。
    assert got.root_cause == got.rca.root_cause
    assert "调查完成" in out
    # 证据闭环：第二次模型调用时对话已带回 query_metric 的实测值 95.2。
    tool_msgs = [m for m in model.calls[1] if m.role == MessageRole.TOOL_RESPONSE]
    assert any("95.2" in str(m.content) for m in tool_msgs)
    # timeline 记录了 Agent 结论。
    assert any("Agent 结论" in t.get("event", "") for t in got.timeline)
