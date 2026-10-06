from app.actions.approval import ApprovalStore
from app.actions.audit import AuditLog
from app.actions.executor import ActionExecutor
from app.actions.flow import ActionFlow
from app.actions.gateway import ActionGateway
from app.actions.model import ExecutionOutcome, TargetDescriptor
from app.actions.registry import default_registry
from app.auth.authenticator import DevAuthenticator
from app.auth.model import ActorContext, AuthMethod
from app.incident.model import RCAResult
from app.incident.service import IncidentService
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SVC = ActorContext("executor-service", AuthMethod.SERVICE)


class _Resolver:
    def resolve(self, target):
        return {"pod-1": TargetDescriptor("pod", "staging", 3)}.get(target)


class _Backend:
    def execute(self, a, t, p):
        return ExecutionOutcome.EXECUTED


def _flow():
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    inc.rca = RCAResult(verdict="ROOT_CAUSE_FOUND", root_cause="r", confidence=0.9,
                        evidence=[{"source": "prometheus", "fact": "f"}])
    inc.verdict = inc.rca.verdict
    inc.status = "ROOT_CAUSE_FOUND"
    store = ApprovalStore()
    flow = ActionFlow(ActionGateway(default_registry(), _Resolver(), lambda iid: inc),
                      store, ActionExecutor(_Backend(), default_registry(), store, _SVC), AuditLog())
    return flow, store


def _client(authenticator=None):
    flow, store = _flow()
    from app.api.actions import create_actions_router
    app = FastAPI()
    app.include_router(create_actions_router(flow, authenticator or DevAuthenticator()))
    return TestClient(app), store


def test_propose_allow_executes():
    c, _ = _client()
    r = c.post("/api/v1/actions/propose", headers={"X-Dev-Principal": "ops"},
               json={"incident_id": "i", "action_id": "restart_pod", "target": "pod-1",
                     "parameters": {"namespace": "prod", "pod": "pod-1"}})
    assert r.status_code == 200
    assert r.json()["status"] == "EXECUTED"


def test_propose_unknown_action_rejected():
    c, _ = _client()
    r = c.post("/api/v1/actions/propose", headers={"X-Dev-Principal": "ops"},
               json={"incident_id": "i", "action_id": "nope", "target": "pod-1"})
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"


def test_propose_without_credentials_is_401():
    c, _ = _client()
    r = c.post("/api/v1/actions/propose", json={"incident_id": "i",
                                                "action_id": "restart_pod", "target": "pod-1"})
    assert r.status_code == 401


def test_approval_status_requires_auth():
    c, _ = _client()
    assert c.get("/api/v1/actions/approvals/xyz").status_code == 401


def test_authenticator_exception_is_fail_closed():
    class _Boom:
        def authenticate(self, ctx):
            raise RuntimeError("IdP down")
    c, _ = _client(authenticator=_Boom())
    r = c.post("/api/v1/actions/propose",
               json={"incident_id": "i", "action_id": "restart_pod", "target": "pod-1"})
    assert r.status_code == 401          # 认证器异常 → 401 fail-closed，而非 500
