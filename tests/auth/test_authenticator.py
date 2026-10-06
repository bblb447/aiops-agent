from app.auth.authenticator import DenyAllAuthenticator, DevAuthenticator
from app.auth.model import AuthMethod, RequestContext


def test_dev_authenticator_reads_principal_header():
    a = DevAuthenticator()
    p = a.authenticate(RequestContext(headers={"x-dev-principal": "alice"}))
    assert p is not None and p.principal_id == "alice" and p.auth_method is AuthMethod.DEV


def test_dev_authenticator_missing_header_is_unauthenticated():
    assert DevAuthenticator().authenticate(RequestContext(headers={})) is None


def test_dev_authenticator_blank_principal_is_unauthenticated():
    assert DevAuthenticator().authenticate(
        RequestContext(headers={"x-dev-principal": "  "})) is None


def test_denyall_always_none():
    assert DenyAllAuthenticator().authenticate(
        RequestContext(headers={"x-dev-principal": "alice"})) is None
