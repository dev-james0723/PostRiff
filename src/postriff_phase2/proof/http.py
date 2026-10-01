"""Routes under ``/api/workspaces/{id}/proof`` (registered in ``growth_v2_routes.RESOURCES``).

GET  …/proof/proofs?frequency=&cursor=&limit=      proofs with their latest revision (25 by default, at most 50)
GET  …/proof/proofs/{proofId}                      one proof with its revisions and next-step proposals
GET  …/proof/proofs/{proofId}/revisions/{n}        one revision (prior revisions are kept)
POST …/proof/refresh {frequency, periodStart?}     owner: recompute a completed period from stored records (no paid I/O)
GET  …/proof/strategy?status=&cursor=&limit=       next-week decisions and what is in effect
POST …/proof/strategy/{decisionId}/decide          owner: accept | edit | reject | revoke (idempotent, expected revision)

Session tokens only; the workspace id in the path selects, the repository transaction authorizes.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from postriff_alpha.domain import AlphaError

from . import require as require_enabled


def ensure(hosted):
    if getattr(hosted, "proof", None) is None:
        from .service import ProofService
        hosted.proof = ProofService(hosted)
    return hosted.proof


def _query(environ, key):
    return (parse_qs(environ.get("QUERY_STRING", "")).get(key) or [None])[0]


def handle(app, environ, start_response, hosted, token, method, parts):
    require_enabled()
    if str(token).startswith("prt_"):
        raise AlphaError("API tokens can't use Rafii proof routes.", 403)
    service = ensure(hosted)
    workspace_id, rest = parts[2], parts[4:]
    if method == "GET" and rest == ["proofs"]:
        return app._json(start_response, 200, service.list(workspace_id, token, _query(environ, "frequency"), _query(environ, "cursor"), _query(environ, "limit")))
    if method == "GET" and len(rest) == 2 and rest[0] == "proofs":
        return app._json(start_response, 200, service.get(workspace_id, token, rest[1]))
    if method == "GET" and len(rest) == 4 and rest[0] == "proofs" and rest[2] == "revisions":
        return app._json(start_response, 200, service.revision(workspace_id, token, rest[1], rest[3]))
    if method == "POST" and rest == ["refresh"]:
        return app._json(start_response, 200, service.refresh(workspace_id, token, app._body(environ)))
    if method == "GET" and rest == ["strategy"]:
        return app._json(start_response, 200, service.strategy(workspace_id, token, _query(environ, "status"), _query(environ, "cursor"), _query(environ, "limit")))
    if method == "POST" and len(rest) == 3 and rest[0] == "strategy" and rest[2] == "decide":
        return app._json(start_response, 200, service.decide(workspace_id, token, rest[1], app._body(environ)))
    raise AlphaError("Proof route unavailable.", 404)
