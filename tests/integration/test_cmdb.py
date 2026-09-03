import pytest

from app.config import Settings
from app.tools.cmdb import CMDBTool

CONTRACT = {
    "service": "order-service",
    "status": "running",
    "owner": "platform",
    "dependencies": ["auth-service", "payment-service"],
}


@pytest.mark.integration
class TestCmdb:
    def test_get_service_hit_returns_contract(self, l1_env):
        r = CMDBTool(Settings(cmdb_url=l1_env["cmdb"])).get_service("order-service")
        assert r.success
        assert r.data == CONTRACT

    def test_get_service_miss_returns_failure(self, l1_env):
        r = CMDBTool(Settings(cmdb_url=l1_env["cmdb"])).get_service("no-such-service")
        assert not r.success
        assert "404" in r.error

    def test_get_service_isolated_endpoint_refused(self):
        # 错误路径隔离：独立实例指向未占用端口，不停止共享后端（spec 44.10）
        r = CMDBTool(Settings(cmdb_url="http://127.0.0.1:31999")).get_service("order-service")
        assert not r.success
        assert "查询失败" in r.error
