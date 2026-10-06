import httpx
import pytest

from app.actions.inventory import CMDBInventoryResolver, parse_target_descriptor
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


def _resolver(handler, url="http://cmdb"):
    return CMDBInventoryResolver(url, transport=httpx.MockTransport(handler))


def test_resolve_returns_descriptor_on_200():
    def h(req):
        assert req.url.path == "/targets/dep-1"
        return httpx.Response(200, json={"kind": "deployment", "environment": "staging", "replicas": 3})
    assert _resolver(h).resolve("dep-1") == TargetDescriptor("deployment", "staging", 3)


def test_unconfigured_url_returns_none():
    assert CMDBInventoryResolver("").resolve("any") is None


@pytest.mark.parametrize("status", [403, 404, 500])
def test_non_200_returns_none(status):
    assert _resolver(lambda req: httpx.Response(status)).resolve("x") is None


def test_non_json_200_returns_none():
    assert _resolver(lambda req: httpx.Response(200, text="<html>ok</html>")).resolve("x") is None


def test_malformed_200_body_returns_none():
    assert _resolver(lambda req: httpx.Response(200, json={"environment": "prod"})).resolve("x") is None


def test_connection_error_returns_none():
    def h(req):
        raise httpx.ConnectError("down")
    assert _resolver(h).resolve("x") is None


def test_resolver_never_raises_on_unexpected_error():
    def h(req):
        raise RuntimeError("boom")
    assert _resolver(h).resolve("x") is None


@pytest.mark.parametrize("url", ["http://cmdb", "http://cmdb/"])
def test_target_is_url_encoded_and_no_double_slash(url):
    seen = {}

    def h(req):
        seen["raw"] = req.url.raw_path
        return httpx.Response(200, json={"kind": "pod", "environment": "prod", "replicas": None})
    _resolver(h, url=url).resolve("a/b c")
    assert b"a%2Fb%20c" in seen["raw"]        # '/' 与空格被编码，不越出 /targets/
    assert b"//targets/" not in seen["raw"]   # 尾斜杠 url 不产生 //targets/
