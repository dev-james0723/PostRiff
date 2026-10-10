"""Target re-validation (CF-3 §6.3 step 4, correction 9): every id a step or approval names is re-resolved inside the step's own
workspace at claim and at decision time. A missing or foreign target blocks the step (`target_changed`); nothing is ever
resolved across workspaces. Resolvers read the locked workspace state only (no provider, no other tenant)."""
from __future__ import annotations

import json

RESOLVERS: dict = {}
SOURCE_DOMAINS = {'campaign': 'campaigns', 'draft': 'content', 'job': 'content', 'post': 'content',
                  'asset': 'library', 'library_asset': 'library', 'library_collection': 'library',
                  'channel': 'connections', 'automation': 'automations'}


def required_domains(refs):
    """Only typed server-validated provenance adds grants; legacy untyped refs keep their contract."""
    domains = set()
    for ref in refs or ():
        if not isinstance(ref, dict) or not ref.get('type'):
            continue
        if ref['type'] not in SOURCE_DOMAINS:
            raise ValueError('Unknown source domain for a typed task reference')
        domains.add(SOURCE_DOMAINS[ref['type']])
    return domains


def resolver(kind: str):
    def wrap(fn):
        RESOLVERS[kind] = fn
        return fn
    return wrap


@resolver("draft")
def _draft(state, ident):
    return any(isinstance(v, dict) and v.get("id") == ident for v in state.get("variants") or [])


@resolver("job")
def _job(state, ident):
    return any(isinstance(j, dict) and j.get("id") == ident for j in (state.get("phase2") or {}).get("jobs") or [])


@resolver("post")
def _post(state, ident):
    return _job(state, ident)


@resolver("asset")
def _asset(state, ident):
    return any(isinstance(a, dict) and a.get("id") == ident for a in (state.get("phase2") or {}).get("assets") or [])


@resolver("campaign")
def _campaign(state, ident):
    root = ((state.get("raffi") or {}).get("campaignPlanning") or {})
    return any(isinstance(c, dict) and c.get("id") == ident for c in root.get("campaigns") or [])


@resolver("automation")
def _automation(state, ident):
    root = ((state.get("raffi") or {}).get("campaignPlanning") or {})
    return any(isinstance(t, dict) and t.get("id") == ident for t in root.get("recurringTasks") or [])


def workspace_state(cur, workspace_id: str) -> dict:
    cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace_id,))
    row = cur.fetchone()
    if not row:
        return {}
    return json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})


def present(state: dict, ref: dict) -> bool:
    fn = RESOLVERS.get(str(ref.get("type") or ""))
    if fn is None:
        return False          # fail closed: a target kind nobody can re-read is treated as changed
    try:
        ident = str(ref.get("id") or "")
        if not fn(state, ident):
            return False
        return "revision" not in ref or revision(state, ref["type"], ident) == ref["revision"]
    except Exception:  # noqa: BLE001
        return False


def all_present(cur, workspace_id: str, refs: list) -> bool:
    if not refs:
        return True
    state = workspace_state(cur, workspace_id)
    return all(present(state, ref) for ref in refs if isinstance(ref, dict))


@resolver("channel")
def _channel(state, ident):
    return any(c.get("id") == ident for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict))


def revision(state, kind, ident):
    if kind == 'draft':
        item = next((v for v in state.get('variants', []) if v.get('id') == ident), {})
        return item.get('revision')
    if kind == 'campaign':
        items = ((state.get('raffi') or {}).get('campaignPlanning') or {}).get('campaigns') or []
        return next((c.get('version') for c in items if c.get('id') == ident), None)
    return None


def planned_refs(ctx, inputs, *, state=None):
    """Only targets observed in this human turn may enter a durable plan."""
    from postriff_alpha.domain import AlphaError
    known = set(ctx.ledger.known_ids) | {str(r.get("id")).lower() for r in ctx.chip_refs if isinstance(r, dict) and r.get("id")}
    names = {"draft": "draft", "variant": "draft", "campaign": "campaign", "job": "job", "post": "post", "asset": "asset",
             "referenceAsset": "asset", "channel": "channel", "automation": "automation"}
    refs = []
    for key, value in inputs.items():
        if not key.endswith(("Id", "Ids")):
            continue
        stem = key[:-3] if key.endswith("Ids") else key[:-2]
        kind = names.get(stem)
        values = value if isinstance(value, list) else [value]
        for ident in values:
            if not isinstance(ident, str) or ident.lower() not in known or kind is None:
                raise AlphaError("Read the target or select its reference before planning this step.", 400, code="tool_input")
            if state is None:
                state = ctx.snapshot()["state"]
            version = revision(state, kind, ident)
            refs.append({"type": kind, "id": ident, **({"revision": version} if version is not None else {})})
    return refs
