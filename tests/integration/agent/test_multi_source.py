import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ScriptedDiagnosisModel, assistant_tool_calls, tool_response_text  # noqa: E402

from app.agent.agent import investigate  # noqa: E402
from app.incident.model import IncidentStatus as S  # noqa: E402
from app.incident.service import IncidentService  # noqa: E402
from app.tools.factory import build_tools  # noqa: E402


@pytest.mark.integration
def test_multi_source_prometheus_and_loki_evidence(settings_l1, monkeypatch):
    plan = [
        {"name": "query_workload", "arguments": {"service": "order-service"}},
        {"name": "search_logs", "arguments": {"query": '{app="order-service"}'}},
        {"name": "submit_rca_result", "arguments": {
            "root_cause": "order-service 500 错误（脚本预置，不评推理）",
            "confidence": 0.9,
            "evidence": [
                {"source": "prometheus", "fact": "真实 workload qps 非空"},
                {"source": "loki", "fact": "日志含 order-service 错误（seed）"},
            ],
            "hypotheses": ["依赖故障", "发布回归"],
        }},
        {"name": "final_answer", "arguments": {"answer": "调查完成（双源）"}},
    ]
    model = ScriptedDiagnosisModel(plan)
    monkeypatch.setattr("app.llm.provider.LiteLLMProvider.make_agent_model", lambda self: model)

    svc = IncidentService()
    inc = svc.create("服务异常", "order-service", "critical", target="order-service")
    investigate(settings_l1, svc, inc.incident_id, tools=build_tools(settings_l1))

    got = svc.get(inc.incident_id)
    assert got.status == S.ROOT_CAUSE_FOUND
    assert got.failure_code is None
    assert got.rca_source == "tool"
    # 证据集合：>=2 条且 source 集合恰为两源（不允许同源冒充双源）
    assert len(got.rca.evidence) >= 2
    assert {e.source for e in got.rca.evidence} == {"prometheus", "loki"}

    # 工具调用顺序
    names = assistant_tool_calls(model)
    assert names.index("query_workload") < names.index("search_logs") < names.index("submit_rca_result")
    # 消费层：第 1 工具(query_workload)响应含 qps；第 2 工具(search_logs)响应含 Loki seed 日志值
    assert "qps" in tool_response_text(model, 1)
    assert "upstream timeout" in tool_response_text(model, 2)
