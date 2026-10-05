import dataclasses
import pytest
from app.actions import model


def test_gateway_outcome_has_four_states():
    assert {o.value for o in model.GatewayOutcome} == {
        "ALLOW", "APPROVAL_REQUIRED", "DENY", "REJECT"}


def test_forbidden_proposal_keys_covers_authority_fields():
    # spec §4 / I2：这些字段 agent 提交即拒。
    assert {"risk_level", "permission_level", "approval_required",
            "eligibility", "requested_by"} <= model.FORBIDDEN_PROPOSAL_KEYS


def test_allowed_proposal_keys_is_closed_allowlist():
    # I2 fail-closed：顶层只允许这四个 key；其余一律拒（见 Task 6）。
    assert model.ALLOWED_PROPOSAL_KEYS == {"action_id", "target", "parameters", "reason"}
    assert model.ALLOWED_PROPOSAL_KEYS.isdisjoint(model.FORBIDDEN_PROPOSAL_KEYS)


def test_proposal_and_target_descriptor_are_frozen():
    # 注：frozen 只保护字段不可重绑，不宣称深层不可变（parameters 仍为 dict）。
    p = model.Proposal(action_id="restart_pod", target="pod-1", parameters={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.action_id = "x"
    td = model.TargetDescriptor(kind="pod", environment="prod")
    with pytest.raises(dataclasses.FrozenInstanceError):
        td.kind = "y"
