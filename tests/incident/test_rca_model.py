"""RCAResult 模型约束测试：结构化 RCA 的字段级规则。"""
import pytest
from pydantic import ValidationError

from app.incident.model import (EvidenceItem, RCAResult, Incident,
                                InvestigationVerdict as V, rca_validation_code)
from app.incident.sources import EvidenceSource


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
        evidence=[{"source": "prometheus", "fact": "disk usage 99%"}],
    )
    assert r.root_cause == "disk_full"


def test_rcarresult_rejects_empty_evidence():
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=0.9, evidence=[])


def test_rcarresult_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=1.5, evidence=[{"source": "prometheus", "fact": "f"}])
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=-0.1, evidence=[{"source": "prometheus", "fact": "f"}])


def test_rcarresult_rejects_string_confidence():
    # 与 submit 工具路径一致：confidence 不接受字符串（P1 两通道校验统一）。
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence="0.8", evidence=[{"source": "prometheus", "fact": "f"}])


def test_rcarresult_rejects_bool_confidence():
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=True, evidence=[{"source": "prometheus", "fact": "f"}])


def test_incident_has_rca_and_failure_code_defaults():
    inc = Incident(incident_id="INC-00001", title="CPU 高", service="order-service")
    assert inc.rca is None
    assert inc.rca_source is None
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


def test_incident_rca_source_field():
    inc = Incident(incident_id="INC-00001", title="CPU 高", service="order-service",
                   rca_source="final_answer")
    assert inc.rca_source == "final_answer"


# ===== V1.7 Verdict Semantics（spec §4） =====


def test_incident_verdict_defaults_none():
    inc = Incident(incident_id="INC-00001", title="CPU 高", service="order-service")
    assert inc.verdict is None


def test_verdict_enum_has_no_escalated():
    assert {v.value for v in V} == {"ROOT_CAUSE_FOUND", "NO_ANOMALY", "INCONCLUSIVE"}


def test_legacy_root_cause_derives_root_cause_found():
    r = RCAResult(root_cause="deployment_regression", confidence=0.87,
                  evidence=[{"source": "prometheus", "fact": "CPU 95.2%"}])
    assert r.verdict == V.ROOT_CAUSE_FOUND


def test_no_anomaly_accepts_root_cause_none():
    r = RCAResult(verdict="NO_ANOMALY", root_cause=None, confidence=0.96,
                  evidence=[{"source": "prometheus", "fact": "实际 CPU 6.8% 低于阈值 80%"}])
    assert r.verdict == V.NO_ANOMALY
    assert r.root_cause is None


def test_no_anomaly_rejects_root_cause_present():
    with pytest.raises(ValidationError):
        RCAResult(verdict="NO_ANOMALY", root_cause="metric_alert_false_positive",
                  confidence=0.96, evidence=[{"source": "prometheus", "fact": "f"}])


def test_inconclusive_accepts_root_cause_none_no_confidence():
    r = RCAResult(verdict="INCONCLUSIVE", root_cause=None, confidence=None,
                  evidence=[{"source": "prometheus", "fact": "指标有波动但无法定根因"}])
    assert r.verdict == V.INCONCLUSIVE


def test_root_cause_found_rejects_missing_root_cause():
    with pytest.raises(ValidationError):
        RCAResult(verdict="ROOT_CAUSE_FOUND", root_cause=None, confidence=0.9,
                  evidence=[{"source": "prometheus", "fact": "f"}])


def test_root_cause_found_rejects_missing_confidence():
    with pytest.raises(ValidationError):
        RCAResult(verdict="ROOT_CAUSE_FOUND", root_cause="x", confidence=None,
                  evidence=[{"source": "prometheus", "fact": "f"}])


def test_verdict_none_root_cause_none_rejected():
    with pytest.raises(ValidationError):
        RCAResult(root_cause=None, confidence=0.9, evidence=[{"source": "prometheus", "fact": "f"}])


def test_blank_root_cause_treated_as_none():
    with pytest.raises(ValidationError):  # verdict 缺失 + root_cause 空白 → 拒绝
        RCAResult(root_cause="   ", confidence=0.9, evidence=[{"source": "prometheus", "fact": "f"}])


def test_rca_rejects_blank_evidence_content():
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=0.9,
                  evidence=[{"source": "prometheus", "fact": " "}])


# ===== F3 Evidence Provenance（spec §3 / §4）=====


@pytest.mark.parametrize("value", ["prometheus", "loki", "cmdb", "runbook"])
def test_evidence_source_accepts_canonical_values(value):
    r = RCAResult(root_cause="x", confidence=0.9,
                  evidence=[{"source": value, "fact": "f"}])
    assert r.evidence[0].source == value


@pytest.mark.parametrize("raw,expected", [
    ("Prometheus", EvidenceSource.PROMETHEUS),
    (" prometheus ", EvidenceSource.PROMETHEUS),
    ("PROMETHEUS", EvidenceSource.PROMETHEUS),
    ("  Loki", EvidenceSource.LOKI),
])
def test_evidence_source_normalizes_case_and_whitespace(raw, expected):
    r = RCAResult(root_cause="x", confidence=0.9,
                  evidence=[{"source": raw, "fact": "f"}])
    assert r.evidence[0].source is expected


@pytest.mark.parametrize("bad", [
    "Prometheus Server",                        # 语义变体
    "query_workload",                           # F3 观测到的真实污染（方法名形态）
    "query_workload(order-service)",
    "query_workload/_CountingMonitoring",       # L3 插桩子类泄漏形态
    "query_metric/Prometheus",
    "node_exporter",
    "s",
    "",
    "   ",
    123,
    None,
])
def test_evidence_source_rejects_non_canonical_values(bad):
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=0.9,
                  evidence=[{"source": bad, "fact": "f"}])


def test_invalid_source_maps_to_missing_evidence():
    with pytest.raises(ValidationError) as ei:
        RCAResult(root_cause="x", confidence=0.9,
                  evidence=[{"source": "query_workload", "fact": "f"}])
    assert rca_validation_code(ei.value) == "MISSING_EVIDENCE"


def test_invalid_source_message_contains_value_and_all_allowed_values():
    # §6 单一事实源：消息中的允许值必须覆盖 EvidenceSource 全部成员。
    # 新增枚举成员而消息未同步 → 本断言失败（硬编码副本会在此暴露）。
    with pytest.raises(ValidationError) as ei:
        RCAResult(root_cause="x", confidence=0.9,
                  evidence=[{"source": "query_workload", "fact": "f"}])
    msg = str(ei.value)
    assert "query_workload" in msg
    for s in EvidenceSource:
        assert s.value in msg


def test_blank_fact_still_rejected_without_source_check():
    # source 合法、fact 空白 → 仍须被拒（空值检查收窄到 fact 后保持有效）。
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=0.9,
                  evidence=[{"source": "prometheus", "fact": "  "}])


def test_evidence_item_missing_source_key_rejected():
    with pytest.raises(ValidationError):
        RCAResult(root_cause="x", confidence=0.9, evidence=[{"fact": "f"}])
