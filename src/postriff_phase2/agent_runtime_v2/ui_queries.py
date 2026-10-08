"""Lane D — authorized, bounded, read-only queries (spec §6.2; G05/G06/G18).

Frozen entry points:
- query_ui_binding(cur, auth, artifact, manifest, request) -> dict UiQueryResultV1 (re-authorized; read-only even if a write
  name is requested; unknown -> denied, never zero)
- query_http(runtime, workspace_id, token, request) -> dict

One request = one `ui_transaction` (verified session, active membership, workspace row lock) that:
1. resolves the artifact in the caller's own scope (foreign/unknown/other-scope ids are the same 404);
2. re-checks the stored manifest (`ui_capabilities.current`: expiry, scope, current role);
3. requires a server-accepted revision (streaming/rejected source has no live data);
4. admits the binding only when the manifest carries it. A write name, an action id or anything else is "unknown
   binding": nothing is called, nothing is written. The OpenUI `Query`/`Mutation` label is never trusted;
5. throttles per principal+artifact through the existing `hosted.throttle` (60/min; stricter existing limits win);
6. validates inputs against the binding's schema (page ≤ 100 rows, window ≤ 366 days, exact IANA zone);
7. runs the existing pure reader inside a SAVEPOINT that is always rolled back, so even a reader that wrote by mistake
   leaves no trace: a query can never change business state;
8. returns `ui_contracts.query_result` (coverage + asOf + sourceRefs; unknown is never zero; `unavailable` carries the
   true reason).
Nothing here calls a model, an HTTP endpoint of this app or the Manager's tool registry.
"""
from __future__ import annotations

import json
import logging
import time

from postriff_alpha.domain import AlphaError

from . import ui_capabilities, ui_contracts, ui_domain
from .ui_domain import common

log = logging.getLogger("postriff.agent_ui")
QUERY_LIMIT_PER_MINUTE = ui_contracts.BOUNDS["queryPerMinute"]
MAX_RESULT_BYTES = 256 * 1024


def _profile_zone(cur, principal) -> str:
    try:
        cur.execute("SAVEPOINT ui_profile_zone")
        cur.execute("SELECT coalesce(time_zone,'') FROM public.pr_profiles WHERE user_id=%s AND deleted_at IS NULL", (principal,))
        row = cur.fetchone()
        cur.execute("RELEASE SAVEPOINT ui_profile_zone")
    except Exception:  # noqa: BLE001 — before migration 011 every person follows UTC here
        cur.execute("ROLLBACK TO SAVEPOINT ui_profile_zone")
        return "UTC"
    value = (row[0] if row else "") or "UTC"
    try:
        return common.zone(value)
    except AlphaError:
        return "UTC"


def domain_context(runtime, cur, auth, artifact, manifest, inputs, *, now=None, founder=None) -> common.DomainContext:
    cur.execute("SELECT revision,state FROM public.pr_workspaces WHERE id=%s", (auth.workspace_id,))
    row = cur.fetchone()
    if not row:
        raise AlphaError("Workspace unavailable.", 403)
    state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    zone = common.zone(inputs.get("zone")) if inputs.get("zone") is not None else _profile_zone(cur, auth.principal)
    return common.DomainContext(runtime=runtime, cur=cur, auth=auth, workspace_id=auth.workspace_id, principal=auth.principal, member=auth.member, state=state,
                                revision=int(row[0]), artifact=artifact, manifest=manifest, now=now if now is not None else time.time(), zone=zone,
                                founder=founder if getattr(auth, "scope", "workspace") == "founder" else None)


def _checked(result) -> dict:
    """The handler's result must be a well-formed UiQueryResultV1 within the size bound; otherwise it is a failure."""
    if not isinstance(result, dict) or result.get("state") not in ui_contracts.DATA_STATES or set(result) != {"state", "data", "asOf", "sourceRefs", "revision",
                                                                                                            "nextCursor", "coverage", "warnings"}:
        raise AlphaError("This data couldn't be read in a form Rafii can show.", 500, code="ui_query_shape")
    if len(ui_contracts.canonical_json(json.loads(json.dumps(result, default=str)), max_depth=None).encode("utf-8")) > MAX_RESULT_BYTES:
        raise AlphaError("This data is too large to show at once. Narrow the filters.", 413, code="ui_query_too_large")
    return result


