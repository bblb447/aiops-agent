import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Sequence

if TYPE_CHECKING:
    from app.actions.audit import AuditEvent


@dataclass(frozen=True)
class AnchorHead:
    """已提交的链头承诺：seq + integrity + 该 head 所用 key version。"""
    seq: int
    integrity: str
    key_version: int


class AuditStore(Protocol):
    """durable 事件链：只追加；无 update/delete/truncate（DA1）。"""
    def append(self, event: "AuditEvent") -> None: ...
    def read_all(self) -> Sequence["AuditEvent"]: ...
    def last_seq(self) -> int: ...


class Anchor(Protocol):
    """head commitment + key identity；store writer 不得经 store 普通写路径覆盖（DA3）。"""
    def commit(self, head: AnchorHead) -> None: ...
    def read(self) -> AnchorHead | None: ...


class KeyProvider(Protocol):
    """key material（不属 store 可写数据，DA4）。"""
    def current(self) -> tuple[int, bytes]: ...
    def get(self, version: int) -> bytes | None: ...
    def rotate(self) -> int: ...


class MemoryAuditStore:
    """内存实现（dev/test）：非 durable。"""
    def __init__(self) -> None:
        self._events: list = []

    def append(self, event) -> None:
        self._events.append(event)

    def read_all(self) -> Sequence:
        return tuple(self._events)

    def last_seq(self) -> int:
        return self._events[-1].seq if self._events else -1


class MemoryAnchor:
    """内存实现（dev/test）：非 durable；commit 单调拒绝回退。"""
    def __init__(self) -> None:
        self._head: AnchorHead | None = None

    def commit(self, head: AnchorHead) -> None:
        if self._head is not None and head.seq < self._head.seq:
            raise ValueError("anchor head 回退被拒")
        self._head = head

    def read(self) -> AnchorHead | None:
        return self._head


class EphemeralKeyProvider:
    """进程内一次性 key（仅 dev/test / 内存 AuditLog）。

    **不是 durable security provider** —— 进程结束即丢，不满足生产 DA4/DA6。
    """
    def __init__(self) -> None:
        self._keys: dict[int, bytes] = {1: os.urandom(32)}
        self._current = 1

    def current(self) -> tuple[int, bytes]:
        return self._current, self._keys[self._current]

    def get(self, version: int) -> bytes | None:
        return self._keys.get(version)

    def rotate(self) -> int:
        self._current += 1
        self._keys[self._current] = os.urandom(32)
        return self._current
