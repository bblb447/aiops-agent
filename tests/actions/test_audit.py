import pytest

from app.actions.audit import AuditEvent, AuditLog, verify_chain
from app.auth.model import AuthMethod


def _log():
    log = AuditLog()
    log.append("PROPOSED", incident_id="i", action_id="restart_pod", proposal_fingerprint="f")
    log.append("POLICY_DECIDED", incident_id="i", proposal_fingerprint="f",
               detail={"policy_decision": "ALLOW"})
    log.append("EXECUTED", incident_id="i", proposal_fingerprint="f",
               detail={"execution_outcome": "EXECUTED"})
    return log


def test_valid_chain_verifies_and_seq_continuous():
    log = _log()
    assert log.verify() is True
    assert [e.seq for e in log.events()] == [0, 1, 2]


def test_events_returns_immutable_tuple():
    ev = _log().events()
    assert isinstance(ev, tuple)
    with pytest.raises(TypeError):
        ev[0] = None


def test_modify_detected():
    ev = list(_log().events())
    e = ev[1]
    ev[1] = AuditEvent(seq=e.seq, event_type="TAMPERED", incident_id=e.incident_id,
                       action_id=e.action_id, proposal_fingerprint=e.proposal_fingerprint,
                       detail=e.detail, prev_integrity=e.prev_integrity,
                       principal_id=e.principal_id, auth_method=e.auth_method,
                       integrity=e.integrity)
    assert verify_chain(ev) is False


def test_delete_detected():
    ev = list(_log().events())
    del ev[1]
    assert verify_chain(ev) is False


def test_insert_detected():
    ev = list(_log().events())
    ev.insert(1, ev[0])
    assert verify_chain(ev) is False


def test_reorder_detected():
    ev = list(_log().events())
    ev[0], ev[1] = ev[1], ev[0]
    assert verify_chain(ev) is False


def test_tail_delete_detected_via_head_commitment():
    log = _log()
    ev = list(log.events())
    assert verify_chain(ev[:-1]) is True               # 截断短链本身合法……
    assert verify_chain(ev[:-1], log.head()) is False  # ……对照承诺头 → 检出 tail-delete
    assert log.verify() is True


def test_detail_unknown_key_fail_closed():
    with pytest.raises(ValueError):
        AuditLog().append("PROPOSED", detail={"action_id": "restart_pod", "token": "SECRET"})


def test_detail_non_primitive_value_rejected():
    with pytest.raises(ValueError):
        AuditLog().append("PROPOSED", detail={"raw_parameters": {"x": 1}})


def test_detail_allowlisted_primitive_ok():
    e = AuditLog().append("PROPOSED", detail={"action_id": "restart_pod"})
    assert e.detail == {"action_id": "restart_pod"}


def test_unknown_event_type_rejected():
    with pytest.raises(ValueError):
        AuditLog().append("NOPE")


def test_principal_id_is_integrity_covered():
    log = AuditLog()
    log.append("APPROVED", principal_id="bob", auth_method=AuthMethod.DEV)
    e = log.events()[0]
    assert e.principal_id == "bob" and e.auth_method is AuthMethod.DEV
    ev = list(log.events())
    ev[0] = AuditEvent(seq=e.seq, event_type=e.event_type, incident_id=e.incident_id,
                       action_id=e.action_id, proposal_fingerprint=e.proposal_fingerprint,
                       detail=e.detail, prev_integrity=e.prev_integrity,
                       principal_id="mallory", auth_method=e.auth_method, integrity=e.integrity)
    assert verify_chain(ev) is False                       # 篡改 principal_id → 检出


def test_identity_defaults_none():
    e = AuditLog().append("PROPOSED")
    assert e.principal_id is None and e.auth_method is None


def test_auth_method_normalized_to_enum():
    # auth_method 运行时保持 AuthMethod 类型（稳定契约），_canonical 的 .value 不靠错误暴露
    e = AuditLog().append("APPROVED", auth_method="dev")
    assert e.auth_method is AuthMethod.DEV


def test_invalid_auth_method_rejected():
    with pytest.raises(ValueError):
        AuditLog().append("APPROVED", auth_method="bogus")
