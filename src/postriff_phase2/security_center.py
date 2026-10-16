"""Rafii Account Protection v2: the Security Center routes that were missing after P1.

Devices (RAP-084, RAP-121), behind RAFII_DEVICE_TRUST_V2 (404 while off, as nothing is registered then):
  GET  /api/auth/devices                 the caller's own browsers from pr_security_devices, each with how many
                                         sessions it carries. The only principal is the verified bearer: any user
                                         parameter is ignored.
  POST /api/auth/devices/{id}/revoke     revoke one browser: its record is revoked (that cookie is never known again)
                                         and every Rafii session linked to it is denied in pr_session_revocations.
                                         Not the browser making the request (sign out instead). Same freshness rule as
                                         revoking a session. Idempotent.

Recovery and resolution (RAP-111, RAP-112, RAP-113), behind RAFII_SECURITY_INCIDENT_HOLD (404 while off):
  GET  /api/auth/security/recovery       the recovery path. With a second factor enrolled before the open incident:
                                         confirm with it. Without one: the support path. An email code or link to the
                                         account's own inbox is never a recovery proof (whoever took over the session
                                         may hold that inbox too).
  POST /api/auth/security/recovery       ask support to recover the account: records the request and moves open
                                         incidents to `recovering`. It never lifts the hold.
  POST /api/auth/security/incidents/{id}/resolve
                                         the person ends the incident; when no other incident is open the hold is
                                         released once (hold_epoch moves forward exactly once; a repeat changes
                                         nothing). Needs a fresh independent second factor (security_policy.fresh_factor:
                                         TOTP or WebAuthn MFA within 10 minutes on an AAL2 session) made after the
                                         report, with a factor that existed before the report. A factor enrolled after
                                         the report, possibly from the stolen session, never lifts the hold. Anything
                                         less answers 403 and the hold stays.
  While a hold is active, POST /api/auth/mfa (recording that the account now requires a factor) is refused too.

Releasing a hold for someone else (support, the founder) is not built: it is an open product decision.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from postriff_alpha.domain import AlphaError

from . import device_trust, security_holds, security_policy

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
RESOLVES_PER_HOUR = 5
RECOVERY_REQUESTS_PER_HOUR = 3


class SecurityRefusal(AlphaError):
    """An AlphaError whose `public_fields` (machine codes only) join the JSON error body, like security_gate's."""

    def __init__(self, message, status, *, code, public_fields):
        super().__init__(message, status, code=code)
        self.public_fields = public_fields


def unavailable_route():
    return AlphaError("This hosted route is unavailable.", 404)


def not_found(what="That security event"):
    return AlphaError(f"{what} isn't available.", 404, code="security_resource_not_found")


def step_up_required():
    return SecurityRefusal("Confirm it's you with your authenticator or security key, then end the hold.", 403, code="security_step_up_required",
                           public_fields={"nextAction": "complete_mfa", "accountHold": "retained"})


def support_required():
    return SecurityRefusal("This account has no second factor from before the report, so support has to recover it. The hold stays on until then.",
                           403, code="security_recovery_support_required", public_fields={"nextAction": "contact_support", "accountHold": "retained"})


