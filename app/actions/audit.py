import hashlib
import hmac
import json
import threading
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


class AuditLog:
    """记录层：durable 链（store）+ head 锚定（anchor）+ key（keyProvider）。

    缺省注入内存端口（dev/test；**不得用于生产 main 装配**）。`append`/`rotate` 由进程内锁串行化，
    保证 seq 分配 → store.append → anchor.commit 不可交错。
    """
    def __init__(self, store=None, anchor=None, key_provider=None) -> None:
        from app.actions.audit_ports import (
            EphemeralKeyProvider, MemoryAnchor, MemoryAuditStore,
        )
        self._store = store if store is not None else MemoryAuditStore()
        self._anchor = anchor if anchor is not None else MemoryAnchor()
        self._kp = key_provider if key_provider is not None else EphemeralKeyProvider()
        self._lock = threading.Lock()
        self._events: list[AuditEvent] = []
        self._recover()

    def _key_map(self, events) -> dict:
        out: dict[int, bytes] = {}
        for e in events:
            if e.key_version not in out:
                k = self._kp.get(e.key_version)
                if k is None:                       # 历史 key 缺失 → fail-closed
                    raise ValueError(f"fail-closed：历史 key 缺失 version={e.key_version}")
                out[e.key_version] = k
        return out

    def _recover(self) -> None:
        events = list(self._store.read_all())
        anchor = self._anchor.read()
        if not events and anchor is None:
            return                                  # 空 + 无锚 → 正常
        if not events and anchor is not None:
            raise ValueError("fail-closed：anchor 存在但 store 为空（非法状态）")
        if events and anchor is None:
            raise ValueError("fail-closed：store 非空但 anchor 缺失（禁止重新首锚）")
        if not verify_chain(events, anchor, self._key_map(events)):
            raise ValueError("fail-closed：链 / anchor 验证失败（可能被篡改）")
        self._events = events

    def append(self, event_type: str, *, incident_id=None, action_id=None,
               proposal_fingerprint=None, detail=None,
               principal_id=None, auth_method=None) -> AuditEvent:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"未知 audit event_type: {event_type!r}")
        if auth_method is not None and not isinstance(auth_method, AuthMethod):
            auth_method = AuthMethod(auth_method)   # 规范化：raw str → AuthMethod（非法值 → ValueError）
        with self._lock:                            # 单写者：seq/store/anchor 不可交错
            version, key = self._kp.current()
            seq = len(self._events)
            prev = self._events[-1].integrity if self._events else GENESIS
            det = _sanitize_strict(dict(detail or {}))
            integ = _integrity(seq, event_type, incident_id, action_id, proposal_fingerprint,
                               principal_id, auth_method, version, det, prev, key=key)
            e = AuditEvent(seq, event_type, incident_id, action_id, proposal_fingerprint,
                           det, prev, version, principal_id, auth_method, integ)
            self._store.append(e)                   # durable（fsync）
            self._anchor.commit(AnchorHead(seq, integ, version))   # durable + atomic
            self._events.append(e)
            return e

    def rotate(self) -> int:
        with self._lock:                            # 与 append 共享锁，避免 version 切换与构造竞态
            return self._kp.rotate()

    def head(self) -> AnchorHead | None:
        return _observed_head(self._events)

    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)          # 不暴露可变内部 list

    def verify(self) -> bool:
        return verify_chain(self._events, self.head(), self._key_map(self._events))
