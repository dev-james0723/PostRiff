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
    "source-uploads": "postriff_phase2.first_week.intake_http",
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


def _module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name and name.startswith(error.name):
            return None     # slice not present in this build
        raise


def public(app, environ, start_response, method, path):
    if not path.startswith(("/api/results/", "/api/l/")):
        return None
    for name in PUBLIC:
        module = _module(name)
        if module is not None and hasattr(module, "public"):
            routed = module.public(app, environ, start_response, method, path)
            if routed is not None:
                return routed
    return None


def handles(parts):
    return len(parts) >= 4 and parts[:2] == ["api", "workspaces"] and parts[3] in RESOURCES


def handle(app, environ, start_response, hosted, token, method, parts):
    from postriff_alpha.domain import AlphaError
    module = _module(RESOURCES[parts[3]])
    if module is None:
        raise AlphaError("This feature is not available.", 404, code="feature_disabled")
    return module.handle(app, environ, start_response, hosted, token, method, parts)
