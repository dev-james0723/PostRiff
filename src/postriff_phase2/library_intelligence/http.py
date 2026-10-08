"""HTTP surface for Library intelligence: /api/workspaces/{ws}/library/intelligence/...

The coordinator owns this table. Handlers live in their workstream modules and take (ctx, request) -> dict; a dict
with "_status" sets the response status. Reads use a verified, non-locking context; writes use the workspace
transaction. Identity always comes from the session or API token, never from the body.
"""
from __future__ import annotations

import importlib
import json
import time
import uuid
from contextlib import contextmanager

from postriff_alpha.domain import AlphaError

from ..permissions import Membership
from . import contracts as c

KEY = "{key}"
# (method, path after .../library/intelligence/, module, function, mode)
ROUTES = (
    ("POST", ("search",), "search", "search_http", "read"),
    ("POST", ("answer",), "answers", "answer_http", "read"),
    ("POST", ("viewer",), "citations", "viewer_http", "read"),
    ("GET", ("assets", KEY), "understanding", "card_http", "read"),
    ("GET", ("assets", KEY, "segments"), "segments", "segments_http", "read"),
    ("GET", ("assets", KEY, "capabilities"), "capabilities", "capabilities_http", "read"),
    ("POST", ("assets", KEY, "process"), "jobs", "request_http", "write"),
    ("POST", ("assets", KEY, "cancel"), "jobs", "cancel_http", "write"),
    ("POST", ("assets", KEY, "waveform"), "media", "waveform_http", "write"),
    ("GET", ("assets", KEY, "related"), "relations", "related_http", "read"),
    ("GET", ("assets", KEY, "versions"), "comparison", "versions_http", "read"),
    ("GET", ("assets", KEY, "usage"), "usage", "usage_http", "read"),
    ("GET", ("assets", KEY, "voice"), "voice", "asset_voice_http", "read"),
    ("POST", ("compare",), "comparison", "compare_http", "read"),
    ("POST", ("actions",), "actions", "apply_http", "write"),
    ("GET", ("grants",), "policy_http", "list_http", "read"),
    ("POST", ("grants",), "policy_http", "grant_http", "write"),
    ("DELETE", ("grants", KEY), "policy_http", "revoke_http", "write"),
    ("POST", ("ingest", "link"), "intake", "link_http", "write"),
    ("POST", ("ingest", "note"), "intake", "note_http", "write"),
    ("POST", ("collections", "preview"), "collections", "preview_http", "read"),
    ("GET", ("collections", KEY), "collections", "collection_http", "read"),
    ("POST", ("source-packs",), "source_packs", "recommend_http", "write"),
    ("GET", ("source-packs", KEY), "source_packs", "pack_http", "read"),
    ("GET", ("suggestions",), "suggestions", "inbox_http", "read"),
    ("GET", ("voice",), "voice", "summary_http", "read"),
    ("GET", ("status",), "telemetry", "status_http", "read"),
)


def match(method: str, rest: list[str]):
    for verb, pattern, module, function, mode in ROUTES:
        if verb != method or len(pattern) != len(rest):
            continue
        params, ok = {}, True
        for want, got in zip(pattern, rest):
            if want == KEY:
                if not c.KEY.fullmatch(got.replace("-", "").lower()):
                    raise AlphaError("This item is unavailable.", 404, code="library_unavailable")
                params["key"] = got.replace("-", "").lower()
            elif want != got:
                ok = False
                break
        if ok:
            return module, function, mode, params
    return None


def _workspace(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise AlphaError("Workspace unavailable.", 403) from None


def load_member(cur, principal, workspace_id, *, lock: bool = False):
    from ..hosted import MEMBER_COLUMNS
    cur.execute(f"SELECT w.revision,w.state,{MEMBER_COLUMNS} FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id "
                "JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL"
                + (" FOR UPDATE OF w" if lock else ""), (workspace_id, principal))
    row = cur.fetchone()
    if not row:
        raise AlphaError("Workspace unavailable.", 403)
    state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    if state.get("accountDeletion"):
        raise AlphaError("Account deletion is pending. Only deletion can continue.", 409, code="account_deletion_pending")
    if state.get("accountBlock"):
        from ..operator_actions import blocked_error
        raise blocked_error()
    return row, state, Membership.from_row(*row[2:7])


@contextmanager
def read_context(service, token, workspace_id):
    """Verified identity and membership without locking the workspace row (searches run concurrently)."""
    workspace_id = _workspace(workspace_id)
    repo = service.repository
    from ..api_tokens import is_api_token
    api_grant = repo.api_tokens.resolve(token, workspace_id) if is_api_token(token) else None
    principal = api_grant["createdBy"] if api_grant else repo.verify_session(token)
    with repo.connection_factory() as db, db.cursor() as cur:
        row, state, member = load_member(cur, principal, workspace_id)
        if api_grant:
            repo.api_tokens.validate(cur, token, workspace_id)
        ctx = c.LibraryContext(workspace_id=workspace_id, actor=str(principal), membership=member, state=state, cur=cur,
                               now=service.clock() if callable(getattr(service, "clock", None)) else time.time(), service=service)
        ctx.reopen = lambda: read_context(service, token, workspace_id)
        yield ctx


@contextmanager
def write_context(service, token, workspace_id):
    workspace_id = _workspace(workspace_id)
    with service.repository.transaction(token, workspace_id) as (cur, row, principal):
        state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        ctx = c.LibraryContext(workspace_id=workspace_id, actor=str(principal), membership=Membership.from_row(*row[2:7]), state=state, cur=cur,
                               now=service.clock() if callable(getattr(service, "clock", None)) else time.time(), service=service)
        ctx.caches["workspaceRevision"] = int(row[0])
        ctx.reopen = lambda: read_context(service, token, workspace_id)
        yield ctx


def dispatch(service, method: str, workspace_id: str, rest: list[str], query: dict, body_reader, token):
    """Returns (status, payload). Unknown paths 404 like the rest of the hosted API."""
    found = match(method, rest)
    if found is None:
        raise AlphaError("This hosted route is unavailable.", 404)
    module_name, function_name, mode, params = found
    body = body_reader() if method in ("POST", "PATCH", "DELETE") else {}
    try:
        module = importlib.import_module(f"{__package__}.{module_name}")
        handler = getattr(module, function_name)
    except (ImportError, AttributeError):
        raise AlphaError("This Library capability is not available in this build.", 503, code="library_capability_unavailable") from None
    opener = read_context if mode == "read" else write_context
    with opener(service, token, workspace_id) as ctx:
        ctx.require("read")
        result = handler(ctx, {"params": params, "query": query, "body": body if isinstance(body, dict) else {}})
    status = 200
    if isinstance(result, dict) and "_status" in result:
        status = int(result.pop("_status"))
    return status, result
