"""Grant routes. Grants are explicit, scoped, revocable and audited; see policy.py."""
from . import policy


def list_http(ctx, request):
    return policy.list_grants(ctx)


def grant_http(ctx, request):
    return {**policy.grant(ctx, request["body"]), "_status": 201}


def revoke_http(ctx, request):
    body = request["body"] or {}
    expected = body.get("expectedRevision")
    return policy.revoke(ctx, request["params"]["key"], expected if type(expected) is int else None)
