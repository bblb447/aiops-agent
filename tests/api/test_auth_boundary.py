import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.authenticator import DenyAllAuthenticator
from app.auth.factory import build_authenticator
from app.config import Settings


# ---- PA8：production fail-closed ----
def test_pa8_production_without_authenticator_is_fail_closed():
    assert isinstance(build_authenticator(Settings(app_env="production", authenticator="")),
                      DenyAllAuthenticator)


def test_pa8_production_forbids_dev_authenticator():
    with pytest.raises(ValueError):
        build_authenticator(Settings(app_env="production", authenticator="dev"))


def test_pa8_production_oidc_jwt_not_implemented():
    with pytest.raises(NotImplementedError):
        build_authenticator(Settings(app_env="production", authenticator="oidc_jwt"))


# ---- PA1：未认证 / 认证器异常 → 401，且不进入 ActionFlow ----
class _NullFlow:
    """任何方法被调用即断言失败 —— 用于证明未认证请求不进入 ActionFlow。"""
    def propose(self, *a, **k):
        raise AssertionError("ActionFlow.propose 不应被调用（未认证）")

    def decide_approval(self, *a, **k):
        raise AssertionError("ActionFlow.decide_approval 不应被调用（未认证）")

    def approval_status(self, *a, **k):
        raise AssertionError("ActionFlow.approval_status 不应被调用（未认证）")


def _client(authenticator, flow=None):
    from app.api.actions import create_actions_router
    app = FastAPI()
    app.include_router(create_actions_router(flow or _NullFlow(), authenticator))
    return TestClient(app)


def test_pa1_unauthenticated_never_reaches_flow():
    c = _client(DenyAllAuthenticator())
    r = c.post("/api/v1/actions/propose", json={"incident_id": "i",
               "action_id": "restart_pod", "target": "pod-1"})
    assert r.status_code == 401


def test_pa1_authenticator_exception_is_fail_closed():
    class _Boom:
        def authenticate(self, ctx):
            raise RuntimeError("IdP down")

    c = _client(_Boom())
    r = c.post("/api/v1/actions/propose", json={"incident_id": "i",
               "action_id": "restart_pod", "target": "pod-1"})
    assert r.status_code == 401          # 401 fail-closed，而非 500


def test_pa1_approval_status_requires_auth():
    assert _client(DenyAllAuthenticator()).get(
        "/api/v1/actions/approvals/xyz").status_code == 401
