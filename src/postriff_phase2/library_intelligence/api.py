"""Importable Python entry points for other in-process callers (Agent tools, the OpenUI J03 adapter).

Each runs inside the caller's authenticated cursor: membership and state are re-read for (principal, workspace) here,
grants are re-checked, and nothing commits or opens another transaction. The HTTP routes call the same functions.

MODEL-BOUND RESULTS: any caller that puts search results or an item card in front of a model (the Agent, OpenUI task
surfaces, source packs, background generation) MUST pass `for_model=True` to `search` and `read`. That forces the
`answer` purpose plus a ('cloud', 'llm') processing grant, so storage-only items and items without both grants never
reach a model, and `read` withholds passage text and content-derived fields unless that decision allows them. Browsing
permission alone never authorizes showing content to a model.
"""
from __future__ import annotations

import time

from . import contracts as c
from .http import load_member


_MOUNTED = {"service": None}
MODEL_PROCESSING = {"location": "cloud", "category": "llm"}
WITHHELD_FIELDS = ("summary", "topics", "suggestedUses", "annotations")


def mount(service):
    """The hosted service this process serves (set when LibraryIntelligence is mounted). In-process callers that do not pass
    `service=` still get repository effects (e.g. voice revocation staling the growth genome) through it."""
    _MOUNTED["service"] = service


def context(cur, principal, workspace_id, *, service=None, now=None) -> c.LibraryContext:
    _, state, member = load_member(cur, str(principal), str(workspace_id))
    return c.LibraryContext(workspace_id=str(workspace_id), actor=str(principal), membership=member, state=state, cur=cur,
                            now=now if now is not None else time.time(), service=service if service is not None else _MOUNTED["service"])


def search(cur, principal, workspace_id, params, *, for_model: bool = False, **kw) -> dict:
    """search_library for in-process callers. for_model=True (required whenever results reach a model) forces the
    answer purpose and a cloud/llm processing grant, applied before ranking."""
    from . import search as search_module
    ctx = context(cur, principal, workspace_id, **kw)
    if for_model:
        request = c.search_request({**params, "purpose": "answer"} if isinstance(params, dict) else params)
        return search_module.search_library(ctx, request, processing=MODEL_PROCESSING)
    return search_module.search_library(ctx, c.search_request(params))


def read(cur, principal, workspace_id, params, *, for_model: bool = False, **kw) -> dict:
    """The item's understanding card. for_model=True (required whenever the card reaches a model) keeps passage text and
    content-derived fields only when answer + cloud/llm processing is allowed for this exact version, re-checked now."""
    from . import policy, understanding, versions
    ctx = context(cur, principal, workspace_id, **kw)
    ref = c.asset_ref(params.get("assetRef") if isinstance(params, dict) else None)
    card = understanding.card(ctx, ref)
    if not for_model:
        return card
    decision = policy.recheck(ctx, policy.authorize_source(ctx, versions.resolve(ctx, ref), "answer", MODEL_PROCESSING))
    if decision.allowed:
        return {**card, "modelAccess": {"allowed": True, "attributionOnly": decision.attribution_only}}
    safe = {k: v for k, v in card.items() if k not in WITHHELD_FIELDS}
    safe["usefulSegments"] = [{k: v for k, v in s.items() if k != "text"} for s in card.get("usefulSegments") or []]
    safe["modelAccess"] = {"allowed": False, "reason": decision.reason, "message": policy.message(decision.reason)}
    return safe


def answer(cur, principal, workspace_id, params, **kw) -> dict:
    from . import answers
    if not isinstance(params, dict):
        c.fail("Ask a question with a search scope.")
    # answer_library validates the search request itself and requires an explicit scope; do not default one here.
    return answers.answer_library(context(cur, principal, workspace_id, **kw), params.get("question"), params.get("search"))


def apply_action(cur, principal, workspace_id, envelope, **kw) -> dict:
    from . import actions
    return actions.apply(context(cur, principal, workspace_id, **kw), envelope)
