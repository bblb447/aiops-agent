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
