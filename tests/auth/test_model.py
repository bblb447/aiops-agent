import dataclasses

import pytest

from app.auth.model import ActorContext, AuthMethod, AuthenticatedPrincipal, RequestContext


def test_auth_method_vocabulary_frozen():
    assert {m.value for m in AuthMethod} == {"oidc_jwt", "dev", "service"}


def test_principal_is_frozen():
    p = AuthenticatedPrincipal("alice", AuthMethod.DEV, {})
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.principal_id = "bob"


def test_actor_context_from_principal_carries_identity():
    p = AuthenticatedPrincipal("bob", AuthMethod.OIDC_JWT, {"role": "ops"})
    ctx = ActorContext.from_principal(p)
    assert (ctx.principal_id, ctx.auth_method) == ("bob", AuthMethod.OIDC_JWT)
    assert dict(ctx.claims) == {"role": "ops"}


def test_actor_context_is_frozen():
    ctx = ActorContext("alice", AuthMethod.DEV)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.principal_id = "bob"


def test_request_context_holds_headers_only():
    rc = RequestContext(headers={"x-dev-principal": "alice"})
    assert rc.headers["x-dev-principal"] == "alice"
