import httpx
import pytest

from app.workload.service import WorkloadService, WorkloadUnavailable, WorkloadQueryError


def _metric_for(query: str) -> float:
    q = query
    if "status=~" in q:
        return 0.012          # error_rate
    if "http_requests_total" in q:
        return 125.4          # qps
    if "container_cpu" in q:
        return 0.73           # cpu
    if "container_memory" in q:
        return 6.8e9          # memory bytes
    return 0.0


def _fake_get(url, params=None, timeout=None):
    value = _metric_for((params or {}).get("query", ""))
    return httpx.Response(
        200, request=httpx.Request("GET", str(url)),
        json={"status": "success", "data": {"result": [{"metric": {}, "value": [1710000000, str(value)]}]}},
    )


def test_get_workload_parses_all_metrics(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get)
    wl = WorkloadService("http://prom:9090").get_workload("order-service")
    assert wl.service == "order-service"
    assert wl.qps == 125.4
    assert wl.error_rate == 0.012
    assert wl.cpu == 0.73
    assert wl.memory == 6.8e9
    assert wl.timestamp


def test_get_workload_unconfigured():
    with pytest.raises(WorkloadUnavailable):
        WorkloadService("").get_workload("order-service")


def test_get_workload_query_failure(monkeypatch):
    def boom(url, params=None, timeout=None):
        return httpx.Response(500, request=httpx.Request("GET", str(url)), json={})
    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(WorkloadQueryError):
        WorkloadService("http://prom:9090").get_workload("order-service")


def test_get_workload_prometheus_status_error(monkeypatch):
    # HTTP 200 但 Prometheus 业务 status=error → 必须 WorkloadQueryError，不是静默 null。
    def err(url, params=None, timeout=None):
        return httpx.Response(
            200, request=httpx.Request("GET", str(url)),
            json={"status": "error", "errorType": "bad_data", "error": "bad expr"},
        )
    monkeypatch.setattr(httpx, "get", err)
    with pytest.raises(WorkloadQueryError):
        WorkloadService("http://prom:9090").get_workload("order-service")


def test_get_workload_non_json_response(monkeypatch):
    def txt(url, params=None, timeout=None):
        return httpx.Response(200, request=httpx.Request("GET", str(url)), text="<html>not json")
    monkeypatch.setattr(httpx, "get", txt)
    with pytest.raises(WorkloadQueryError):
        WorkloadService("http://prom:9090").get_workload("order-service")


def test_get_workload_empty_result_is_null_not_error(monkeypatch):
    # 单指标无匹配数据 → 字段 null，请求仍 200（非查询失败）。
    def empty(url, params=None, timeout=None):
        return httpx.Response(
            200, request=httpx.Request("GET", str(url)),
            json={"status": "success", "data": {"result": []}},
        )
    monkeypatch.setattr(httpx, "get", empty)
    wl = WorkloadService("http://prom:9090").get_workload("ghost-service")
    assert wl.qps is None and wl.error_rate is None
    assert wl.cpu is None and wl.memory is None


def test_escape_service_for_promql():
    from app.workload.service import _escape_service
    assert _escape_service('a"b\\c') == 'a\\"b\\\\c'


@pytest.mark.parametrize(
    "result",
    [
        [{"metric": {"service": "s"}}],                   # 缺 value 键
        [{"metric": {}, "value": ["1710000000"]}],        # value 缺数值列
        [{"metric": {}, "value": ["1710000000", "abc"]}],  # 数值列非数值
        [{"metric": {}, "value": "oops"}],                # value 非数组
    ],
)
def test_get_workload_malformed_result_is_query_error(monkeypatch, result):
    # result 非空但记录结构畸形（缺 value / value 非法）→ 数据源返回畸形数据，
    # 须 WorkloadQueryError，与"无匹配数据→null+200"区分（不能吞成 null 或崩 500）。
    def bad(url, params=None, timeout=None):
        return httpx.Response(
            200, request=httpx.Request("GET", str(url)),
            json={"status": "success", "data": {"result": result}},
        )
    monkeypatch.setattr(httpx, "get", bad)
    with pytest.raises(WorkloadQueryError):
        WorkloadService("http://prom:9090").get_workload("order-service")
