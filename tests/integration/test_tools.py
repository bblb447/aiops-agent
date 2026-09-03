import pytest

from app.tools.cmdb import CMDBTool
from app.tools.logging import LoggingTool
from app.tools.monitoring import MonitoringTool


@pytest.mark.integration
class TestToolsRealBackend:
    def test_all_tools_over_shared_settings(self, settings_l1):
        wl = MonitoringTool(settings_l1).query_workload("order-service")
        assert wl.success and wl.data["qps"] > 0

        log = LoggingTool(settings_l1).search_logs('{app="order-service"}')
        assert log.success and (log.data.get("data", {}).get("result") or [])

        cmdb = CMDBTool(settings_l1).get_service("order-service")
        assert cmdb.success and cmdb.data["service"] == "order-service"
