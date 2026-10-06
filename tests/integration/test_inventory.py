import pytest

from app.actions.inventory import CMDBInventoryResolver
from app.actions.model import TargetDescriptor


@pytest.mark.integration
class TestInventoryResolver:
    def test_resolve_hit_returns_descriptor(self, l1_env):
        r = CMDBInventoryResolver(l1_env["cmdb"])
        assert r.resolve("dep-1") == TargetDescriptor("deployment", "staging", 3)
        assert r.resolve("pod-1") == TargetDescriptor("pod", "staging", None)

    def test_resolve_miss_returns_none(self, l1_env):
        r = CMDBInventoryResolver(l1_env["cmdb"])
        assert r.resolve("no-such-target") is None

    def test_resolve_unreachable_returns_none(self):
        assert CMDBInventoryResolver("http://127.0.0.1:31999").resolve("x") is None
