"""SubmitRCATool 测试：校验 + holder 语义，且工具不写 Incident。"""
from app.agent.submit_tool import SubmitRCATool
from app.incident.service import IncidentService
from app.incident.model import IncidentStatus as S
from app.tools.base import ToolResult


def _tool(iid):
    svc = IncidentService()
    return svc, SubmitRCATool(svc, iid)


def test_submit_valid_result():
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service")
    tool = SubmitRCATool(svc, inc.incident_id)
    r = tool.submit_rca_result(
        root_cause="deployment_regression",
        confidence=0.87,
        evidence=[{"source": "prometheus", "fact": "CPU 从 42% 涨到 95%"}],
    )
    assert r.success is True
    assert tool.submit_attempted is True
    assert tool.rca_result is not None
    assert tool.rca_result.root_cause == "deployment_regression"
    assert tool.validation_error is None
    assert tool.last_validation_code is None
    # 工具不写 Incident：rca/status 保持原样。
    got = svc.get(inc.incident_id)
    assert got.rca is None
    assert got.status == S.NEW


def test_submit_rejects_missing_evidence():
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(root_cause="x", confidence=0.8, evidence=[])
    assert r.success is False
    assert tool.rca_result is None
    assert tool.last_validation_code == "MISSING_EVIDENCE"
    assert tool.validation_error


def test_submit_rejects_evidence_item_missing_field():
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(
        root_cause="x", confidence=0.8,
        evidence=[{"source": "", "fact": "f"}],
    )
    assert r.success is False
    assert tool.last_validation_code == "MISSING_EVIDENCE"


def test_submit_rejects_non_dict_evidence_item():
    # evidence 元素若不是对象（如字符串/数字）不得抛异常，必须归 MISSING_EVIDENCE。
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(
        root_cause="x", confidence=0.8,
        evidence=["这是错误格式", {"source": "s", "fact": "f"}],
    )
    assert r.success is False
    assert tool.last_validation_code == "MISSING_EVIDENCE"
    assert tool.rca_result is None


def test_submit_rejects_empty_root_cause():
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(root_cause="  ", confidence=0.8,
                               evidence=[{"source": "s", "fact": "f"}])
    assert r.success is False
    assert tool.last_validation_code == "MISSING_EVIDENCE"


def test_submit_rejects_bad_confidence():
    for bad in [None, 1.5, -0.1]:
        _, tool = _tool("INC-1")
        r = tool.submit_rca_result(root_cause="x", confidence=bad,
                                   evidence=[{"source": "s", "fact": "f"}])
        assert r.success is False
        assert tool.last_validation_code == "LOW_CONFIDENCE"


def test_submit_lock_after_success():
    # 成功提交后，后续失败不得清空已锁存的 rca_result。
    _, tool = _tool("INC-1")
    ok = tool.submit_rca_result(root_cause="regression", confidence=0.9,
                                evidence=[{"source": "s", "fact": "f"}])
    assert ok.success is True
    locked = tool.rca_result
    bad = tool.submit_rca_result(root_cause="x", confidence=0.9, evidence=[])
    assert bad.success is False
    assert tool.rca_result is locked
    assert tool.last_validation_code == "MISSING_EVIDENCE"
    assert tool.validation_error


def test_submit_optional_fields_default():
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(root_cause="disk_full", confidence=0.95,
                               evidence=[{"source": "node_exporter", "fact": "99%"}])
    assert r.success is True
    assert tool.rca_result.hypotheses == []
    assert tool.rca_result.recommendations == []
    assert tool.rca_result.summary is None


def test_adapts_to_single_submit_rca_tool():
    # 经现有适配层后只暴露 submit_rca_result 一个工具方法，无多余公开方法泄漏。
    from app.agent.agent import adapt_tools
    svc, tool = _tool("INC-1")
    adapters = adapt_tools([tool])
    assert [a.name for a in adapters] == ["submit_rca_result"]
