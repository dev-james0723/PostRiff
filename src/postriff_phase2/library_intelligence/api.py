"""Importable Python entry points for other in-process callers (Agent tools, the OpenUI J03 adapter).

Each runs inside the caller's authenticated cursor: membership and state are re-read for (principal, workspace) here,
grants are re-checked, and nothing commits or opens another transaction. The HTTP routes call the same functions.
"""
from __future__ import annotations

import time

from . import contracts as c
from .http import load_member


def context(cur, principal, workspace_id, *, service=None, now=None) -> c.LibraryContext:
    _, state, member = load_member(cur, str(principal), str(workspace_id))
    return c.LibraryContext(workspace_id=str(workspace_id), actor=str(principal), membership=member, state=state, cur=cur,
                            now=now if now is not None else time.time(), service=service)


def search(cur, principal, workspace_id, params, **kw) -> dict:
    from . import search as search_module
    return search_module.search_library(context(cur, principal, workspace_id, **kw), c.search_request(params))


def read(cur, principal, workspace_id, params, **kw) -> dict:
    from . import understanding
    ctx = context(cur, principal, workspace_id, **kw)
    return understanding.card(ctx, c.asset_ref(params.get("assetRef") if isinstance(params, dict) else None))


def answer(cur, principal, workspace_id, params, **kw) -> dict:
    from . import answers
    if not isinstance(params, dict):
        c.fail("Ask a question with a search scope.")
    # answer_library validates the search request itself and requires an explicit scope; do not default one here.
    return answers.answer_library(context(cur, principal, workspace_id, **kw), params.get("question"), params.get("search"))


def apply_action(cur, principal, workspace_id, envelope, **kw) -> dict:
    from . import actions
    return actions.apply(context(cur, principal, workspace_id, **kw), envelope)
