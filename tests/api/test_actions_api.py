from app.actions.approval import ApprovalStore
from app.actions.audit import AuditLog
from app.actions.executor import ActionExecutor
from app.actions.flow import ActionFlow
from app.actions.gateway import ActionGateway
from app.actions.model import ExecutionOutcome, TargetDescriptor
from app.actions.registry import default_registry
from app.incident.model import RCAResult
from app.incident.service import IncidentService
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Resolver:
    def resolve(self, target):
        return {"pod-1": TargetDescriptor("pod", "staging", 3)}.get(target)


class _Backend:
    def execute(self, a, t, p):
        return ExecutionOutcome.EXECUTED


def _client():
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    inc.rca = RCAResult(verdict="ROOT_CAUSE_FOUND", root_cause="r", confidence=0.9,
                        evidence=[{"source": "prometheus", "fact": "f"}])
    inc.verdict = inc.rca.verdict
    inc.status = "ROOT_CAUSE_FOUND"
    store = ApprovalStore()
    flow = ActionFlow(ActionGateway(default_registry(), _Resolver(), lambda iid: inc),
                      store, ActionExecutor(_Backend(), default_registry(), store), AuditLog())
    from app.api.actions import create_actions_router
    app = FastAPI()
    app.include_router(create_actions_router(flow))
    return TestClient(app), store


def test_propose_allow_executes():
    c, _ = _client()
    r = c.post("/api/v1/actions/propose", headers={"X-Actor": "ops"},
               json={"incident_id": "i", "action_id": "restart_pod", "target": "pod-1",
                     "parameters": {"namespace": "prod", "pod": "pod-1"}})
    assert r.status_code == 200
    assert r.json()["status"] == "EXECUTED"


def test_propose_unknown_action_rejected():
    c, _ = _client()
    r = c.post("/api/v1/actions/propose", json={"incident_id": "i", "action_id": "nope",
                                                "target": "pod-1"})
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
