import pytest
from app.actions.context import build_context
from app.actions.gateway import ActionGateway, proposal_fingerprint
from app.actions.model import GatewayOutcome, PolicyDecision, RiskLevel, TargetDescriptor
from app.actions.registry import default_registry
from app.incident.model import RCAResult
from app.incident.service import IncidentService


class _Resolver:
    def __init__(self, desc):
        self._desc = desc

    def resolve(self, target):
        return self._desc.get(target)


def _incident(eligible=True):
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    if eligible:
        inc.rca = RCAResult(verdict="ROOT_CAUSE_FOUND", root_cause="版本回归", confidence=0.9,
                            evidence=[{"source": "prometheus", "fact": "CPU 95%"}])
        inc.verdict = inc.rca.verdict
        inc.status = "ROOT_CAUSE_FOUND"
    return inc


def _gateway(desc, inc):
    return ActionGateway(default_registry(), _Resolver(desc), lambda iid: inc)


_POD = TargetDescriptor("pod", "staging", 3)
_POD_PARAMS = {"namespace": "prod", "pod": "pod-1"}
_ACTOR = {"user": "ops"}


def test_unknown_action_rejected():
    g = _gateway({"pod-1": _POD}, _incident())
    r = g.evaluate("i", {"action_id": "nope", "target": "pod-1"}, actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.REJECT


def test_non_dict_payload_rejected():
    # payload 类型 fail-closed：非 dict 一律拒，不猜测。
    g = _gateway({"pod-1": _POD}, _incident())
    r = g.evaluate("i", ["not", "a", "dict"], actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.REJECT


def test_unknown_top_level_key_rejected():
    # I2 fail-closed：顶层只允许 allowlist 四键；未知名（即使无害）也拒。
    g = _gateway({"pod-1": _POD}, _incident())
    r = g.evaluate("i", {"action_id": "restart_pod", "target": "pod-1",
                         "parameters": _POD_PARAMS, "execute_now": True}, actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.REJECT
    assert "execute_now" in r.reason


def test_forbidden_authority_field_rejected():
    g = _gateway({"pod-1": _POD}, _incident())
    r = g.evaluate("i", {"action_id": "restart_pod", "target": "pod-1",
                         "parameters": _POD_PARAMS, "risk_level": "LOW"}, actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.REJECT and "risk_level" in r.reason


def test_self_reported_eligibility_cannot_grant():
    g = _gateway({"pod-1": _POD}, _incident(eligible=False))
    r = g.evaluate("i", {"action_id": "restart_pod", "target": "pod-1",
                         "parameters": _POD_PARAMS, "eligibility": True}, actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.REJECT


def test_invalid_target_rejected():
    g = _gateway({}, _incident())
    r = g.evaluate("i", {"action_id": "restart_pod", "target": "ghost"}, actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.REJECT


def test_bad_parameter_rejected():
    g = _gateway({"pod-1": _POD}, _incident())
    r = g.evaluate("i", {"action_id": "restart_pod", "target": "pod-1",
                         "parameters": {"namespace": "prod", "bogus": 1}}, actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.REJECT


def test_ineligible_incident_rejected():
    g = _gateway({"pod-1": _POD}, _incident(eligible=False))
    r = g.evaluate("i", {"action_id": "restart_pod", "target": "pod-1",
                         "parameters": _POD_PARAMS}, actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.REJECT
    assert "eligible" in r.reason.lower() or "verdict" in r.reason


def test_low_write_staging_routes_allow_with_snapshot():
    g = _gateway({"pod-1": _POD}, _incident())
    r = g.evaluate("i", {"action_id": "restart_pod", "target": "pod-1",
                         "parameters": _POD_PARAMS}, actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.ALLOW
    assert r.final_risk is RiskLevel.MEDIUM
    assert r.policy_decision is PolicyDecision.ALLOW
    assert len(r.proposal_fingerprint) == 64
    # P2→P3 seam：canonical 快照可用，P3 无需再读原始 proposal。
    assert r.snapshot is not None
    assert r.snapshot.action_id == "restart_pod"
    assert r.snapshot.target_descriptor == _POD
    assert r.snapshot.proposal_fingerprint == r.proposal_fingerprint
    assert dict(r.snapshot.parameters) == _POD_PARAMS
    # context 为完整 V1DecisionContext 快照（不是仅 version/id）。
    assert r.snapshot.context.version == "v1_decision_context@1"
    assert r.snapshot.context.verdict == "ROOT_CAUSE_FOUND"


def test_reject_has_no_snapshot():
    g = _gateway({}, _incident())
    r = g.evaluate("i", {"action_id": "restart_pod", "target": "ghost"}, actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.REJECT and r.snapshot is None


def test_critical_routes_deny():
    g = _gateway({"ns-1": TargetDescriptor("namespace", "prod", None)}, _incident())
    r = g.evaluate("i", {"action_id": "delete_namespace", "target": "ns-1",
                         "parameters": {"namespace": "ns-1"}}, actor_context=_ACTOR)
    assert r.outcome is GatewayOutcome.DENY


def test_fingerprint_changes_with_final_risk():
    ctx = build_context(_incident())
    fp1 = proposal_fingerprint(ctx, "restart_pod", _POD, _POD_PARAMS, RiskLevel.MEDIUM, PolicyDecision.ALLOW, "actions@1")
    fp2 = proposal_fingerprint(ctx, "restart_pod", _POD, _POD_PARAMS, RiskLevel.HIGH, PolicyDecision.ALLOW, "actions@1")
    assert fp1 != fp2 and len(fp1) == 64


def test_fingerprint_changes_with_parameters_context_and_registry_version():
    ctx = build_context(_incident())
    base = proposal_fingerprint(ctx, "restart_pod", _POD, _POD_PARAMS, RiskLevel.MEDIUM, PolicyDecision.ALLOW, "actions@1")
    assert base != proposal_fingerprint(ctx, "restart_pod", _POD, {"namespace": "other", "pod": "pod-1"},
                                        RiskLevel.MEDIUM, PolicyDecision.ALLOW, "actions@1")
    assert base != proposal_fingerprint(ctx, "restart_pod", _POD, _POD_PARAMS, RiskLevel.MEDIUM, PolicyDecision.ALLOW, "actions@2")
    assert base != proposal_fingerprint(build_context(_incident(eligible=False)), "restart_pod", _POD,
                                        _POD_PARAMS, RiskLevel.MEDIUM, PolicyDecision.ALLOW, "actions@1")
