from typing import Any, Protocol
from urllib.parse import quote

import httpx

from app.actions.model import TargetDescriptor


class TargetResolver(Protocol):
    """Gateway 唯一 runtime caller；只回答 target 的可信 descriptor。"""
    def resolve(self, target: str) -> TargetDescriptor | None: ...


def _encode_target(target: str) -> str:
    """quote 后把 '.' 也编码为 %2E —— 否则 httpx 的 RFC-3986 dot-segment 归一化
    会把 '.'/'..' 消掉，令请求逃出 /targets/。"""
    return quote(target, safe="").replace(".", "%2E")


def parse_target_descriptor(data: Any) -> TargetDescriptor | None:
    """严格解析 inventory 响应；任何不合法 → None（fail-closed）。"""
    if not isinstance(data, dict):
        return None
    kind = data.get("kind")
    env = data.get("environment")
    if not isinstance(kind, str) or not kind.strip():
        return None
    if not isinstance(env, str) or not env.strip():
        return None
    replicas = data.get("replicas")                       # 缺省 / null → None（合法）
    if replicas is not None:
        if isinstance(replicas, bool):                    # bool 是 int 子类，显式排除
            return None
        if not isinstance(replicas, int) or replicas < 0:  # 非整数 / 负数 → malformed
            return None
    return TargetDescriptor(kind=kind, environment=env, replicas=replicas)


class CMDBInventoryResolver:
    """V1 concrete adapter：GET {cmdb_url}/targets/{name}。只读、无副作用、不抛异常。"""

    def __init__(self, cmdb_url: str, *, transport=None, timeout: float = 10.0) -> None:
        self._url = cmdb_url.rstrip("/")        # 去尾斜杠，避免 ``…//targets``
        self._transport = transport
        self._timeout = timeout

    def resolve(self, target: str) -> TargetDescriptor | None:
        if not self._url:
            return None
        try:
            with httpx.Client(transport=self._transport) as client:
                resp = client.get(f"{self._url}/targets/{_encode_target(target)}",
                                  timeout=self._timeout)
        except Exception:                       # 连接 / 超时 / 其它网络错误 → fail-closed
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except Exception:                       # 非 JSON body → fail-closed
            return None
        return parse_target_descriptor(data)
