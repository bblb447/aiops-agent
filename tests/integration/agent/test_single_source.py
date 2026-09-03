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
def test_single_source_query_workload_to_tool_rca(settings_l1, monkeypatch):
    plan = [
        {"name": "query_workload", "arguments": {"service": "order-service"}},
        {"name": "submit_rca_result", "arguments": {
            "root_cause": "order-service 负载异常（脚本预置，不评推理）",
            "confidence": 0.85,
            "evidence": [
                {"source": "prometheus", "fact": "真实 workload 返回 qps/error_rate/cpu/memory 四字段"},
            ],
            "hypotheses": ["负载异常", "发布回归"],
        }},
        {"name": "final_answer", "arguments": {"answer": "调查完成（tool 通道）"}},
    ]
    model = ScriptedDiagnosisModel(plan)
    monkeypatch.setattr("app.llm.provider.LiteLLMProvider.make_agent_model", lambda self: model)

    svc = IncidentService()
    inc = svc.create("服务异常", "order-service", "critical", target="order-service")
    investigate(settings_l1, svc, inc.incident_id, tools=build_tools(settings_l1))

    got = svc.get(inc.incident_id)
    assert got.status == S.ROOT_CAUSE_FOUND
    assert got.failure_code is None
    assert got.rca is not None
    assert 0 <= got.rca.confidence <= 1
    assert got.rca_source == "tool"
    assert got.rca.evidence and got.rca.evidence[0].source == "prometheus"
    assert got.rca.evidence[0].fact

    # 工具调用顺序：query_workload 先于 submit_rca_result
    names = assistant_tool_calls(model)
    assert names.index("query_workload") < names.index("submit_rca_result")
    # 消费层：与 query_workload 对应（第 1 工具）的 TOOL_RESPONSE 含真实 qps 键
    assert "qps" in tool_response_text(model, 1)
