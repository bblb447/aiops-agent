import httpx
from app.config import Settings
from app.tools.kubernetes import KubernetesTool
from app.incident.sources import EvidenceSource


def _tool(**kw):
    s = Settings(k8s_api_url="https://k8s.test:6443", k8s_token="tok", **kw)
    return KubernetesTool(s)


def test_unconfigured_kubernetes_returns_failure():
    r = KubernetesTool(Settings()).list_pods("default")
    assert r.success is False
    assert "k8s_api_url" in r.error


def test_list_pods_success_passes_through_and_sets_auth(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None, verify=None):
        captured["url"] = str(url); captured["params"] = params
        captured["headers"] = headers; captured["verify"] = verify
        return httpx.Response(200, request=httpx.Request("GET", str(url)),
                              json={"items": [{"metadata": {"name": "pod-1"}}]})

    monkeypatch.setattr(httpx, "get", fake_get)
    r = _tool().list_pods("prod", label_selector="app=order")
    assert r.success is True
    assert r.tool == "list_pods"
    assert r.data["items"][0]["metadata"]["name"] == "pod-1"
    assert captured["url"] == "https://k8s.test:6443/api/v1/namespaces/prod/pods"
    assert captured["params"] == {"labelSelector": "app=order"}
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["verify"] is True            # 未配 CA 时默认 TLS 校验开启


def test_list_pods_http_error_passes_through_status(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None, verify=None):
        return httpx.Response(403, request=httpx.Request("GET", str(url)),
                              text='{"message":"pods is forbidden"}')

    monkeypatch.setattr(httpx, "get", fake_get)
    r = _tool().list_pods("prod")
    assert r.success is False
    assert "HTTP 403" in r.error
    assert "forbidden" in r.error


def test_list_pods_uses_configured_ca_path(monkeypatch):
    # spec §10：k8s_ca_path 的语义 = TLS CA verification 配置。
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None, verify=None):
        captured["verify"] = verify
        return httpx.Response(200, request=httpx.Request("GET", str(url)), json={})

    monkeypatch.setattr(httpx, "get", fake_get)
    tool = KubernetesTool(Settings(k8s_api_url="https://k8s.test:6443", k8s_ca_path="/etc/ca.crt"))
    tool.list_pods("prod")
    assert captured["verify"] == "/etc/ca.crt"


def test_list_pods_200_non_json_is_structured_failure(monkeypatch):
    # 200 + 非 JSON body：不得让 JSONDecodeError 逸出工具（ToolResult boundary）。
    def fake_get(url, params=None, headers=None, timeout=None, verify=None):
        return httpx.Response(200, request=httpx.Request("GET", str(url)),
                              text="<html>oops</html>")

    monkeypatch.setattr(httpx, "get", fake_get)
    r = _tool().list_pods("prod")   # 不得 raise
    assert r.success is False
    assert "非 JSON" in r.error
    assert "HTTP 200" in r.error
    assert "oops" in r.error


def test_kubernetes_tool_declares_source_type():
    assert KubernetesTool(Settings()).source_type is EvidenceSource.KUBERNETES