def _iso(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value is not None and hasattr(value, "strftime") else None


def _epoch(value):
    if type(value) in (int, float):
        return float(value)
    if isinstance(value, str) and value:
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()
    return None


def _confirmed(body, message):
    if not isinstance(body, dict) or body.get("confirmed") is not True or set(body) - {"confirmed"}:
        raise AlphaError(message, 400, code="confirmation_required")


class SecurityCenter:
    def __init__(self, service):
        self.service = service

    def _interactive(self, token):
        from .api_tokens import is_api_token
        if is_api_token(token):
            raise AlphaError("Use your signed-in Rafii session for account security.", 403, code="token_scope_denied")
        return self.service.verify_session(token)

    # --- devices (RAP-084, RAP-121) -----------------------------------------------------------------------------------
    def devices(self, token):
        if not device_trust.enabled():
            raise unavailable_route()
        principal = self._interactive(token)
        current = device_trust.presented_hashes(principal)
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute(
                "SELECT d.id,d.display_label,d.state,d.surface,d.first_seen_at,d.last_seen_at,d.revoked_at,d.revoke_reason,d.token_hash = ANY(%s),"
                " count(ss.session_id),count(ss.session_id) FILTER (WHERE r.session_id IS NULL AND ss.enforcement <> 'revoked')"
                " FROM public.pr_security_devices d"
                " LEFT JOIN public.pr_session_security ss ON ss.user_id=d.user_id AND ss.device_id=d.id"
                " LEFT JOIN public.pr_session_revocations r ON r.user_id=ss.user_id AND r.session_id=ss.session_id"
                " WHERE d.user_id=%s GROUP BY d.id ORDER BY d.last_seen_at DESC LIMIT 50", (current, principal))
            rows = cur.fetchall()
        devices = [{"deviceId": str(row[0]), "label": row[1], "state": row[2], "surface": row[3], "firstSeen": _iso(row[4]), "lastSeen": _iso(row[5]),
                    "revokedAt": _iso(row[6]), "revokeReason": row[7], "current": bool(row[8]), "sessions": int(row[9]), "activeSessions": int(row[10])}
                   for row in rows]
        known = [device for device in devices if device["state"] != "revoked"]
        # "1 recognized browser, 2 sessions" (RAP-121): browsers and sessions are counted apart, never conflated.
        return {"devices": devices, "summary": {"recognizedBrowsers": len(known), "activeSessions": sum(device["activeSessions"] for device in known)}}

    def revoke_device(self, token, device_id):
        if not device_trust.enabled():
            raise unavailable_route()
        principal = self._interactive(token)
        self.service.repository.assert_fresh(token, principal)
        if not isinstance(device_id, str) or not _UUID.match(device_id):
            raise not_found("That browser")
        current = set(device_trust.presented_hashes(principal))
        from .hosted import audit
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT token_hash,state FROM public.pr_security_devices WHERE user_id=%s AND id=%s FOR UPDATE", (principal, device_id))
            row = cur.fetchone()
            if not row:
                raise not_found("That browser")  # Unknown or another person's: the same answer.
            if row[0] in current:
                raise AlphaError("That is this browser. Sign out here instead.", 409, code="current_device_revocation_requires_logout")
            if row[1] == "revoked":
                return {"deviceId": device_id, "revoked": True, "sessionsRevoked": 0, "replayed": True}
            cur.execute("UPDATE public.pr_security_devices SET state='revoked',revoked_at=now(),revoke_reason='user_revoked',updated_at=now() WHERE user_id=%s AND id=%s", (principal, device_id))
            cur.execute("INSERT INTO public.pr_session_revocations(user_id,session_id) SELECT ss.user_id,ss.session_id FROM public.pr_session_security ss"
                        " WHERE ss.user_id=%s AND ss.device_id=%s ON CONFLICT DO NOTHING RETURNING session_id", (principal, device_id))
            revoked = [item[0] for item in cur.fetchall()]
            if revoked:
                cur.execute("UPDATE public.pr_session_security SET enforcement='revoked',last_evaluated_at=now(),version=version+1 WHERE user_id=%s AND session_id = ANY(%s)", (principal, revoked))
            device_trust.record(cur, principal, "device.revoked", f"device.revoked:{device_id}:user", device_id=device_id,
                                details={"reason": "user_revoked", "sessionsRevoked": len(revoked)})
            audit(cur, None, principal, "device.revoked", device_id, {"sessionsRevoked": len(revoked)})
        return {"deviceId": device_id, "revoked": True, "sessionsRevoked": len(revoked)}

    # --- recovery (RAP-111) -------------------------------------------------------------------------------------------
    def _factors(self, principal):
        """[(type, created epoch or None)] of the verified factors; None when the identity service cannot say."""
        listed = getattr(getattr(self.service, "identity", None), "verified_factors", None)
        if not callable(listed):
            return None
        try:
            factors = listed(principal)
        except Exception:  # noqa: BLE001 - an identity outage means "cannot say", never "has none"
            return None
        if not isinstance(factors, list):
            return None
        return [(str(item.get("type", "")), _epoch(item.get("createdAt"))) for item in factors if isinstance(item, dict)]

    @staticmethod
    def _before(factors, moment):
        """Factors enrolled before `moment` (all of them when there is no incident)."""
        return [kind for kind, created in (factors or []) if moment is None or (created is not None and created < moment)]

    def recovery(self, token):
        if not security_holds.enabled():
            raise unavailable_route()
        principal = self._interactive(token)
        with self.service.connection_factory() as db, db.cursor() as cur:
            held, _, _ = security_holds.read(cur, principal)
            cur.execute("SELECT id,extract(epoch from created_at) FROM public.pr_security_incidents WHERE user_id=%s AND state<>'resolved' ORDER BY created_at LIMIT 1", (principal,))
            incident = cur.fetchone()
        factors = self._factors(principal)
        prior = self._before(factors, float(incident[1]) if incident else None)
        return {"accountHold": held, "openIncident": str(incident[0]) if incident else None,
                "path": "verify_factor" if prior else "support",
                "factorsBeforeIncident": len(prior), "identityAvailable": factors is not None,
                # Never an email code or link to the account's own inbox (RAP-111).
                "emailCodeAccepted": False,
                "steps": ["confirm_with_existing_factor", "resolve_incident"] if prior else ["request_support_recovery", "support_verifies_identity_out_of_band"]}

    def request_recovery(self, token, body):
        if not security_holds.enabled():
            raise unavailable_route()
        principal = self._interactive(token)
        from .hosted import audit, throttle
        with self.service.connection_factory() as db, db.cursor() as cur:
            # Counted first and in its own transaction, so refused attempts count too.
            throttle(cur, f"security-recovery:{principal}", RECOVERY_REQUESTS_PER_HOUR, 3600)
        _confirmed(body, "Confirm that you want support to recover this account.")
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("UPDATE public.pr_security_incidents SET state='recovering' WHERE user_id=%s AND state IN ('open','user_confirmed') RETURNING id", (principal,))
            moved = [str(row[0]) for row in cur.fetchall()]
            audit(cur, None, principal, "security.recovery_requested", moved[0] if moved else "", {"incidents": len(moved), "path": "support"})
            cur.execute("SELECT id::text FROM public.pr_audit_events WHERE actor=%s AND kind='security.recovery_requested' ORDER BY at DESC LIMIT 1", (principal,))
            reference = cur.fetchone()
        return {"path": "support", "reference": reference[0] if reference else None, "incidentsRecovering": len(moved),
                "accountHold": "unchanged", "emailCodeAccepted": False}

    # --- resolution (RAP-112, RAP-113) --------------------------------------------------------------------------------
    def resolve(self, token, incident_id, body):
        if not security_holds.enabled():
            raise unavailable_route()
        principal = self._interactive(token)
        from .hosted import audit, throttle
        with self.service.connection_factory() as db, db.cursor() as cur:
            throttle(cur, f"security-resolve:{principal}", RESOLVES_PER_HOUR, 3600)
        _confirmed(body, "Confirm that the account is yours again before ending the hold.")
        if not isinstance(incident_id, str) or not _UUID.match(incident_id):
            raise not_found()
        verify = self.service.verify_session
        method_time, aal = getattr(verify, "method_time", None), getattr(verify, "aal", None)
        method, at = method_time(token, principal) if callable(method_time) else (None, 0)
        proof = security_policy.Proof(method, float(at or 0), aal(token, principal) if callable(aal) else "aal1")
        now = float(self.service.clock())
        session_id = verify.session_id(token, principal)
        factors = self._factors(principal)
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT state,extract(epoch from created_at),resolved_at FROM public.pr_security_incidents WHERE user_id=%s AND id=%s FOR UPDATE", (principal, incident_id))
            incident = cur.fetchone()
            if not incident:
                raise not_found()  # Unknown or another person's: the same answer.
            if incident[0] == "resolved":
                # Released once (RAP-113): a repeat changes nothing and reports the state as it is.
                active, epoch, _ = security_holds.read(cur, principal)
                return {"incidentId": incident_id, "state": "resolved", "resolvedAt": _iso(incident[2]), "accountHold": active, "holdEpoch": epoch,
                        "holdReleased": False, "replayed": True}
            reported = float(incident[1])
            cur.execute("SELECT coalesce(extract(epoch from max(at)),0) FROM public.pr_audit_events WHERE actor=%s AND kind='mfa.disabled'", (principal,))
            factor_removed = float(cur.fetchone()[0] or 0)
            fresh = security_policy.fresh_factor(proof, now, factor_removed)
            if factors is not None and not self._before(factors, reported):
                raise support_required()
            if fresh is None or proof.at <= reported or factors is None:
                # RAP-112: stale or weak proof (an email code, OAuth, a refreshed token, a proof older than the report)
                # or an identity service that cannot confirm the factor: nothing changes and the hold stays.
                raise step_up_required()
            cur.execute("UPDATE public.pr_security_incidents SET state='resolved',resolution_code='owner_verified_factor',resolved_at=now() WHERE user_id=%s AND id=%s RETURNING resolved_at", (principal, incident_id))
            resolved_at = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM public.pr_security_incidents WHERE user_id=%s AND state<>'resolved'", (principal,))
            others = int(cur.fetchone()[0])
            active, epoch, _ = security_holds.read(cur, principal)
            released = active and others == 0
            if released:
                epoch = security_holds.release(cur, principal, "incident.resolved")
                active = False
                device_trust.record(cur, principal, "account.hold_released", f"account.hold_released:{epoch}", session_id=session_id,
                                    details={"incidentId": incident_id, "holdEpoch": epoch, "reason": "incident.resolved"})
            device_trust.record(cur, principal, "incident.resolved", f"incident.resolved:{incident_id}", session_id=session_id,
                                details={"incidentId": incident_id, "method": fresh, "holdReleased": released, "holdEpoch": epoch})
            audit(cur, None, principal, "security.incident_resolved", incident_id, {"holdReleased": released, "holdEpoch": epoch, "method": fresh})
        return {"incidentId": incident_id, "state": "resolved", "resolvedAt": _iso(resolved_at), "accountHold": active, "holdEpoch": epoch,
                "holdReleased": released, "otherOpenIncidents": others}


def assert_enrolment_allowed(service, principal):
    """POST /api/auth/mfa during an active hold: a factor recorded during an incident must not become the account's proof."""
    if not security_holds.enabled():
        return
    with service.connection_factory() as db, db.cursor() as cur:
        held, _, _ = security_holds.read(cur, principal)
    if held:
        raise AlphaError("Two-factor changes are paused while the account is on a security hold. End the hold with a factor you already had, or contact support.",
                         409, code="security_account_hold")
