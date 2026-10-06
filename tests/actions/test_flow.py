from app.actions.approval import ApprovalStore
from app.actions.audit import AuditLog
from app.actions.executor import ActionExecutor
from app.actions.flow import ActionFlow
from app.actions.gateway import ActionGateway
from app.actions.model import ExecutionOutcome, TargetDescriptor
from app.actions.registry import default_registry
from app.incident.model import RCAResult
from app.incident.service import IncidentService
from app.auth.model import ActorContext, AuthenticatedPrincipal, AuthMethod


def _actor(pid="ops"):
    return ActorContext.from_principal(AuthenticatedPrincipal(pid, AuthMethod.DEV, {}))


_SVC = ActorContext("executor-service", AuthMethod.SERVICE)


class _Resolver:
    def __init__(self, desc):
        self._desc = desc

    def resolve(self, target):
        return self._desc.get(target)


class _Backend:
    def __init__(self):
        self.calls = 0

    def execute(self, action_id, target_descriptor, parameters):
        self.calls += 1
        return ExecutionOutcome.EXECUTED


def _eligible_incident():
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    inc.rca = RCAResult(verdict="ROOT_CAUSE_FOUND", root_cause="r", confidence=0.9,
                        evidence=[{"source": "prometheus", "fact": "CPU 95%"}])
    inc.verdict = inc.rca.verdict
    inc.status = "ROOT_CAUSE_FOUND"
    return inc


_PROD = {"pod-1": TargetDescriptor("pod", "staging", 3)}
_DEP = {"dep-1": TargetDescriptor("deployment", "staging", 3)}
_NS = {"ns-1": TargetDescriptor("namespace", "prod", None)}
_ACTOR = _actor()


def _flow(inc, desc=None):
    store = ApprovalStore()
    backend = _Backend()
    audit = AuditLog()
    gw = ActionGateway(default_registry(), _Resolver(desc or _PROD), lambda iid: inc)
    ex = ActionExecutor(backend, default_registry(), store, _SVC)
    return ActionFlow(gw, store, ex, audit), store, backend, audit


def test_allow_path_executes_and_audits_in_order():
    flow, _, backend, audit = _flow(_eligible_incident())
    r = flow.propose("i", {"action_id": "restart_pod", "target": "pod-1",
                           "parameters": {"namespace": "prod", "pod": "pod-1"}}, _ACTOR)
    assert r.execution is not None and r.execution.outcome is ExecutionOutcome.EXECUTED
    assert backend.calls == 1
    types = [e.event_type for e in audit.events()]
    assert types[:3] == ["PROPOSED", "RISK_EVALUATED", "POLICY_DECIDED"]
    assert "EXECUTION_ACCEPTED" in types and "EXECUTED" in types
    assert "APPROVAL_REQUESTED" not in types and "APPROVED" not in types
    assert audit.verify() is True


def test_approval_required_path_yields_awaiting():
    flow, store, backend, audit = _flow(_eligible_incident(), desc=_DEP)
    r = flow.propose("i", {"action_id": "scale_deployment", "target": "dep-1",
                           "parameters": {"namespace": "prod", "deployment": "d",
                                          "replicas": 2}}, _ACTOR)
    assert r.approval_id and r.execution is None
    assert backend.calls == 0
    assert "APPROVAL_REQUESTED" in [e.event_type for e in audit.events()]


def test_decide_approval_executes_bound_snapshot_without_redecision():
    flow, store, backend, audit = _flow(_eligible_incident(), desc=_DEP)
    r = flow.propose("i", {"action_id": "scale_deployment", "target": "dep-1",
                           "parameters": {"namespace": "prod", "deployment": "d",
                                          "replicas": 2}}, _ACTOR)
    r2 = flow.decide_approval(r.approval_id, True, _ACTOR)
    assert r2.execution is not None and r2.execution.outcome is ExecutionOutcome.EXECUTED
    assert backend.calls == 1
    assert "APPROVED" in [e.event_type for e in audit.events()]
    assert audit.verify() is True


def test_decide_approval_reject_no_execution():
    flow, store, backend, audit = _flow(_eligible_incident(), desc=_DEP)
    r = flow.propose("i", {"action_id": "scale_deployment", "target": "dep-1",
                           "parameters": {"namespace": "prod", "deployment": "d",
                                          "replicas": 2}}, _ACTOR)
    r2 = flow.decide_approval(r.approval_id, False, _ACTOR)
    assert r2.execution is None and backend.calls == 0
    assert "REJECTED" in [e.event_type for e in audit.events()]


def test_critical_denied_no_approval_no_execution():
    flow, store, backend, audit = _flow(_eligible_incident(), desc=_NS)
    r = flow.propose("i", {"action_id": "delete_namespace", "target": "ns-1",
                           "parameters": {"namespace": "ns-1"}}, _ACTOR)
    assert r.approval_id is None and backend.calls == 0
    assert "APPROVAL_REQUESTED" not in [e.event_type for e in audit.events()]


def test_audit_attribution_matrix():
    flow, store, backend, audit = _flow(_eligible_incident(), desc=_DEP)
    r = flow.propose("i", {"action_id": "scale_deployment", "target": "dep-1",
                           "parameters": {"namespace": "prod", "deployment": "d", "replicas": 2}},
                     _actor("alice"))
    flow.decide_approval(r.approval_id, True, _actor("bob"))
    by = {e.event_type: e.principal_id for e in audit.events()}
    assert by["PROPOSED"] == "alice"
    assert by["RISK_EVALUATED"] == "alice"
    assert by["POLICY_DECIDED"] == "alice"
    assert by["APPROVAL_REQUESTED"] == "alice"
    assert by["APPROVED"] == "bob"
    assert by["EXECUTION_ACCEPTED"] == "executor-service"
    assert by["EXECUTED"] == "executor-service"


def test_gateway_reject_attributed_to_proposer_not_executor():
    flow, store, backend, audit = _flow(_eligible_incident(), desc=_PROD)
    flow.propose("i", {"action_id": "unknown", "target": "pod-1"}, _actor("alice"))
    rejected = [e for e in audit.events() if e.event_type == "EXECUTION_REJECTED"]
    assert rejected and all(e.principal_id == "alice" for e in rejected)
