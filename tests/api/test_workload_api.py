import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _fake_get(url, params=None, timeout=None):
    q = (params or {}).get("query", "")
    if "status=~" in q:
        v = 0.012
    elif "http_requests_total" in q:
        v = 125.4
    elif "container_cpu" in q:
        v = 0.73
    elif "container_memory" in q:
        v = 6.8e9
    else:
        v = 0.0
    return httpx.Response(
        200, request=httpx.Request("GET", str(url)),
        json={"status": "success", "data": {"result": [{"metric": {}, "value": [1710000000, str(v)]}]}},
    )


def test_get_workload_endpoint(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get)
    app = create_app(Settings(prometheus_url="http://prom:9090"))
    c = TestClient(app)
    r = c.get("/api/v1/workload/order-service")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "order-service"
    assert body["qps"] == 125.4
    assert body["error_rate"] == 0.012
    assert body["cpu"] == 0.73
    assert body["memory"] == 6.8e9


def test_get_workload_unconfigured_returns_503():
    app = create_app(Settings(prometheus_url=""))
    c = TestClient(app)
    r = c.get("/api/v1/workload/order-service")
    assert r.status_code == 503
    assert "未配置" in r.json()["detail"]


def test_get_workload_query_error_returns_502(monkeypatch):
    def boom(url, params=None, timeout=None):
        return httpx.Response(500, request=httpx.Request("GET", str(url)), json={})
    monkeypatch.setattr(httpx, "get", boom)
    app = create_app(Settings(prometheus_url="http://prom:9090"))
    c = TestClient(app)
    r = c.get("/api/v1/workload/order-service")
    assert r.status_code == 502
