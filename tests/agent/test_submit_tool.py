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
        evidence=["这是错误格式", {"source": "prometheus", "fact": "f"}],
    )
    assert r.success is False
    assert tool.last_validation_code == "MISSING_EVIDENCE"
    assert tool.rca_result is None


def test_submit_rejects_empty_root_cause():
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(root_cause="  ", confidence=0.8,
                               evidence=[{"source": "prometheus", "fact": "f"}])
    assert r.success is False
    assert tool.last_validation_code == "MISSING_EVIDENCE"


def test_submit_rejects_bad_confidence():
    for bad in [None, 1.5, -0.1]:
        _, tool = _tool("INC-1")
        r = tool.submit_rca_result(root_cause="x", confidence=bad,
                                   evidence=[{"source": "prometheus", "fact": "f"}])
        assert r.success is False
        assert tool.last_validation_code == "LOW_CONFIDENCE"


def test_submit_lock_after_success():
    # 成功提交后，后续失败不得清空已锁存的 rca_result。
    _, tool = _tool("INC-1")
    ok = tool.submit_rca_result(root_cause="regression", confidence=0.9,
                                evidence=[{"source": "prometheus", "fact": "f"}])
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
                               evidence=[{"source": "prometheus", "fact": "99%"}])
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


# ===== V1.7 verdict-aware（spec §6：submit 通道） =====


def test_submit_no_anomaly_success():
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service")
    tool = SubmitRCATool(svc, inc.incident_id)
    r = tool.submit_rca_result(
        verdict="NO_ANOMALY", root_cause="", confidence=0.96,
        evidence=[{"source": "prometheus", "fact": "实际 CPU 6.8% 低于阈值 80%"}])
    assert r.success is True
    assert tool.rca_result.verdict.value == "NO_ANOMALY"
    assert tool.rca_result.root_cause is None


def test_submit_no_anomaly_rejects_pseudo_root_cause():
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(
        verdict="NO_ANOMALY", root_cause="metric_alert_false_positive",
        confidence=0.96, evidence=[{"source": "prometheus", "fact": "f"}])
    assert r.success is False
    assert tool.last_validation_code == "MISSING_EVIDENCE"
    assert tool.rca_result is None


def test_submit_inconclusive_explicit_success():
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(
        verdict="INCONCLUSIVE", root_cause="", confidence=None,
        evidence=[{"source": "prometheus", "fact": "指标有波动，无法定根因"}])
    assert r.success is True
    assert tool.rca_result.verdict.value == "INCONCLUSIVE"


def test_submit_legacy_without_verdict_derives_root_cause_found():
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(root_cause="deployment_regression", confidence=0.87,
                               evidence=[{"source": "prometheus", "fact": "CPU 涨"}])
    assert r.success is True
    assert tool.rca_result.verdict.value == "ROOT_CAUSE_FOUND"


def test_invalid_source_plus_bad_confidence_still_low_confidence():
    # spec §4.3：F3 不改变既有 precedence —— 同时含 source 错误与 confidence 错误时，
    # rca_validation_code 因 confidence 错误优先仍返回 LOW_CONFIDENCE。
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(root_cause="x", confidence=1.5,
                               evidence=[{"source": "query_workload", "fact": "f"}])
    assert r.success is False
    assert tool.last_validation_code == "LOW_CONFIDENCE"


def test_invalid_source_plus_missing_confidence_is_missing_evidence():
    # spec §4.3（2026-09-21 裁定）：字段级 source 校验失败会抑制 RCAResult 的
    # mode="after" 模型级校验，故「非法 source + 缺 confidence」落 MISSING_EVIDENCE，
    # 而非模型级校验本会给出的 LOW_CONFIDENCE。与既有 fact 空值语义同构。
    _, tool = _tool("INC-1")
    r = tool.submit_rca_result(root_cause="x", confidence=None,
                               evidence=[{"source": "query_workload", "fact": "f"}])
    assert r.success is False
    assert tool.last_validation_code == "MISSING_EVIDENCE"
