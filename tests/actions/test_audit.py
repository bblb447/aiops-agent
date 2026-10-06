import dataclasses

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
    log = _log(); ev = list(log.events()); e = ev[1]
    ev[1] = AuditEvent(seq=e.seq, event_type="TAMPERED", incident_id=e.incident_id,
                       action_id=e.action_id, proposal_fingerprint=e.proposal_fingerprint,
                       detail=e.detail, prev_integrity=e.prev_integrity,
                       key_version=e.key_version, principal_id=e.principal_id,
                       auth_method=e.auth_method, integrity=e.integrity)
    assert verify_chain(ev, None, log._key_map(ev)) is False


def test_delete_detected():
    log = _log(); ev = list(log.events()); del ev[1]
    assert verify_chain(ev, None, log._key_map(ev)) is False


def test_insert_detected():
    log = _log(); ev = list(log.events()); ev.insert(1, ev[0])   # 重复 seq
    assert verify_chain(ev, None, log._key_map(ev)) is False


def test_reorder_detected():
    log = _log(); ev = list(log.events()); ev[0], ev[1] = ev[1], ev[0]
    assert verify_chain(ev, None, log._key_map(ev)) is False


def test_tail_delete_detected_via_head_commitment():
    log = _log(); ev = list(log.events())
    assert verify_chain(ev[:-1], None, log._key_map(ev)) is True       # 截断短链本身合法……
    assert verify_chain(ev[:-1], log.head(), log._key_map(ev)) is False  # ……对照承诺头 → 检出
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
                       key_version=e.key_version, principal_id="mallory",
                       auth_method=e.auth_method, integrity=e.integrity)
    assert verify_chain(ev, None, log._key_map(ev)) is False


def test_identity_defaults_none():
    e = AuditLog().append("PROPOSED")
    assert e.principal_id is None and e.auth_method is None


def test_auth_method_normalized_to_enum():
    e = AuditLog().append("APPROVED", auth_method="dev")
    assert e.auth_method is AuthMethod.DEV


def test_invalid_auth_method_rejected():
    with pytest.raises(ValueError):
        AuditLog().append("APPROVED", auth_method="bogus")


def test_keyed_hmac_detects_field_tamper():
    log = _log(); e = log.events()[0]
    bad = dataclasses.replace(e, event_type="TAMPERED")
    assert verify_chain([bad], None, log._key_map([bad])) is False


def test_missing_key_fails_closed():
    log = _log(); e = log.events()[0]
    assert verify_chain([e], None, {}) is False        # keys 缺 version → False（fail-closed）


# ---------- Task 3：恢复矩阵 + crash-safe append + 单写者 ----------

from app.actions.audit_ports import (  # noqa: E402
    AnchorHead, EphemeralKeyProvider, MemoryAnchor, MemoryAuditStore,
)


class _BoomAnchor:
    def read(self):
        return None

    def commit(self, head):
        raise RuntimeError("crash before commit")


def test_recover_empty_store_no_anchor_ok():
    AuditLog(MemoryAuditStore(), MemoryAnchor(), EphemeralKeyProvider())   # 不抛


def test_recover_nonempty_store_without_anchor_fails_closed():
    s = MemoryAuditStore(); a = MemoryAnchor(); kp = EphemeralKeyProvider()
    AuditLog(s, a, kp).append("PROPOSED")
    with pytest.raises(Exception):
        AuditLog(s, MemoryAnchor(), kp)                 # anchor 被删 → 禁止重新首锚


def test_recover_empty_store_with_anchor_fails_closed():
    s = MemoryAuditStore(); a = MemoryAnchor(); kp = EphemeralKeyProvider()
    a.commit(AnchorHead(0, "x", 1))
    with pytest.raises(Exception):
        AuditLog(s, a, kp)


def test_append_crash_between_store_and_anchor_fails_closed_on_restart():
    s = MemoryAuditStore(); kp = EphemeralKeyProvider()
    log = AuditLog(s, _BoomAnchor(), kp)
    with pytest.raises(RuntimeError):
        log.append("PROPOSED")                          # store 成功、anchor.commit 崩
    with pytest.raises(Exception):
        AuditLog(s, MemoryAnchor(), kp)                 # 重启：store 非空 + anchor 缺 → fail-closed


def test_normal_restart_verifies():
    s = MemoryAuditStore(); a = MemoryAnchor(); kp = EphemeralKeyProvider()
    log = AuditLog(s, a, kp); log.append("PROPOSED"); log.append("EXECUTED")
    log2 = AuditLog(s, a, kp)                           # 重启
    assert log2.verify() is True and len(log2.events()) == 2


def test_concurrent_appends_are_serialized():
    import threading, time

    class _SlowStore(MemoryAuditStore):                 # 放大 I/O 窗口，暴露无锁交错
        def append(self, event):
            time.sleep(0.001)
            super().append(event)

    s = _SlowStore(); a = MemoryAnchor(); kp = EphemeralKeyProvider()
    log = AuditLog(s, a, kp)

    def worker():
        for _ in range(20):
            log.append("PROPOSED")

    ts = [threading.Thread(target=worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(e.seq for e in log.events()) == list(range(80))   # 无重复/无空洞
    assert log.verify() is True                                     # 链 + anchor 自洽
    assert a.read() == log.head()                                   # anchor 与内存 head 一致


def test_append_after_failed_anchor_commit_is_poisoned():
    s = MemoryAuditStore(); kp = EphemeralKeyProvider()
    log = AuditLog(s, _BoomAnchor(), kp)
    with pytest.raises(RuntimeError):
        log.append("PROPOSED")
    with pytest.raises(Exception):
        log.append("PROPOSED")                                      # poisoned：不再静默续写
    with pytest.raises(Exception):
        log.verify()                                                # 亦 fail-closed
    assert len(s.read_all()) == 1                                   # store 无重复 seq
