import pytest
from app.actions.approval import ApprovalStore
from app.actions.context import V1DecisionContext
from app.actions.executor import ActionExecutor, seal
from app.actions.model import (
    AdmissionOutcome, DecisionSnapshot, ExecutionOutcome, PolicyDecision, RiskLevel,
    TargetDescriptor)
from app.actions.registry import default_registry
from app.auth.model import ActorContext, AuthMethod

_SVC = ActorContext("executor-service", AuthMethod.SERVICE)

_CTX = V1DecisionContext(version="v1_decision_context@1", incident_id="i",
                         status="ROOT_CAUSE_FOUND", verdict="ROOT_CAUSE_FOUND",
                         confidence=0.9, evidence=(), failure_code=None)


class _Backend:
    def __init__(self, outcome=ExecutionOutcome.EXECUTED, exc=None):
        self._outcome = outcome
        self._exc = exc
        self.calls = 0

    def execute(self, action_id, target_descriptor, parameters):
        self.calls += 1
        if self._exc:
            raise self._exc
        return self._outcome


def _snap(action_id="restart_pod", policy=PolicyDecision.ALLOW, *, params=None, fp="f" * 64,
          registry_version="actions@1", target=None):
    return DecisionSnapshot(
        context=_CTX, action_id=action_id,
        target_descriptor=target or TargetDescriptor("pod", "staging", 3),
        parameters=params or {"namespace": "prod", "pod": "p1"},
        registry_version=registry_version, final_risk=RiskLevel.MEDIUM,
        policy_decision=policy, proposal_fingerprint=fp)


def _recompute(snap):
    from dataclasses import replace
    from app.actions.gateway import proposal_fingerprint
    fp = proposal_fingerprint(snap.context, snap.action_id, snap.target_descriptor,
                              dict(snap.parameters), snap.final_risk, snap.policy_decision,
                              snap.registry_version)
    return replace(snap, proposal_fingerprint=fp)


def _good_snap(**kw):
    return _recompute(_snap(**kw))


def _seal_allow(store):
    return seal(_good_snap(), store, None)


def test_seal_allow_path_requires_allow_policy():
    with pytest.raises(ValueError):
        seal(_snap(policy=PolicyDecision.APPROVAL_REQUIRED), ApprovalStore(), None)


def test_seal_requires_approved_and_matching_approval():
    store = ApprovalStore()
    ap = store.request(_good_snap(policy=PolicyDecision.APPROVAL_REQUIRED))
    with pytest.raises(ValueError):
        seal(_good_snap(policy=PolicyDecision.APPROVAL_REQUIRED), store, ap.approval_id)  # 未批准
    store.approve(ap.approval_id, actor="ops")
    with pytest.raises(ValueError):
        seal(_snap(policy=PolicyDecision.APPROVAL_REQUIRED, fp="e" * 64), store, ap.approval_id)  # 指纹不符


def test_allow_path_executes():
    res = ActionExecutor(_Backend(), default_registry(), ApprovalStore(), _SVC).execute(
        _seal_allow(ApprovalStore()))
    assert res.admission is AdmissionOutcome.ACCEPTED
    assert res.outcome is ExecutionOutcome.EXECUTED


def test_tampered_snapshot_content_rejected():
    store = ApprovalStore()
    order = seal(_snap(params={"namespace": "prod", "pod": "p2"}, fp="f" * 64), store, None)
    backend = _Backend()
    res = ActionExecutor(backend, default_registry(), store, _SVC).execute(order)
    assert res.admission is AdmissionOutcome.REJECTED
    assert res.outcome is None and backend.calls == 0


def test_forged_order_without_capability_rejected():
    from app.actions.executor import SealedOrder
    forged = SealedOrder(snapshot=_snap(), approval_id=None)
    backend = _Backend()
    res = ActionExecutor(backend, default_registry(), ApprovalStore(), _SVC).execute(forged)
    assert res.admission is AdmissionOutcome.REJECTED and backend.calls == 0


def test_critical_sealed_order_rejected_by_executor():
    crit = _recompute(_snap(action_id="delete_namespace", policy=PolicyDecision.ALLOW,
                            params={"namespace": "ns"},
                            target=TargetDescriptor("namespace", "prod", None)))
    order = seal(crit, ApprovalStore(), None)
    backend = _Backend()
    res = ActionExecutor(backend, default_registry(), ApprovalStore(), _SVC).execute(order)
    assert res.admission is AdmissionOutcome.REJECTED and backend.calls == 0


def test_registry_version_mismatch_rejected():
    order = seal(_recompute(_snap(registry_version="actions@999")), ApprovalStore(), None)
    backend = _Backend()
    res = ActionExecutor(backend, default_registry(), ApprovalStore(), _SVC).execute(order)
    assert res.admission is AdmissionOutcome.REJECTED and backend.calls == 0


def test_backend_timeout_and_failure_mapping():
    order = _seal_allow(ApprovalStore())
    t = ActionExecutor(_Backend(exc=TimeoutError()), default_registry(), ApprovalStore(), _SVC).execute(order)
    assert t.admission is AdmissionOutcome.ACCEPTED and t.outcome is ExecutionOutcome.TIMEOUT
    f = ActionExecutor(_Backend(exc=ValueError("boom")), default_registry(), ApprovalStore(), _SVC).execute(order)
    assert f.admission is AdmissionOutcome.ACCEPTED and f.outcome is ExecutionOutcome.FAILED


def test_backend_noop_passthrough():
    order = _seal_allow(ApprovalStore())
    r = ActionExecutor(_Backend(outcome=ExecutionOutcome.NOOP), default_registry(), ApprovalStore(), _SVC).execute(order)
    assert r.outcome is ExecutionOutcome.NOOP


def test_approval_path_requires_approved_for_execution():
    store = ApprovalStore()
    ap = store.request(_good_snap(policy=PolicyDecision.APPROVAL_REQUIRED))
    store.approve(ap.approval_id, actor="ops")
    order = seal(_good_snap(policy=PolicyDecision.APPROVAL_REQUIRED), store, ap.approval_id)
    r = ActionExecutor(_Backend(), default_registry(), store, _SVC).execute(order)
    assert r.admission is AdmissionOutcome.ACCEPTED and r.outcome is ExecutionOutcome.EXECUTED


def test_service_principal_is_actor_context_not_bare_string():
    ex = ActionExecutor(_Backend(), default_registry(), ApprovalStore(), _SVC)
    assert isinstance(ex.service_principal, ActorContext)
    assert ex.service_principal.auth_method is AuthMethod.SERVICE
    assert ex.service_principal.principal_id == "executor-service"
