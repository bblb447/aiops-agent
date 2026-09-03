import time

import pytest

from app.config import Settings
from app.tools.monitoring import MonitoringTool
from app.workload.service import WorkloadService, WorkloadQueryError

WANT_FIELDS = {"qps", "error_rate", "cpu", "memory"}


@pytest.mark.integration
class TestPrometheus:
    def test_query_metric_hits_exporter(self, l1_env):
        tool = MonitoringTool(Settings(prometheus_url=l1_env["prometheus"]))
        r = tool.query_metric("http_requests_total")
        assert r.success
        assert r.data["status"] == "success"
        assert len(r.data["data"]["result"]) > 0

    def test_query_metric_unknown_metric_empty(self, l1_env):
        tool = MonitoringTool(Settings(prometheus_url=l1_env["prometheus"]))
        r = tool.query_metric("metric_that_does_not_exist_xyz")
        assert r.success
        assert r.data["data"]["result"] == []

    def test_query_metric_bad_expression_status_error(self, l1_env):
        # 非法 metric → 真实 Prometheus status=error → success=False（spec 44.10 错误语义）
        tool = MonitoringTool(Settings(prometheus_url=l1_env["prometheus"]))
        r = tool.query_metric("]")
        assert not r.success
        assert "查询失败" in r.error

    def test_query_metric_range_hits(self, l1_env):
        tool = MonitoringTool(Settings(prometheus_url=l1_env["prometheus"]))
        now = int(time.time())
        r = tool.query_metric_range("up", start=now - 300, end=now, step="60s")
        assert r.success
        assert len(r.data["data"]["result"]) > 0

    def test_query_workload_order_service_all_fields(self, l1_env):
        # spec 44.10 宽范围：qps>0、0<=error_rate<=1、cpu>0、memory>0
        tool = MonitoringTool(Settings(prometheus_url=l1_env["prometheus"]))
        r = tool.query_workload("order-service")
        assert r.success
        assert WANT_FIELDS <= set(r.data)
        assert r.data["qps"] > 0
        assert 0 <= r.data["error_rate"] <= 1
        assert r.data["cpu"] > 0
        assert r.data["memory"] > 0

    def test_query_workload_ghost_all_null(self, l1_env):
        tool = MonitoringTool(Settings(prometheus_url=l1_env["prometheus"]))
        r = tool.query_workload("ghost-service")
        assert r.success
        for f in WANT_FIELDS:
            assert r.data[f] is None

    def test_query_workload_isolated_endpoint_error(self):
        # 错误路径隔离：connection refused → WorkloadQueryError（spec 44.10）
        with pytest.raises(WorkloadQueryError):
            WorkloadService("http://127.0.0.1:31999").get_workload("order-service")
