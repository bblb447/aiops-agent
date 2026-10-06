import httpx

from app.actions.gateway import ActionGateway
from app.actions.inventory import CMDBInventoryResolver
from app.actions.model import GatewayOutcome
from app.actions.registry import default_registry
from app.auth.model import ActorContext, AuthMethod
from app.incident.model import RCAResult
from app.incident.service import IncidentService


def _actor():
    return ActorContext("ops", AuthMethod.DEV)


def _incident():
    svc = IncidentService()
    inc = svc.create("t", "order-service", "critical")
    inc.rca = RCAResult(verdict="ROOT_CAUSE_FOUND", root_cause="r", confidence=0.9,
                        evidence=[{"source": "prometheus", "fact": "f"}])
    inc.verdict = inc.rca.verdict
    inc.status = "ROOT_CAUSE_FOUND"
    return inc


def _gateway(handler):
    resolver = CMDBInventoryResolver("http://cmdb", transport=httpx.MockTransport(handler))
    return ActionGateway(default_registry(), resolver, lambda iid: _incident())


_POD = {"action_id": "restart_pod", "target": "pod-1",
        "parameters": {"namespace": "prod", "pod": "pod-1"}}


def test_resolved_target_passes_to_decision():
    g = _gateway(lambda req: httpx.Response(
        200, json={"kind": "pod", "environment": "staging", "replicas": None}))
    assert g.evaluate("i", _POD, _actor()).outcome is not GatewayOutcome.REJECT


def test_kind_not_allowed_by_action_is_rejected():
    # resolver 报 deployment，但 restart_pod 只允许 target_kinds={pod} → REJECT
    g = _gateway(lambda req: httpx.Response(
        200, json={"kind": "deployment", "environment": "staging", "replicas": 3}))
    assert g.evaluate("i", _POD, _actor()).outcome is GatewayOutcome.REJECT


def test_unresolved_target_is_rejected():
    g = _gateway(lambda req: httpx.Response(404))
    assert g.evaluate("i", _POD, _actor()).outcome is GatewayOutcome.REJECT


def test_proposal_cannot_supply_descriptor_facts():
    # IR2：payload 顶层带 kind/environment/replicas → 未知 key → REJECT
    g = _gateway(lambda req: httpx.Response(
        200, json={"kind": "pod", "environment": "staging", "replicas": None}))
    payload = {**_POD, "kind": "pod", "environment": "prod", "replicas": 5}
    assert g.evaluate("i", payload, _actor()).outcome is GatewayOutcome.REJECT