def run_binding(dctx: common.DomainContext, binding, inputs: dict, cursor: str | None) -> dict:
    """Run one reader read-only: every statement it issues is rolled back (rate counters are written before this)."""
    cur = dctx.cur
    cur.execute("SAVEPOINT ui_query_read")
    try:
        try:
            result = binding.handler(dctx, inputs, cursor)
        except AlphaError as error:
            if error.status == 404:
                # Same answer whether the record is foreign, deleted or never existed.
                result = ui_contracts.query_result("unavailable", note="Not found in this workspace.", warnings=["not_found"], as_of=common.iso(dctx.now))
            elif error.status == 403:
                result = ui_contracts.query_result("denied", note="Your role in this workspace can't read this.", warnings=["forbidden"], as_of=common.iso(dctx.now))
            else:
                raise
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT ui_query_read")
        cur.execute("RELEASE SAVEPOINT ui_query_read")
    return _checked(result)


def query_ui_binding(cur, auth, artifact, manifest, request, *, runtime=None, now=None, founder=None):
    """`founder` is the verified founder scope dict (only the founder route passes it; consumer requests never have one)."""
    started = time.monotonic()
    effective = ui_capabilities.current(cur, auth, manifest)
    ui_capabilities.require_accepted(artifact, int(request.get("artifactRevision") or 0))
    entry = ui_capabilities.query_binding(effective, request.get("bindingId"))
    if entry is None:
        # A write name, an action id, a binding of another journey or scope, or nothing at all: the same refusal, and
        # no reader or command is reached.
        raise AlphaError("Unknown data binding.", 404, code="ui_binding")
    binding = entry["binding"]
    if not ui_capabilities._allows(auth.member, binding.requirement):
        raise AlphaError("Your role in this workspace can't read this.", 403, code="ui_forbidden")
    from ..hosted import throttle
    throttle(cur, f"ui-query:{auth.principal}:{artifact['id']}", QUERY_LIMIT_PER_MINUTE, 60)
    inputs = ui_domain.validate(binding.args, request.get("inputs") or {})
    dctx = domain_context(runtime, cur, auth, artifact, effective, inputs, now=now, founder=founder)
    result = run_binding(dctx, binding, inputs, request.get("cursor"))
    log.info(json.dumps({"event": "ui.query", "binding": binding.name, "state": result["state"], "ms": round((time.monotonic() - started) * 1000, 1)}))
    return result


def founder_scope_of(runtime) -> dict | None:
    """The verified founder scope of a founder runtime (rafii_control.founder_agent._prepare builds it after Boundary.authorize
    at AAL2); None for every consumer runtime. Nothing a client sends can produce it."""
    scope = getattr(runtime, "founder", None)
    return scope if isinstance(scope, dict) and str(scope.get("namespace") or "").startswith("founder:") else None


def query_http(runtime, workspace_id, token, request):
    """Consumer route: workspace-scope artifacts only. Founder route (F's founder_agent_ui passes the founder runtime and its
    capability): founder-scope artifacts of exactly that namespace, with the founder tools' scope."""
    import dataclasses
    from .ui_http import ui_transaction
    founder = founder_scope_of(runtime)
    with ui_transaction(runtime, token, workspace_id, "read") as (cur, auth):
        if founder is not None:
            auth = dataclasses.replace(auth, scope="founder", scope_key=founder["namespace"])
        artifact, manifest = ui_capabilities.load_artifact(cur, auth, request["artifactId"])
        return query_ui_binding(cur, auth, artifact, manifest, request, runtime=runtime, founder=founder)
