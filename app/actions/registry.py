from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from app.actions.model import PermissionLevel, RiskLevel


@dataclass(frozen=True)
class ActionEntry:
    action_id: str
    permission_level: PermissionLevel
    base_risk: RiskLevel
    target_kinds: frozenset[str]
    parameter_schema: Mapping[str, tuple[type, bool]]   # name -> (type, required)
    rollback_class: str

    def __post_init__(self):
        # 只读权威：frozen 只保护字段重绑，不保护 dict 内容；把 schema 冻结为只读视图。
        object.__setattr__(self, "parameter_schema",
                           MappingProxyType(dict(self.parameter_schema)))


class ActionRegistry:
    def __init__(self, entries: list[ActionEntry], version: str = "actions@1") -> None:
        self._version = version
        by_id: dict[str, ActionEntry] = {}
        for e in entries:
            if e.action_id in by_id:
                raise ValueError(f"duplicate action_id: {e.action_id}")
            by_id[e.action_id] = e
        self._by_id = MappingProxyType(by_id)    # 权威索引也不可外部改

    @property
    def version(self) -> str:
        return self._version                      # 只读，无 setter

    def get(self, action_id: str) -> ActionEntry | None:
        return self._by_id.get(action_id)

    def __contains__(self, action_id: str) -> bool:
        return action_id in self._by_id


def validate_parameters(schema: Mapping[str, tuple[type, bool]], params: dict) -> str | None:
    """返回错误信息（str）表示不合法，None 表示通过。schema: name -> (type, required)。"""
    if not isinstance(params, dict):
        return "parameters 必须是对象"
    for name, (typ, required) in schema.items():
        if required and name not in params:
            return f"参数 {name!r} 必填缺失"
    for key, value in params.items():
        if key not in schema:
            return f"参数 {key!r} 未在 schema 中"
        if not isinstance(value, schema[key][0]):
            return f"参数 {key!r} 类型不合法：期望 {schema[key][0].__name__}"
    return None


def default_registry() -> ActionRegistry:
    """种子目录（示例内容，真实目录由其 owner 维护）。"""
    return ActionRegistry([
        ActionEntry("restart_pod", PermissionLevel.LOW_WRITE, RiskLevel.MEDIUM,
                    frozenset({"pod"}),
                    {"namespace": (str, True), "pod": (str, True)}, "idempotent"),
        ActionEntry("scale_deployment", PermissionLevel.HIGH_WRITE, RiskLevel.HIGH,
                    frozenset({"deployment"}),
                    {"namespace": (str, True), "deployment": (str, True), "replicas": (int, True)},
                    "compensable"),
        ActionEntry("delete_namespace", PermissionLevel.CRITICAL, RiskLevel.HIGH,
                    frozenset({"namespace"}), {"namespace": (str, True)}, "none"),
    ])
