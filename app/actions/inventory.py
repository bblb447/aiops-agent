from typing import Any, Protocol

from app.actions.model import TargetDescriptor


class TargetResolver(Protocol):
    """Gateway 唯一 runtime caller；只回答 target 的可信 descriptor。"""
    def resolve(self, target: str) -> TargetDescriptor | None: ...


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
