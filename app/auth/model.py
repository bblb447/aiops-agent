from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class AuthMethod(str, Enum):
    OIDC_JWT = "oidc_jwt"   # production human/service principal via OIDC/JWT
    DEV = "dev"             # deterministic local/test authenticator
    SERVICE = "service"     # trusted service principal identity


@dataclass(frozen=True)
class RequestContext:
    """认证所需的只读请求视图；具体载体由 Authenticator 实现决定。"""
    headers: Mapping[str, str]


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    principal_id: str
    auth_method: AuthMethod
    claims: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "claims", MappingProxyType(dict(self.claims)))


@dataclass(frozen=True)
class ActorContext:
    """下游唯一接受的 actor 载体；不可变。"""
    principal_id: str
    auth_method: AuthMethod
    claims: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "claims", MappingProxyType(dict(self.claims)))

    @classmethod
    def from_principal(cls, principal: AuthenticatedPrincipal) -> "ActorContext":
        """request actor 的唯一构造路径（认证边界调用）。"""
        return cls(principal.principal_id, principal.auth_method, principal.claims)
