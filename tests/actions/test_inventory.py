import pytest

from app.actions.inventory import parse_target_descriptor
from app.actions.model import TargetDescriptor


def test_valid_descriptor_with_replicas():
    d = parse_target_descriptor({"kind": "deployment", "environment": "staging", "replicas": 3})
    assert d == TargetDescriptor("deployment", "staging", 3)


def test_replicas_null_and_absent_both_valid_none():
    assert parse_target_descriptor(
        {"kind": "pod", "environment": "prod", "replicas": None}) == TargetDescriptor("pod", "prod", None)
    assert parse_target_descriptor(
        {"kind": "pod", "environment": "prod"}) == TargetDescriptor("pod", "prod", None)


def test_replicas_zero_is_zero_not_none():
    assert parse_target_descriptor(
        {"kind": "deployment", "environment": "prod", "replicas": 0}).replicas == 0


@pytest.mark.parametrize("bad", [True, False, -1, "3", 3.0, [], {"n": 1}])
def test_invalid_replicas_is_malformed(bad):
    # bool 是 int 子类 → 必须显式排除；负数非合法 fact；其它类型非法。
    assert parse_target_descriptor({"kind": "pod", "environment": "prod", "replicas": bad}) is None


@pytest.mark.parametrize("data", [
    {}, {"kind": "pod"}, {"environment": "prod"},
    {"kind": "", "environment": "prod"}, {"kind": "pod", "environment": "   "},
    {"kind": "   ", "environment": "prod"},
    {"kind": 1, "environment": "prod"}, {"kind": "pod", "environment": ["prod"]},
    "not-a-dict", None, [1, 2],
])
def test_malformed_is_none(data):
    assert parse_target_descriptor(data) is None


def test_unknown_fields_ignored():
    d = parse_target_descriptor(
        {"kind": "pod", "environment": "prod", "replicas": 2, "workload": "w", "extra": "x"})
    assert d == TargetDescriptor("pod", "prod", 2)
