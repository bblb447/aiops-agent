from app.actions.context import (
    CONTEXT_VERSION, ContextEvidence, V1DecisionContext, build_context, is_eligible)
from app.incident.model import RCAResult
from app.incident.service import IncidentService


def _incident_with_rca():
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    inc.rca = RCAResult(
        verdict="ROOT_CAUSE_FOUND", root_cause="版本回归", confidence=0.86,
        evidence=[{"source": "prometheus", "fact": "CPU 95.2%"}])
    inc.verdict = inc.rca.verdict
    inc.status = "ROOT_CAUSE_FOUND"
    return inc


def test_build_context_projects_stable_fields_only():
    ctx = build_context(_incident_with_rca())
    assert ctx.version == CONTEXT_VERSION == "v1_decision_context@1"
    assert ctx.incident_id and ctx.status == "ROOT_CAUSE_FOUND"
    assert ctx.verdict == "ROOT_CAUSE_FOUND"
    assert ctx.confidence == 0.86
    assert ctx.evidence == (ContextEvidence(source="prometheus", fact="CPU 95.2%"),)
    assert not hasattr(ctx, "root_cause")   # 不暴露 legacy root_cause


def test_build_context_without_rca_is_empty_evidence():
    svc = IncidentService()
    inc = svc.create("x", "svc")
    ctx = build_context(inc)
    assert ctx.evidence == () and ctx.confidence is None and ctx.verdict is None


def test_is_eligible_only_when_root_cause_found():
    assert is_eligible(build_context(_incident_with_rca())) is True
    svc = IncidentService()
    assert is_eligible(build_context(svc.create("x", "svc"))) is False
