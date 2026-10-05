import pytest
from app.actions.model import PermissionLevel, RiskLevel
from app.actions.registry import (
    ActionEntry, ActionRegistry, default_registry, validate_parameters)

# schema 形如 {name: (type, required)}
SCHEMA = {"namespace": (str, True), "pod": (str, True), "force": (bool, False)}


def _entry(action_id="restart_pod", **kw):
    base = dict(permission_level=PermissionLevel.LOW_WRITE, base_risk=RiskLevel.MEDIUM,
                target_kinds=frozenset({"pod"}), parameter_schema=SCHEMA,
                rollback_class="idempotent")
    base.update(kw)
    return ActionEntry(action_id=action_id, **base)


def test_registry_get_contains_and_readonly_version():
    reg = ActionRegistry([_entry()])
    assert "restart_pod" in reg and reg.get("restart_pod").action_id == "restart_pod"
    assert reg.get("nope") is None and "nope" not in reg
    assert reg.version == "actions@1"
    with pytest.raises(AttributeError):
        reg.version = "actions@999"          # 只读属性，外部不可改


def test_registry_rejects_duplicate_action_id():
    with pytest.raises(ValueError):
        ActionRegistry([_entry(), _entry()])


def test_action_entry_schema_is_readonly_authority():
    e = _entry()
    with pytest.raises(TypeError):
        e.parameter_schema["x"] = (str, True)   # MappingProxyType，内容不可改


def test_validate_parameters_required_missing_rejected():
    assert "必填" in validate_parameters(SCHEMA, {"namespace": "prod"})   # 缺 pod


def test_validate_parameters_optional_missing_allowed():
    assert validate_parameters(SCHEMA, {"namespace": "prod", "pod": "p1"}) is None   # force 可选


def test_validate_parameters_unknown_rejected():
    assert "未在 schema" in validate_parameters(
        SCHEMA, {"namespace": "p", "pod": "x", "zzz": 1})


def test_validate_parameters_wrong_type_rejected():
    assert "类型" in validate_parameters(SCHEMA, {"namespace": "p", "pod": 1})


def test_default_registry_seed_contents():
    reg = default_registry()
    assert reg.get("restart_pod").permission_level is PermissionLevel.LOW_WRITE
    assert reg.get("scale_deployment").permission_level is PermissionLevel.HIGH_WRITE
    assert reg.get("delete_namespace").permission_level is PermissionLevel.CRITICAL
