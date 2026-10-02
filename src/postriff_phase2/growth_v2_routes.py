"""One route table for the RAFII Product Growth program (PRD R-ENG-01/02).

`hosted_app` calls ``public`` before its origin/session guard (signed webhooks, tracking redirects) and ``handle`` for
``/api/workspaces/{id}/<resource>/…``. Each resource module is imported lazily and owns its own service, so a slice
never edits the shared application file. Every authenticated handler derives workspace and actor authority from the
session token through the existing repository transaction; a workspace id in the path selects a target, it does not
grant access. API tokens never reach these routes (``api_tokens`` allowlists explicitly).
"""
from __future__ import annotations

import importlib

# resource segment (parts[3]) → module with handle(app, environ, start_response, hosted, token, method, parts)
RESOURCES = {
    "first-week": "postriff_phase2.first_week.http",
    "source-uploads": "postriff_phase2.source_uploads.http",
    "relationships": "postriff_phase2.relationships.http",
    "results": "postriff_phase2.results.http",
    "series": "postriff_phase2.series.http",
    "visual-packs": "postriff_phase2.visual_pack.http",
    "briefs": "postriff_phase2.briefs.http",
    "proof": "postriff_phase2.proof.http",
}
# modules with public(app, environ, start_response, method, path) → response or None, consulted in this order
PUBLIC = (
    "postriff_phase2.results.http",
)
# modules with tick(hosted, deadline) → JSON-safe summary; each step is bounded, flag-gated and never raises
CRON = (
    "postriff_phase2.source_uploads.jobs",
    "postriff_phase2.relationships.jobs",
    "postriff_phase2.visual_pack.jobs",
    "postriff_phase2.series.jobs",
    "postriff_phase2.briefs.jobs",
    "postriff_phase2.proof.jobs",
)


def _module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name and name.startswith(error.name):
            return None     # slice not present in this build
        raise


def public(app, environ, start_response, method, path):
    if path == "/api/plans" and method == "GET":
        return plans(app, start_response)
    if path == "/api/growth-features" and method == "GET":
        # Public pages may only learn whether the first-week continuation exists (the anonymous Post Doctor offers it).
        return app._json(start_response, 200, {"features": {"firstWeek": feature_state()["firstWeek"]}})
    if not path.startswith(("/api/results/", "/api/l/")):
        return None
    for name in PUBLIC:
        module = _module(name)
        if module is not None and hasattr(module, "public"):
            routed = module.public(app, environ, start_response, method, path)
            if routed is not None:
                return routed
    return None


# Which program features this deployment has switched on, from each slice's own flag function (module, function).
# The web reads this once and never asks a switched-off resource (whose 404 would be noise on every shared page).
FEATURES = {
    "firstWeek": ("postriff_phase2.first_week.service", "enabled"),
    "sourceUploads": ("postriff_phase2.source_uploads.limits", None),
    "relationships": ("postriff_phase2.relationships.service", "enabled"),
    "results": ("postriff_phase2.results.service", "enabled"),
    "series": ("postriff_phase2.series.model", "enabled"),
    "visualPacks": ("postriff_phase2.visual_pack.service", "enabled"),
    "briefs": ("postriff_phase2.briefs.service", "enabled"),
    "proof": ("postriff_phase2.proof.service", "enabled"),
}


def feature_state():
    """{feature: bool}. A slice missing from the build, or whose flag check fails, is off (never guessed on)."""
    state = {}
    for key, (name, function) in FEATURES.items():
        try:
            module = _module(name)
            if module is None:
                state[key] = False
            elif function is None:     # source uploads: its limits carry the flag with the preview-isolated environment
                state[key] = bool(module.Policy.from_environment().enabled)
            else:
                state[key] = bool(getattr(module, function)())
        except Exception:
            state[key] = False
    if state["firstWeek"]:
        from .coworker import flags
        state["firstWeek"] = flags.enabled("RAFII_WEEKLY_OPERATOR_ENABLED")   # the first week drives the Weekly Operator
    return state


def handles(parts):
    return len(parts) >= 4 and parts[:2] == ["api", "workspaces"] and (parts[3] in RESOURCES or parts[3:] == ["growth-features"])


def handle(app, environ, start_response, hosted, token, method, parts):
    from postriff_alpha.domain import AlphaError
    if parts[3:] == ["growth-features"]:
        if method not in ("GET", "HEAD"):
            raise AlphaError("Method not allowed.", 405)
        from .hosted import _membership
        from .permissions import require
        with hosted.repository.transaction(token, parts[2]) as (_cur, row, _principal):
            require(_membership(row), "read")   # members only, although it reveals nothing but switch states
        return app._json(start_response, 200, {"features": feature_state()})
    module = _module(RESOURCES[parts[3]])
    if module is None:
        raise AlphaError("This feature is not available.", 404, code="feature_disabled")
    return module.handle(app, environ, start_response, hosted, token, method, parts)


def cron(hosted, deadline):
    """Run each present slice's bounded background step until ``deadline`` (time.monotonic()). One slice failing never
    stops the others; the summary carries only counts and status codes."""
    import time
    summary = {}
    for name in CRON:
        if time.monotonic() >= deadline:
            summary[name.rsplit(".", 2)[-2]] = {"status": "deferred"}
            continue
        module = _module(name)
        if module is None or not hasattr(module, "tick"):
            continue
        try:
            summary[name.rsplit(".", 2)[-2]] = module.tick(hosted, deadline)
        except Exception as error:  # noqa: BLE001 - a background step must never fail the cron response
            summary[name.rsplit(".", 2)[-2]] = {"status": "unavailable", "reason": type(error).__name__}
    return summary


def plans(app, start_response):
    """Public, read-only plan catalog for the active pricing version (R-COM-04): the one source public pages, in-app
    plan cards and checkout agree on. No identity, no write, no client-supplied price."""
    from .plan_pricing import public_catalog
    service = app._runtime()
    with service.connection_factory() as db, db.cursor() as cur:
        # Creator is purchasable only where its credits can be spent (the credit ledger is on), as checkout requires.
        catalog = public_catalog(cur, service.billing.pricing_v2_enabled, credits_enabled=getattr(service.ledger, "credits", None) is not None)
    return app._json(start_response, 200, catalog)
