import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Sequence

from app.actions.audit_ports import AnchorHead
from app.auth.model import AuthMethod

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
               principal_id, auth_method, key_version, detail, prev_integrity) -> str:
    # integrity 覆盖整条 canonical event（含 key_version）。
    am = auth_method.value if auth_method is not None else None
    return json.dumps({
        "seq": seq, "event_type": event_type, "incident_id": incident_id,
        "action_id": action_id, "proposal_fingerprint": proposal_fingerprint,
        "principal_id": principal_id, "auth_method": am, "key_version": key_version,
        "detail": detail, "prev_integrity": prev_integrity,
    }, sort_keys=True, ensure_ascii=False)


def _integrity(seq, event_type, incident_id, action_id, proposal_fingerprint,
               principal_id, auth_method, key_version, detail, prev_integrity,
               *, key: bytes) -> str:
    msg = _canonical(seq, event_type, incident_id, action_id, proposal_fingerprint,
                     principal_id, auth_method, key_version, detail, prev_integrity)
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class AuditEvent:
    seq: int
    event_type: str
    incident_id: str | None
    action_id: str | None
    proposal_fingerprint: str | None
    detail: dict
    prev_integrity: str
    key_version: int                              # required：DA5 的 integrity 输入，无默认
    principal_id: str | None = None
    auth_method: AuthMethod | None = None
    integrity: str = ""


def _observed_head(events) -> AnchorHead | None:
    if not events:
        return None
    e = events[-1]
    return AnchorHead(e.seq, e.integrity, e.key_version)


def verify_chain(events: Sequence[AuditEvent], head, keys) -> bool:
    """纯函数：keyed 链验证（检测 modify / delete / insert / reorder / tail-delete）。

    `keys: Mapping[int, bytes]` —— 每个事件按其 `key_version` 取 key；**任一缺失 → False**（fail-closed）。
    `head: AnchorHead | None` —— 非 None 时校验「观测尾 == 承诺头」（检 tail-delete）。
    **无 I/O、不依赖 KeyProvider**；HMAC 复算在本函数内完成。
    """
    prev = GENESIS
    for expected_seq, e in enumerate(events):
        if e.seq != expected_seq or e.prev_integrity != prev:
            return False
        key = keys.get(e.key_version)
        if key is None:                           # 历史 key 缺失 → fail-closed
            return False
        recomputed = _integrity(e.seq, e.event_type, e.incident_id, e.action_id,
                                e.proposal_fingerprint, e.principal_id, e.auth_method,
                                e.key_version, e.detail, e.prev_integrity, key=key)
        if recomputed != e.integrity:
            return False
        prev = e.integrity
    if head is not None and head != _observed_head(events):
        return False
    return True


# Task 3 将由注入的 KeyProvider 取代；Task 2 用模块默认 key 维持核心可独立测。
_DEFAULT_KEY = b"durable-audit-default-key"
_DEFAULT_KEY_VERSION = 1


class AuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def _key_map(self, events) -> dict:
        return {_DEFAULT_KEY_VERSION: _DEFAULT_KEY}

    def append(self, event_type: str, *, incident_id=None, action_id=None,
               proposal_fingerprint=None, detail=None,
               principal_id=None, auth_method=None) -> AuditEvent:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"未知 audit event_type: {event_type!r}")
        if auth_method is not None and not isinstance(auth_method, AuthMethod):
            auth_method = AuthMethod(auth_method)   # 规范化：raw str → AuthMethod（非法值 → ValueError）
        seq = len(self._events)
        prev = self._events[-1].integrity if self._events else GENESIS
        det = _sanitize_strict(dict(detail or {}))
        version = _DEFAULT_KEY_VERSION
        integ = _integrity(seq, event_type, incident_id, action_id, proposal_fingerprint,
                           principal_id, auth_method, version, det, prev, key=_DEFAULT_KEY)
        e = AuditEvent(seq, event_type, incident_id, action_id, proposal_fingerprint,
                       det, prev, version, principal_id, auth_method, integ)
        self._events.append(e)
        return e

    def head(self) -> AnchorHead | None:
        return _observed_head(self._events)

    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)          # 不暴露可变内部 list

    def verify(self) -> bool:
        return verify_chain(self._events, self.head(), self._key_map(self._events))
