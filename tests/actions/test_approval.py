import pytest
from app.actions.approval import Approval, ApprovalStatus, ApprovalStore
from app.actions.model import DecisionSnapshot, PolicyDecision, RiskLevel, TargetDescriptor


def _snap(fp="f" * 64):
    return DecisionSnapshot(
        context="ctx", action_id="scale_deployment",
        target_descriptor=TargetDescriptor("deployment", "prod", 3),
        parameters={"namespace": "prod", "deployment": "d", "replicas": 2},
        registry_version="actions@1", final_risk=RiskLevel.HIGH,
        policy_decision=PolicyDecision.APPROVAL_REQUIRED, proposal_fingerprint=fp)


def test_request_is_pending_and_bound_to_snapshot():
    store = ApprovalStore()
    ap = store.request(_snap())
    assert ap.status is ApprovalStatus.PENDING
    assert ap.snapshot.proposal_fingerprint == "f" * 64


def test_approve_then_valid_for_matching_fingerprint():
    store = ApprovalStore()
    a = store.request(_snap()).approval_id
    store.approve(a, actor="ops")
    assert store.get(a).status is ApprovalStatus.APPROVED
    assert store.is_valid_for(a, "f" * 64) is True
    assert store.is_valid_for(a, "e" * 64) is False


def test_reject_and_expire_terminal():
    store = ApprovalStore()
    a = store.request(_snap()).approval_id
    store.reject(a, actor="ops")
    assert store.get(a).status is ApprovalStatus.REJECTED
    with pytest.raises(ValueError):
        store.approve(a, actor="ops")


def test_terminal_state_immutable_and_requires_new_record():
    store = ApprovalStore()
    a = store.request(_snap()).approval_id
    store.approve(a, actor="ops")
    with pytest.raises(ValueError):
        store.expire(a)
    b = store.request(_snap()).approval_id
    assert b != a and store.get(b).status is ApprovalStatus.PENDING


def test_expired_is_not_valid_for_execution():
    store = ApprovalStore()
    a = store.request(_snap()).approval_id
    store.expire(a)
    assert store.is_valid_for(a, "f" * 64) is False
