import dataclasses
from types import SimpleNamespace

import pytest

from app.actions.audit_ports import (
    AnchorHead, EphemeralKeyProvider, MemoryAnchor, MemoryAuditStore,
)


def test_anchor_head_frozen_and_fields():
    h = AnchorHead(2, "abc", 1)
    assert (h.seq, h.integrity, h.key_version) == (2, "abc", 1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.seq = 3


def test_memory_store_append_read_last_seq():
    s = MemoryAuditStore()
    assert s.last_seq() == -1 and tuple(s.read_all()) == ()
    s.append(SimpleNamespace(seq=0))
    assert s.last_seq() == 0 and len(tuple(s.read_all())) == 1


def test_memory_anchor_monotonic_rejects_rollback():
    a = MemoryAnchor()
    assert a.read() is None
    a.commit(AnchorHead(0, "x", 1))
    a.commit(AnchorHead(1, "y", 1))
    assert a.read() == AnchorHead(1, "y", 1)
    with pytest.raises(ValueError):
        a.commit(AnchorHead(0, "x", 1))          # 回退 → 拒


def test_ephemeral_key_provider_current_get_rotate():
    kp = EphemeralKeyProvider()
    v, key = kp.current()
    assert kp.get(v) == key
    v2 = kp.rotate()
    assert v2 == v + 1
    assert kp.get(v) == key                       # 旧 key 保留
    assert kp.get(999) is None
