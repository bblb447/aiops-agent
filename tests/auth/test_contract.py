import dataclasses
import inspect

import pytest

from app.actions import gateway
from app.actions.audit import AuditEvent, AuditLog, verify_chain
from app.actions.model import ALLOWED_PROPOSAL_KEYS, FORBIDDEN_PROPOSAL_KEYS
from app.auth.model import ActorContext, AuthMethod, AuthenticatedPrincipal


# ---- PA2：ActorContext exact type + request actor 唯一构造路径 ----
def test_pa2_actor_context_exact_fields():
    assert {f.name for f in dataclasses.fields(ActorContext)} == {
        "principal_id", "auth_method", "claims"}


def test_pa2_from_principal_is_the_request_construction_path():
    ctx = ActorContext.from_principal(AuthenticatedPrincipal("alice", AuthMethod.DEV, {}))
    assert isinstance(ctx, ActorContext) and ctx.principal_id == "alice"


def test_pa2_api_constructs_actor_context_only_via_from_principal():
    from app.api import actions as api
    src = inspect.getsource(api)
    assert "ActorContext.from_principal" in src
    assert "ActorContext(" not in src            # 无绕过 from_principal 的直接构造


# ---- PA3：proposal 权威字段禁列 ----
def test_pa3_actor_identity_fields_forbidden_in_proposal():
    forbidden = {"actor", "requested_by", "actor_context"}
    assert forbidden <= FORBIDDEN_PROPOSAL_KEYS
    assert not (forbidden & ALLOWED_PROPOSAL_KEYS)


# ---- PA4：actor 不进 fingerprint ----
def test_pa4_fingerprint_excludes_actor():
    assert "actor" not in inspect.getsource(gateway.proposal_fingerprint)


# ---- PA5：audit identity 受 integrity 覆盖 ----
def test_pa5_audit_identity_is_integrity_covered():
    log = AuditLog()
    log.append("APPROVED", principal_id="bob", auth_method=AuthMethod.DEV)
    e = log.events()[0]
    tampered = AuditEvent(seq=e.seq, event_type=e.event_type, incident_id=e.incident_id,
                          action_id=e.action_id, proposal_fingerprint=e.proposal_fingerprint,
                          detail=e.detail, prev_integrity=e.prev_integrity,
                          key_version=e.key_version, principal_id="mallory",
                          auth_method=e.auth_method, integrity=e.integrity)
    assert verify_chain([tampered], None, log._key_map([tampered])) is False


# ---- PA6：request actor 与 executor service principal 双入口分离 ----
def test_pa6_executor_service_principal_is_typed_and_from_config():
    from app.actions.approval import ApprovalStore
    from app.actions.executor import ActionExecutor
    from app.actions.registry import default_registry
    svc = ActorContext("executor-service", AuthMethod.SERVICE)
    ex = ActionExecutor(object(), default_registry(), ApprovalStore(), svc)
    assert isinstance(ex.service_principal, ActorContext)
    assert ex.service_principal.auth_method is AuthMethod.SERVICE


# ---- PA7：audit 面冻结为 principal_id + auth_method；claims 不入 audit ----
def test_pa7_audit_identity_surface_is_principal_and_method_only():
    fields = {f.name for f in dataclasses.fields(AuditEvent)}
    assert "principal_id" in fields and "auth_method" in fields
    assert "claims" not in fields


def test_pa7_claims_not_written_to_audit_detail():
    with pytest.raises(ValueError):               # detail allowlist fail-closed
        AuditLog().append("PROPOSED", detail={"claims": "role=ops"})
