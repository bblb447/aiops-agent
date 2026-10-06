from typing import Protocol

from app.auth.model import AuthMethod, AuthenticatedPrincipal, RequestContext

_DEV_PRINCIPAL_HEADER = "x-dev-principal"


class Authenticator(Protocol):
    def authenticate(self, ctx: RequestContext) -> AuthenticatedPrincipal | None: ...


class DevAuthenticator:
    """本地 deterministic authenticator：仅 test/dev 使用（production 由 factory 禁用）。"""

    def authenticate(self, ctx: RequestContext) -> AuthenticatedPrincipal | None:
        raw = ctx.headers.get(_DEV_PRINCIPAL_HEADER)
        if raw is None or not raw.strip():
            return None
        return AuthenticatedPrincipal(raw.strip(), AuthMethod.DEV)


class DenyAllAuthenticator:
    """fail-closed 默认：永不认证（production 无配置时的安全缺省）。"""

    def authenticate(self, ctx: RequestContext) -> AuthenticatedPrincipal | None:
        return None
