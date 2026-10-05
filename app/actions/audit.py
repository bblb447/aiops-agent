import hashlib
import json
from dataclasses import dataclass
from typing import Sequence

GENESIS = "GENESIS"

# detail 脱敏 allowlist：只有这些键允许进入 audit（绝不记 token/credential/raw payload/raw RCA/evidence）。
DETAIL_ALLOWLIST = frozenset({
    "action_id", "target_kind", "environment", "registry_version",
    "final_risk", "policy_decision", "execution_outcome", "approval_id", "reason_kind",
})

EVENT_TYPES = frozenset({
    "PROPOSED", "RISK_EVALUATED", "POLICY_DECIDED", "APPROVAL_REQUESTED",
    "APPROVED", "REJECTED", "EXPIRED", "EXECUTION_ACCEPTED", "EXECUTION_REJECTED",
    "EXECUTED", "FAILED", "TIMEOUT", "NOOP",
})

_PRIMITIVE = (str, int, float, bool)


def _sanitize_strict(detail: dict) -> dict:
    unknown = [k for k in detail if k not in DETAIL_ALLOWLIST]
    if unknown:                                    # fail-closed：未知键拒绝，不静默丢弃
        raise ValueError(f"detail 含不允许的键（fail-closed）: {sorted(unknown)}")
    for k, v in detail.items():
        if v is not None and not isinstance(v, _PRIMITIVE):
            raise ValueError(f"detail[{k!r}] 类型不允许（仅 primitive/None）")
    return detail


def _canonical(seq, event_type, incident_id, action_id, proposal_fingerprint,
               detail, prev_integrity) -> str:
    # integrity 覆盖整条 canonical event（非仅 detail）。
    return json.dumps({
        "seq": seq, "event_type": event_type, "incident_id": incident_id,
        "action_id": action_id, "proposal_fingerprint": proposal_fingerprint,
        "detail": detail, "prev_integrity": prev_integrity,
    }, sort_keys=True, ensure_ascii=False)


def _integrity(*args) -> str:
    return hashlib.sha256(_canonical(*args).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEvent:
    seq: int
    event_type: str
    incident_id: str | None
    action_id: str | None
    proposal_fingerprint: str | None
    detail: dict
    prev_integrity: str
    integrity: str


def verify_chain(events: Sequence[AuditEvent], head=None) -> bool:
    """纯函数：检测 modify / delete / insert / reorder。

    `head=(seq, integrity)` 是**独立 head commitment**；给定后同时校验「观测尾 == 承诺头」，
    故可检测 **tail-delete**。无 head 时只验证链内部完整性，不承诺 tail-delete detection；
    完整 B2 verification 须提供 committed head（`AuditLog.verify()` 始终提供）。
    """
    prev = GENESIS
    for expected_seq, e in enumerate(events):
        if e.seq != expected_seq:
            return False
        if e.prev_integrity != prev:
            return False
        recomputed = _integrity(e.seq, e.event_type, e.incident_id, e.action_id,
                                e.proposal_fingerprint, e.detail, e.prev_integrity)
        if recomputed != e.integrity:
            return False
        prev = e.integrity
    if head is not None:
        observed = (events[-1].seq, events[-1].integrity) if events else (-1, GENESIS)
        if observed != head:
            return False
    return True


class AuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._head: tuple[int, str] = (-1, GENESIS)     # 独立 head commitment

    def head(self) -> tuple[int, str]:
        return self._head                               # (last_seq, last_integrity)

    def append(self, event_type: str, *, incident_id=None, action_id=None,
               proposal_fingerprint=None, detail=None) -> AuditEvent:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"未知 audit event_type: {event_type!r}")
        seq = len(self._events)
        prev = self._events[-1].integrity if self._events else GENESIS
        det = _sanitize_strict(dict(detail or {}))
        e = AuditEvent(seq, event_type, incident_id, action_id, proposal_fingerprint,
                       det, prev,
                       _integrity(seq, event_type, incident_id, action_id,
                                  proposal_fingerprint, det, prev))
        self._events.append(e)
        self._head = (seq, e.integrity)                 # 推进承诺头
        return e

    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)          # 不暴露可变内部 list

    def verify(self) -> bool:
        return verify_chain(self._events, self._head)   # 带 head → 覆盖 tail-delete
