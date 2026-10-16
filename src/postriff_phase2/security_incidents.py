"""Rafii Account Protection v2, P1 item 4: "This wasn't me".

POST /api/auth/security/incidents files a report from the person's own signed-in Security settings and, in one
transaction: records the incident, places an account hold (security_holds: workers, automations, Agent steps and API
tokens stop acting for the account), revokes the scoped sessions in pr_session_revocations and writes the ledger. After
the commit, when other sessions were in scope, it asks the identity provider to end their refresh tokens and reports
honestly whether that was confirmed. Connected third-party accounts are never disconnected automatically: the response
says what is held and what was not touched.

Abuse controls, because someone holding a stolen session could use this to lock the owner out:
- only an interactive session (never an API token), with the existing Origin/CSRF guard of every hosted mutation;
- an explicit confirmation in the body (`confirmed: true`, `type: "not_me"`, nothing else accepted);
- fresh proof: a sign-in method Supabase signed into this session's `amr` within the last 10 minutes (JWT `iat` never
  counts). Any signed method qualifies here, unlike step-up: this action can only restrict the account, never unlock it;
- at most 3 reports per person per hour (counted before any other check), plus an optional Idempotency-Key;
- an email link can only navigate here: GET never changes anything.

Off (404) unless RAFII_SECURITY_INCIDENT_HOLD is on, the same flag that makes holds enforceable.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re

from postriff_alpha.domain import AlphaError

from . import device_trust, security_holds, security_policy

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{16,120}$")
REPORTS_PER_HOUR = 3
FIELDS = {"sourceEventId", "type", "confirmed", "revokeOtherSessions"}


def unavailable_route():
    return AlphaError("This hosted route is unavailable.", 404)


def not_found():
    return AlphaError("That security event isn't available.", 404, code="security_resource_not_found")


def validate(body):
    if not isinstance(body, dict) or set(body) - FIELDS or not {"type", "confirmed", "revokeOtherSessions"} <= set(body):
        raise AlphaError("Send type, confirmed and revokeOtherSessions only.", 400)
    if body["type"] != "not_me" or body["confirmed"] is not True or type(body["revokeOtherSessions"]) is not bool:
        raise AlphaError("Confirm that this wasn't you before reporting it.", 400, code="confirmation_required")
    source = body.get("sourceEventId")
    if source is not None and (not isinstance(source, str) or not _UUID.match(source)):
        raise AlphaError("Invalid security event.", 400)
    return {"sourceEventId": source, "revokeOtherSessions": body["revokeOtherSessions"]}


def digest(principal, body):
    return hashlib.sha256(json.dumps({"principal": str(principal), **body}, sort_keys=True).encode()).hexdigest()


def _iso(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value is not None and hasattr(value, "strftime") else None


def view(row):
    incident_id, state, hold_epoch, created_at, resolved_at, hold_active = row
    return {"incidentId": str(incident_id), "state": state, "accountHold": bool(hold_active), "holdEpoch": int(hold_epoch or 0),
            "createdAt": _iso(created_at), "resolvedAt": _iso(resolved_at)}


class SecurityIncidents:
    def __init__(self, service):
        self.service = service

    def _principal(self, token):
        from .api_tokens import is_api_token
        if not security_holds.enabled():
            raise unavailable_route()
        if is_api_token(token):
            raise AlphaError("Use your signed-in Rafii session for account security.", 403, code="token_scope_denied")
        return self.service.verify_session(token)

    def list(self, token):
        """The person's own incidents, newest first. Never changes anything."""
        principal = self._principal(token)
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT i.id,i.state,i.hold_epoch,i.created_at,i.resolved_at,coalesce(c.hold_active,false) FROM public.pr_security_incidents i"
                        " LEFT JOIN public.pr_security_account_controls c ON c.user_id=i.user_id WHERE i.user_id=%s ORDER BY i.created_at DESC LIMIT 20", (principal,))
            return {"incidents": [view(row) for row in cur.fetchall()]}

    def report(self, token, body, idempotency_key=None):
        from .hosted import audit, throttle
        principal = self._principal(token)
        verify = self.service.verify_session
        with self.service.connection_factory() as db, db.cursor() as cur:
            # Counted first and in its own transaction, so refused attempts count too.
            throttle(cur, f"security-incident:{principal}", REPORTS_PER_HOUR, 3600)
        request = validate(body)
        if idempotency_key is not None and not _KEY.match(idempotency_key):
            raise AlphaError("Invalid Idempotency-Key.", 400)
        method_time = getattr(verify, "method_time", None)
        _, verified_at = method_time(token, principal) if callable(method_time) else (None, 0)
        if not 0 <= float(self.service.clock()) - float(verified_at or 0) <= security_policy.STEP_UP_SECONDS:
            # The existing "sign in again" code: the web app already offers sign-out-and-back for it.
            raise AlphaError("Sign in again to confirm it's you, then report this.", 403, code="step_up_required")
        current = verify.session_id(token, principal)
        print_ = digest(principal, request)
        with self.service.connection_factory() as db, db.cursor() as cur:
            if idempotency_key is not None:
                replay = self._replay(cur, principal, idempotency_key, print_)
                if replay is not None:
                    return replay
            target = None
            if request["sourceEventId"]:
                cur.execute("SELECT session_id FROM public.pr_security_login_events WHERE user_id=%s AND id=%s", (principal, request["sourceEventId"]))
                event = cur.fetchone()
                if not event:
                    raise not_found()  # Unknown or another person's: the same answer.
                target = event[0]
            if target is not None and target == current:
                raise AlphaError("That is this session. Sign out here instead, or choose another session.", 409, code="current_device_revocation_requires_logout")
            if idempotency_key is not None:
                cur.execute("SAVEPOINT rapv2_incident")
            try:
                cur.execute("INSERT INTO public.pr_security_incidents(user_id,source_event_id,state,summary_code,confirmed_at,idempotency_key,request_digest)"
                            " VALUES(%s,%s,'user_confirmed','not_me',now(),%s,%s) RETURNING id,created_at",
                            (principal, request["sourceEventId"], idempotency_key, print_ if idempotency_key else None))
            except Exception as error:
                # A concurrent request with the same key won the unique index after our lookup: answer with its result.
                if idempotency_key is None or type(error).__name__ != "UniqueViolation":
                    raise
                cur.execute("ROLLBACK TO SAVEPOINT rapv2_incident")
                replay = self._replay(cur, principal, idempotency_key, print_)
                if replay is None:
                    raise
                return replay
            incident_id, created_at = cur.fetchone()
            epoch = security_holds.place(cur, principal, "incident.not_me")
            # Scoped sessions: the reported one, and every other known session when asked. Never the current one.
            cur.execute("INSERT INTO public.pr_session_revocations(user_id,session_id) SELECT s.user_id,s.session_id FROM public.pr_sessions s"
                        " WHERE s.user_id=%s AND s.session_id<>%s AND (%s OR s.session_id=%s) ON CONFLICT DO NOTHING RETURNING session_id",
                        (principal, current or "", request["revokeOtherSessions"], target or ""))
            revoked = [row[0] for row in cur.fetchall()]
            if revoked:
                cur.execute("UPDATE public.pr_session_security SET enforcement='revoked',last_evaluated_at=now(),version=version+1 WHERE user_id=%s AND session_id = ANY(%s)", (principal, revoked))
            cur.execute("UPDATE public.pr_security_incidents SET hold_epoch=%s,sessions_revoked=%s WHERE user_id=%s AND id=%s", (epoch, len(revoked), principal, incident_id))
            device_trust.record(cur, principal, "incident.reported", f"incident.reported:{incident_id}", session_id=current,
                                details={"incidentId": str(incident_id), "sessionsRevoked": len(revoked), "holdEpoch": epoch})
            device_trust.record(cur, principal, "account.hold_placed", f"account.hold_placed:{epoch}", session_id=current,
                                details={"incidentId": str(incident_id), "holdEpoch": epoch, "reason": "incident.not_me"})
            audit(cur, None, principal, "security.incident_reported", str(incident_id), {"sessionsRevoked": len(revoked), "holdEpoch": epoch})
            if current:
                # Owner decision 5: the banner shows at the next sign-in, never on the session that filed the report.
                # Migration 128's column; before it is applied the report still files (and the banner shows everywhere).
                cur.execute("SAVEPOINT rapv2_reporter")
                try:
                    cur.execute("UPDATE public.pr_security_incidents SET reported_session_id=%s WHERE user_id=%s AND id=%s", (current, principal, incident_id))
                    cur.execute("RELEASE SAVEPOINT rapv2_reporter")
                except Exception:  # noqa: BLE001
                    cur.execute("ROLLBACK TO SAVEPOINT rapv2_reporter")
        provider = "unsupported"
        if request["revokeOtherSessions"]:
            logout_others = getattr(self.service.identity, "logout_others", None)
            try:
                provider = "confirmed" if logout_others and logout_others(token) else "unknown"
            except Exception as error:
                logging.getLogger("postriff.account_protection").warning(json.dumps({"event": "incident.provider_logout_failed", "error": type(error).__name__}))
                provider = "partial"
        return {**view((incident_id, "user_confirmed", epoch, created_at, None, True)), **self._outcome(len(revoked), provider)}

    def _replay(self, cur, principal, idempotency_key, print_):
        """The earlier incident filed with this key, or None; 409 when that key carried a different report."""
        cur.execute("SELECT i.id,i.state,i.hold_epoch,i.created_at,i.resolved_at,coalesce(c.hold_active,false),i.request_digest,i.sessions_revoked"
                    " FROM public.pr_security_incidents i LEFT JOIN public.pr_security_account_controls c ON c.user_id=i.user_id"
                    " WHERE i.user_id=%s AND i.idempotency_key=%s", (principal, idempotency_key))
        replay = cur.fetchone()
        if not replay:
            return None
        if replay[6] != print_:
            raise AlphaError("This Idempotency-Key was used for a different report.", 409, code="idempotency_key_conflict")
        return {**view(replay[:6]), **self._outcome(replay[7], None), "replayed": True}

    @staticmethod
    def _outcome(revoked, provider):
        """Exactly what was protected and what was not touched (04-API-CONTRACT §3)."""
        return {"sessions": {"rafiiApiRevoked": int(revoked), "providerRefreshState": provider or "unknown"},
                "agents": {"newSensitiveActions": "held", "alreadyExecutedActions": "not_reversible"},
                "connectedAccounts": "not_disconnected",
                "nextAction": "verify_recovery"}
