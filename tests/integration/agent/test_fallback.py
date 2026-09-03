import json
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
def test_fallback_final_answer_rca_result(settings_l1, monkeypatch):
    final_text = (
        "调查完成：判断为负载异常。\n<rca_result>\n"
        + json.dumps({
            "root_cause": "order-service 负载异常（脚本预置，不评推理）",
            "confidence": 0.72,
            "evidence": [{"source": "prometheus", "fact": "真实 http_requests_total 可查"}],
            "hypotheses": ["负载异常"],
        }, ensure_ascii=False)
        + "\n</rca_result>"
    )
    plan = [
        {"name": "query_metric", "arguments": {"metric": "http_requests_total"}},
        {"name": "final_answer", "arguments": {"answer": final_text}},
    ]
    model = ScriptedDiagnosisModel(plan)
    monkeypatch.setattr("app.llm.provider.LiteLLMProvider.make_agent_model", lambda self: model)

    svc = IncidentService()
    inc = svc.create("服务异常", "order-service", "critical", target="order-service")
    investigate(settings_l1, svc, inc.incident_id, tools=build_tools(settings_l1))

    got = svc.get(inc.incident_id)
    assert got.status == S.ROOT_CAUSE_FOUND
    assert got.failure_code is None
    assert got.rca_source == "final_answer"
    assert got.rca.confidence == 0.72

    # submit 在整段工具调用轨迹中均未出现（非仅末次调用）
    assert "submit_rca_result" not in assistant_tool_calls(model)
    # 消费层：第 1 工具(query_metric) 响应含真实 series 标签 order-service（Prom 响应无指标名本身）
    assert "order-service" in tool_response_text(model, 1)
