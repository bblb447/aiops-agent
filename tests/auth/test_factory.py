import pytest

from app.auth.authenticator import DenyAllAuthenticator, DevAuthenticator
from app.auth.factory import build_authenticator, resolve_executor_principal_id
from app.config import Settings


def _s(**kw):
    return Settings(**kw)


def test_dev_env_default_is_dev_authenticator():
    assert isinstance(build_authenticator(_s(app_env="development")), DevAuthenticator)


def test_production_with_dev_is_configuration_error():
    with pytest.raises(ValueError):
        build_authenticator(_s(app_env="production", authenticator="dev"))


def test_production_without_authenticator_is_fail_closed():
    assert isinstance(build_authenticator(_s(app_env="production", authenticator="")),
                      DenyAllAuthenticator)


def test_production_with_oidc_jwt_is_not_implemented_yet():
    with pytest.raises(NotImplementedError):
        build_authenticator(_s(app_env="production", authenticator="oidc_jwt"))


def test_unknown_authenticator_rejected():
    with pytest.raises(ValueError):
        build_authenticator(_s(app_env="development", authenticator="magic"))


def test_executor_principal_id_returned_when_configured():
    assert resolve_executor_principal_id(_s(executor_principal_id="exec-svc")) == "exec-svc"


@pytest.mark.parametrize("blank", ["", "   "])
def test_production_blank_executor_principal_id_is_configuration_error(blank):
    with pytest.raises(ValueError):
        resolve_executor_principal_id(_s(app_env="production", executor_principal_id=blank))


def test_dev_blank_executor_principal_id_falls_back_to_provenance_label():
    assert resolve_executor_principal_id(_s(app_env="development")) == "executor-service"
