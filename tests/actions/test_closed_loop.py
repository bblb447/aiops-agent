import pytest
from app.actions.approval import ApprovalStore
from app.actions.audit import AuditLog
from app.actions.executor import ActionExecutor
from app.actions.flow import ActionFlow
from app.actions.gateway import ActionGateway
from app.actions.model import AdmissionOutcome, ExecutionOutcome, TargetDescriptor
from app.actions.registry import default_registry
from app.incident.model import RCAResult
from app.incident.service import IncidentService
from app.auth.model import ActorContext, AuthenticatedPrincipal, AuthMethod


def _actor(pid="ops"):
    return ActorContext.from_principal(AuthenticatedPrincipal(pid, AuthMethod.DEV, {}))


_SVC = ActorContext("executor-service", AuthMethod.SERVICE)


class _Resolver:
    def __init__(self, d):
        self._d = d

    def resolve(self, t):
        return self._d.get(t)


class _Backend:
    def __init__(self):
        self.calls = 0

    def execute(self, a, t, p):
        self.calls += 1
        return ExecutionOutcome.EXECUTED


def _incident(eligible=True):
    svc = IncidentService()
    inc = svc.create("t", "order-service", "critical")
    if eligible:
        inc.rca = RCAResult(verdict="ROOT_CAUSE_FOUND", root_cause="r", confidence=0.9,
                            evidence=[{"source": "prometheus", "fact": "f"}])
        inc.verdict = inc.rca.verdict
        inc.status = "ROOT_CAUSE_FOUND"
    return inc


def _flow(inc, desc):
    store = ApprovalStore()
    be = _Backend()
    audit = AuditLog()
    gw = ActionGateway(default_registry(), _Resolver(desc), lambda iid: inc)
    return ActionFlow(gw, store, ActionExecutor(be, default_registry(), store, _SVC), audit), store, be, audit


_DEP = {"dep-1": TargetDescriptor("deployment", "staging", 3)}
_NS = {"ns-1": TargetDescriptor("namespace", "prod", None)}
_SCALE = {"action_id": "scale_deployment", "target": "dep-1",
          "parameters": {"namespace": "prod", "deployment": "d", "replicas": 2}}


def test_full_closed_loop_approval_executed_then_audit_verifies():
    flow, store, be, audit = _flow(_incident(), _DEP)
    r = flow.propose("i", _SCALE, _actor())
    assert r.status == "AWAITING_APPROVAL" and be.calls == 0
    r2 = flow.decide_approval(r.approval_id, True, _actor())
    assert r2.execution.outcome is ExecutionOutcome.EXECUTED and be.calls == 1
    types = [e.event_type for e in audit.events()]
    assert types == ["PROPOSED", "RISK_EVALUATED", "POLICY_DECIDED", "APPROVAL_REQUESTED",
                     "APPROVED", "EXECUTION_ACCEPTED", "EXECUTED"]
    assert audit.verify() is True


def test_reverse_critical_denied_no_approval_no_execution():
    flow, store, be, audit = _flow(_incident(), _NS)
    r = flow.propose("i", {"action_id": "delete_namespace", "target": "ns-1",
                           "parameters": {"namespace": "ns-1"}}, _actor())
    assert r.status == "DENIED" and r.approval_id is None and be.calls == 0
    types = [e.event_type for e in audit.events()]
    assert "EXECUTED" not in types and "APPROVAL_REQUESTED" not in types


def test_reverse_tampered_fingerprint_admission_rejected_no_mutation():
    flow, store, be, audit = _flow(_incident(), _DEP)
    r = flow.propose("i", _SCALE, _actor())
    store.approve(r.approval_id, actor="ops")
    from dataclasses import replace
    from app.actions.executor import SealedOrder
    ap = store.get(r.approval_id)
    tampered = replace(ap.snapshot, proposal_fingerprint="0" * 64)
    # 直接构造（绕过 seal，无 capability）→ 拒；底层一次都不执行。
    res = ActionExecutor(be, default_registry(), store, _SVC).execute(
        SealedOrder(snapshot=tampered, approval_id=r.approval_id))
    assert res.admission is AdmissionOutcome.REJECTED and be.calls == 0


def test_reverse_expired_approval_no_execution():
    flow, store, be, audit = _flow(_incident(), _DEP)
    r = flow.propose("i", _SCALE, _actor())
    store.expire(r.approval_id)
    from app.actions.executor import seal as _seal
    with pytest.raises(ValueError):
        _seal(store.get(r.approval_id).snapshot, store, r.approval_id)
    assert be.calls == 0
