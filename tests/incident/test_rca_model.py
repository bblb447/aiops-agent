"""RCAResult 模型约束测试：结构化 RCA 的字段级规则。"""
import pytest
from pydantic import ValidationError

from app.incident.model import EvidenceItem, RCAResult, Incident


def test_rcarresult_valid():
    r = RCAResult(
        root_cause="deployment_regression",
        confidence=0.87,
        evidence=[EvidenceItem(source="prometheus", fact="CPU 从 42% 涨到 95%")],
    )
    assert r.root_cause == "deployment_regression"
    assert r.confidence == 0.87
    assert r.evidence[0].source == "prometheus"
    assert r.hypotheses == []
    assert r.recommendations == []
    assert r.summary is None


def test_rcarresult_minimal_fields_only():
    # evidence 至少 1 条且 source/fact 非空；hypotheses/recommendations 可省略。
    r = RCAResult(
        root_cause="disk_full",
        confidence=0.95,
        evidence=[{"source": "node_exporter", "fact": "disk usage 99%"}],
    )
    assert r.root_cause == "disk_full"


def test_rcarresult_rejects_empty_evidence():
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=0.9, evidence=[])


def test_rcarresult_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=1.5, evidence=[{"source": "s", "fact": "f"}])
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=-0.1, evidence=[{"source": "s", "fact": "f"}])


def test_incident_has_rca_and_failure_code_defaults():
    inc = Incident(incident_id="INC-00001", title="CPU 高", service="order-service")
    assert inc.rca is None
    assert inc.failure_code is None


def test_incident_stores_rca():
    r = RCAResult(
        root_cause="deployment_regression",
        confidence=0.87,
        evidence=[{"source": "prometheus", "fact": "CPU 涨"}],
    )
    inc = Incident(incident_id="INC-00001", title="CPU 高", service="order-service", rca=r)
    assert inc.rca is not None
    assert inc.rca.root_cause == "deployment_regression"
