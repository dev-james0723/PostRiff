"""HTTP routes for the coworker upgrade (architecture lock §3). Mounted from hosted_app with two calls:

- `public(app, environ, start_response, method, path)`: the email-provider webhook and one-click unsubscribe,
  matched before the application's origin guard (like the Stripe webhook): they authenticate by signature/token;
- `handle(app, environ, start_response, service, token, method, parts)`: workspace routes, after the origin guard,
  session tokens only (API tokens have no coworker scope).

Every workspace route re-checks membership in the repository transaction; the service layer re-checks the permission
class for each mutation and re-reads what it changed.
"""
from __future__ import annotations

import html
from urllib.parse import parse_qs

from postriff_alpha.domain import AlphaError

from . import runtime

RESOURCES = ("coworker", "notifications", "notification-preferences", "push-subscriptions")
MAX_WEBHOOK = 65_536


def _query(environ, key):
    return (parse_qs(environ.get("QUERY_STRING", "")).get(key) or [None])[0]


def _page(start_response, status, title, message, form_token=None):
    """A tiny, dependency-free HTML page for the unsubscribe link (no scripts, no external assets)."""
    e = html.escape
    button = ""
    if form_token:
        button = (f'<form method="post" action="/api/notifications/unsubscribe?token={e(form_token)}">'
                  '<button type="submit" style="font:inherit;padding:12px 20px;border-radius:999px;border:0;background:#111;color:#fff">Unsubscribe</button></form>')
    body = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="color-scheme" content="light dark"><title>{e(title)}</title></head>'
            f'<body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:480px;margin:48px auto;padding:0 16px;line-height:1.5">'
            f'<h1 style="font-family:Georgia,serif;font-weight:600">{e(title)}</h1><p>{e(message)}</p>{button}</body></html>').encode()
    start_response(status, [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                            ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
                            ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")])
    return [body]


def public(app, environ, start_response, method, path):
    if path == "/api/notifications/email/webhook" and method == "POST":
        service = runtime.ensure(app._runtime())
        length = int(environ.get("CONTENT_LENGTH") or "0")
        if not 0 < length <= MAX_WEBHOOK:
            raise AlphaError("Webhook body size invalid.", 413)
        raw = environ["wsgi.input"].read(length)
        headers = {"svix-id": environ.get("HTTP_SVIX_ID"), "svix-timestamp": environ.get("HTTP_SVIX_TIMESTAMP"), "svix-signature": environ.get("HTTP_SVIX_SIGNATURE")}
        if not service.notifications.enabled():
            raise AlphaError("Email webhooks are not enabled.", 404, code="feature_disabled")
        return app._json(start_response, 200, service.notifications.provider_webhook(headers, raw))
    if path == "/api/notifications/unsubscribe" and method in ("GET", "POST"):
        service = runtime.ensure(app._runtime())
        token = _query(environ, "token") or ""
        try:
            if method == "GET":
                service.notifications.unsubscribe(token, apply=False)
                return _page(start_response, "200 OK", "Unsubscribe from Rafii emails?", "You'll stop receiving these notification emails. Security and billing notices still reach you.", token)
            result = service.notifications.unsubscribe(token, apply=True)
            if not result.get("unsubscribed"):
                return _page(start_response, "409 Conflict", "Not changed", "Your email settings could not be changed. Try again from Rafii's notification settings.")
            return _page(start_response, "200 OK", "You're unsubscribed", "You won't receive these emails any more. You can turn them back on in Rafii's notification settings.")
        except AlphaError as error:
            return _page(start_response, f"{error.status} Error", "This link can't be used", str(error))
    return None


def handle(app, environ, start_response, service, token, method, parts):
    """parts = ['api','workspaces',{id},<resource>, ...]."""
    if str(token).startswith("prt_"):
        raise AlphaError("API tokens can't use Rafii coworker routes.", 403)
    runtime.ensure(service)
    workspace_id, resource, rest = parts[2], parts[3], parts[4:]
    notifications, coworker = service.notifications, service.coworker
    body = (lambda: app._body(environ))
    json_ = (lambda status, value: app._json(start_response, status, value))
    if resource == "notifications":
        if not rest and method == "GET":
            before = _query(environ, "before")
            return json_(200, notifications.center(workspace_id, token, before=float(before) if before and before.replace(".", "", 1).isdigit() else None,
                                                   unread_only=_query(environ, "unread") == "1"))
        if len(rest) == 2 and method == "POST":
            body()
            return json_(200, notifications.mark(workspace_id, token, rest[0], rest[1]))
    if resource == "notification-preferences" and not rest:
        if method == "GET":
            return json_(200, notifications.preferences(workspace_id, token))
        if method == "PATCH":
            return json_(200, notifications.set_preference(workspace_id, token, body()))
    if resource == "push-subscriptions":
        if not rest and method == "GET":
            return json_(200, notifications.push_devices(workspace_id, token))
        if not rest and method == "POST":
            from ..hosted_app import client_label
            return json_(201, notifications.subscribe_push(workspace_id, token, body(), client_label(environ)))
        if rest == ["unsubscribe"] and method == "POST":
            return json_(200, notifications.unsubscribe_push(workspace_id, token, endpoint=body().get("endpoint")))
        if len(rest) == 1 and method == "DELETE":
            return json_(200, notifications.unsubscribe_push(workspace_id, token, subscription_id=rest[0]))
    if resource == "coworker" and rest:
        area, tail = rest[0], rest[1:]
        if area == "status" and method == "GET":
            return json_(200, coworker.status(workspace_id, token))
        if area == "attention" and method == "GET":
            return json_(200, coworker.attention(workspace_id, token))
        if area == "weekly":
            if not tail and method == "GET":
                return json_(200, coworker.weekly_list(workspace_id, token))
            if tail == ["recipes"] and method == "POST":
                return json_(201, coworker.weekly_save_recipe(workspace_id, token, body()))
            if len(tail) == 2 and tail[0] == "recipes" and method == "PATCH":
                return json_(200, coworker.weekly_save_recipe(workspace_id, token, body(), tail[1]))
            if len(tail) == 3 and tail[0] == "recipes" and tail[2] == "status" and method == "POST":
                return json_(200, coworker.weekly_recipe_status(workspace_id, token, tail[1], body().get("status")))
            if len(tail) == 3 and tail[0] == "recipes" and tail[2] == "prepare" and method == "POST":
                payload = body()
                return json_(200, coworker.weekly_prepare(workspace_id, token, tail[1], week_of=None, max_slots=min(12, int(payload.get("maxSlots") or 8))))
            if len(tail) == 2 and tail[0] == "weeks" and method == "GET":
                return json_(200, coworker.weekly_week(workspace_id, token, tail[1]))
            if len(tail) == 5 and tail[0] == "weeks" and tail[2] == "slots" and method == "POST":
                return json_(200, coworker.weekly_slot(workspace_id, token, tail[1], tail[3], tail[4], body()))
        if area == "research":
            if tail == ["search"] and method == "POST":
                return json_(200, coworker.research_search(workspace_id, token, body().get("query")))
            if tail == ["providers"] and method == "GET":
                return json_(200, coworker.research_diagnostics(workspace_id, token))
        if area == "source-campaigns" and not tail and method == "POST":
            return json_(201, coworker.source_campaign(workspace_id, token, body()))
        if area == "creative" and tail == ["plan"] and method == "POST":
            from . import creative, flags
            flags.require("RAFII_CREATIVE_AGENT_ENABLED")
            payload = body()
            state = service.repository.get(workspace_id, token)["state"]
            platforms = [p for p in (payload.get("platforms") or []) if isinstance(p, str)][:6]
            return json_(200, creative.plan_assets(state, payload.get("brief") or {}, platforms, payload.get("format") or "image"))
        if area == "overlays":
            if not tail and method == "GET":
                return json_(200, coworker.overlays_view(workspace_id, token))
            if tail == ["export"] and method == "GET":
                return json_(200, coworker.overlays_export(workspace_id, token))
            if tail == ["notes"] and method == "POST":
                return json_(201, coworker.overlay_note(workspace_id, token, body()))
            if len(tail) == 2 and tail[0] == "notes" and method == "PATCH":
                return json_(200, coworker.overlay_note(workspace_id, token, body(), tail[1]))
            if len(tail) == 2 and tail[1] == "status" and method == "POST":
                return json_(200, coworker.overlay_status(workspace_id, token, tail[0], body().get("status")))
            if tail == ["reset"] and method == "POST":
                payload = body()
                return json_(200, coworker.overlay_reset(workspace_id, token, payload.get("scope"), payload.get("confirmed")))
        if area == "performance":
            if not tail and method == "GET":
                return json_(200, coworker.performance_view(workspace_id, token))
            if len(tail) == 3 and tail[0] == "hypotheses" and tail[2] == "decide" and method == "POST":
                return json_(200, coworker.hypothesis_decide(workspace_id, token, tail[1], body().get("decision")))
        if area == "listening":
            if not tail and method == "GET":
                return json_(200, coworker.listening_view(workspace_id, token))
            if tail == ["watchlists"] and method == "POST":
                return json_(201, coworker.watchlist_save(workspace_id, token, body()))
            if len(tail) == 3 and tail[0] == "opportunities" and tail[2] == "decide" and method == "POST":
                return json_(200, coworker.opportunity_decide(workspace_id, token, tail[1], body().get("decision")))
        if area == "engagement":
            if not tail and method == "GET":
                return json_(200, coworker.engagement_triage(workspace_id, token))
            if len(tail) == 3 and tail[0] == "threads" and tail[2] == "draft" and method == "POST":
                body()
                return json_(201, coworker.engagement_draft(workspace_id, token, tail[1]))
        if area == "growth" and not tail and method == "GET":
            return json_(200, coworker.growth(workspace_id, token))
        if area == "experiments" and len(tail) == 1 and method == "GET":
            return json_(200, coworker.experiment(workspace_id, token, tail[0]))
    raise AlphaError("This hosted route is unavailable.", 404)
