"""Rafii Account Protection v2, P1 item 2: the security gate in front of sensitive capabilities.

`require(service, token, capability)` runs only under RAFII_ACCOUNT_PROTECTION_V2_MODE=enforce (set nowhere); in any
other mode it returns at once and runs nothing. Under enforce it:

1. refuses an API token outright for a sensitive capability (it is not an interactive session and cannot step up); an
   API token reading private workspace data is governed by its scopes and the account hold instead;
2. re-verifies the bearer through the hosted verifier (revocation, deleted account, MFA enforcement, founder block);
3. reads the session's signals in one statement: revocation, the browser making *this* request (its cookie must hash to
   the device the session is linked to; a missing or different cookie is an unknown browser, so a copied bearer
   alone never reads as known), whether a second factor was added or removed or other sessions were signed out
   in the last 24 hours, and when a factor was last removed (a proof older than that is void);
4. asks security_policy.evaluate, persists the decision on pr_session_security, and records a
   `session.step_up_verified` ledger event once per proof;
5. raises 403 `security_step_up_required` (no protected effect) unless the policy allows. Its `nextAction` is
   `complete_mfa` when the person has a verified second factor and `enroll_mfa` when the identity service says they
   have none (an MFA prompt they could never complete is not a next step).

A sensitive capability is also refused (403 `security_account_hold`) while the account is on a security hold, however
fresh the proof, and with 503 when the session has no security record although the device registry is on (its
observation failed, so nothing about this session is known). Private workspace reads (`private_data`) are gated only at
high risk and fail open: an unreadable security state never takes a person's own drafts away.

Security notices for step-ups (owner decision 6, 2026-10-16): a successful, self-initiated step-up stays quiet (its
`session.step_up_verified` ledger row only). A notice is queued, through the transactional `security.account_change`
event, only when a step-up fails repeatedly (STEP_UP_FAILURES challenges of one session within STEP_UP_FAILURE_SECONDS
with no fresh proof since; at most one notice per session per hour) or a risky sign-in is blocked (a high or critical
risk session refused; once per session). Each challenge is recorded as `session.step_up_challenged` (at most one row per
session, capability and minute) so failures can be counted.

Sensitive capabilities fail closed: if the security state cannot be read (database error, migration 120 missing) the capability answers
503 `security_state_unavailable`; nothing else in the app is affected. `capability_for` maps the hosted routes onto
three of the sensitive capabilities; the fourth, widening Agent permissions, is checked by agent_permissions.apply_decision
only when the change actually widens authority. Protective actions (revoking a token, disconnecting an account,
narrowing Agent permissions, signing out sessions) are never gated, so a person under challenge can still lock things down.
"""
from __future__ import annotations

import json
import logging

from postriff_alpha.domain import AlphaError

from . import account_protection, device_trust, security_holds, security_policy

# Account events that make the next sensitive action riskier (pr_audit_events kinds, actor = the person).
RECENT_CHANGE_KINDS = ("mfa.enabled", "mfa.disabled", "session.revoked_others")
# Decision 6: how many challenges without a fresh proof count as a failed step-up, and within how long.
STEP_UP_FAILURES = 3
STEP_UP_FAILURE_SECONDS = 1800


def capability_for(method, parts):
    """The sensitive capability a hosted route exercises, or None. `parts` is the path split on '/', no empty ends."""
    if len(parts) < 3 or parts[:2] != ["api", "workspaces"]:
        return None
    if len(parts) == 3:
        return "private_data" if method == "GET" else None
    area = parts[3]
    if area == "tokens" and len(parts) == 4 and method == "POST":
        return "api_tokens"
    if area in ("channels", "connectors") and len(parts) == 7 and parts[5] == "oauth" and parts[6] in ("start", "complete") and method == "POST":
        return "connections"
    if area in ("export", "profile-export") and len(parts) == 4 and method == "GET":
        return "exports"
    if method == "GET":
        return "private_data"
    return None


class SecurityError(AlphaError):
    """An AlphaError whose `public_fields` (machine codes only, never a signal value) join the JSON error body."""

    def __init__(self, message, status, *, code, public_fields):
        super().__init__(message, status, code=code)
        self.public_fields = public_fields


def step_up_required(decision, has_factor=None):
    if has_factor is False:
        return SecurityError("Set up an authenticator app or security key, then confirm it's you to continue.", 403, code="security_step_up_required",
                             public_fields={"nextAction": "enroll_mfa", "security": decision.body()})
    return SecurityError("Confirm it's you with your authenticator or security key to continue.", 403, code="security_step_up_required",
                         public_fields={"nextAction": "complete_mfa", "security": decision.body()})


def has_second_factor(service, principal):
    """True/False from the identity service's verified factors; None when it cannot say (then the prompt stays
    complete_mfa, the answer that never claims the person has nothing to complete)."""
    factors = getattr(getattr(service, "identity", None), "verified_factors", None)
    if not callable(factors):
        return None
    try:
        listed = factors(principal)
    except Exception:  # noqa: BLE001 - an identity outage only changes the wording of the next step
        return None
    return bool(listed) if isinstance(listed, list) else None


def unavailable():
    return SecurityError("This action is unavailable while account security can't be checked. Try again shortly.", 503, code="security_state_unavailable",
                         public_fields={"nextAction": "retry"})


_SIGNALS = (
    "SELECT EXISTS(SELECT 1 FROM public.pr_session_revocations r WHERE r.user_id=%s AND r.session_id=%s),"
    " (SELECT CASE WHEN d.id IS NULL THEN NULL WHEN d.state='revoked' THEN 'revoked'"
    "   WHEN d.first_seen_at < ss.first_seen_at THEN 'known' ELSE 'new' END"
    "   FROM public.pr_session_security ss JOIN public.pr_security_devices d ON d.user_id=ss.user_id AND d.id=ss.device_id"
    "   WHERE ss.user_id=%s AND ss.session_id=%s AND d.token_hash = ANY(%s)),"
    " EXISTS(SELECT 1 FROM public.pr_audit_events a WHERE a.actor=%s AND a.kind = ANY(%s) AND a.at > now() - make_interval(secs => %s)),"
    " coalesce((SELECT extract(epoch from max(a.at)) FROM public.pr_audit_events a WHERE a.actor=%s AND a.kind='mfa.disabled'),0),"
    " EXISTS(SELECT 1 FROM public.pr_session_security ss WHERE ss.user_id=%s AND ss.session_id=%s)"
)


def require(service, token, capability):
    """Allow `capability` for this bearer or raise. A no-op outside enforce mode."""
    if not account_protection.enforcing():
        return None
    from .api_tokens import is_api_token
    sensitive = capability in security_policy.SENSITIVE
    if is_api_token(token):
        if not sensitive:
            return None
        raise SecurityError("An interactive sign-in is required for this action.", 403, code="security_step_up_required", public_fields={"nextAction": "sign_in"})
    verify = service.repository.verify_session
    principal = verify(token)
    session_id = verify.session_id(token, principal)
    method_time = getattr(verify, "method_time", None)
    aal = getattr(verify, "aal", None)
    method, at = method_time(token, principal) if callable(method_time) else (None, 0)
    proof = security_policy.Proof(method, float(at or 0), aal(token, principal) if callable(aal) else "aal1")
    now = float(service.clock())
    try:
        with service.connection_factory() as db:
            with db.cursor() as cur:
                if sensitive:
                    # Fail closed with the flag on; with it off only an existing hold is enforced (security_holds).
                    security_holds.assert_clear(cur, principal)
                cur.execute(_SIGNALS, (principal, session_id, principal, session_id, device_trust.presented_hashes(principal), principal, list(RECENT_CHANGE_KINDS),
                                       security_policy.RECENT_CHANGE_SECONDS, principal, principal, session_id))
                revoked, device, recent, factor_changed_at, recorded = cur.fetchone()
                if sensitive and not recorded and not revoked and device_trust.active():
                    # The registry is on but this session's observation never committed: nothing is known about it.
                    raise unavailable()
                signals = security_policy.Signals(bool(revoked), device, bool(recent), float(factor_changed_at or 0))
                decision = security_policy.evaluate(signals, proof, now, capability)
                if sensitive or decision.outcome != "allow":
                    _persist(cur, principal, session_id, decision, proof)
                if decision.outcome == "step_up" and session_id:
                    _challenged(cur, principal, session_id, decision, capability, now)
    except AlphaError:
        raise
    except Exception as error:
        logging.getLogger("postriff.account_protection").warning(json.dumps({"event": "security_gate.unavailable", "capability": capability, "error": type(error).__name__}))
        if not sensitive:
            return None
        raise unavailable() from error
    if decision.outcome == "revoked":
        raise AlphaError("This session expired or was revoked. Sign in again.", 401, code="session_revoked")
    if decision.outcome != "allow":
        raise step_up_required(decision, has_second_factor(service, principal))
    return decision


def _persist(cur, principal, session_id, decision, proof):
    """The latest decision on the session's row (a no-op when the session has none yet) and, for a step-up, one ledger
    event per proof. Same transaction as the read, so a decision is never acted on without being recorded."""
    cur.execute(
        "UPDATE public.pr_session_security SET risk_level=%s,enforcement=%s,risk_reasons=%s::jsonb,policy_version=%s,last_evaluated_at=now(),"
        " step_up_at=CASE WHEN %s::text IS NULL THEN step_up_at ELSE to_timestamp(%s) END,"
        " step_up_method=coalesce(%s,step_up_method),version=version+1 WHERE user_id=%s AND session_id=%s",
        (decision.risk_level, decision.enforcement, json.dumps(list(decision.reasons)), decision.policy_version,
         decision.step_up_method, proof.at, decision.step_up_method, principal, session_id))
    if decision.step_up_method is not None:
        device_trust.record(cur, principal, "session.step_up_verified", f"session.step_up_verified:{session_id}:{int(proof.at)}",
                            session_id=session_id, details={"method": decision.step_up_method, "policyVersion": decision.policy_version},
                            risk_level=decision.risk_level)


def _record_once(cur, principal, session_id, event_type, event_key, details, risk_level):
    """One ledger row; True only when this call wrote it (a repeat of the key is a no-op)."""
    cur.execute("INSERT INTO public.pr_security_login_events(user_id,session_id,event_type,event_key,details,risk_level) VALUES(%s,%s,%s,%s,%s::jsonb,%s)"
                " ON CONFLICT DO NOTHING RETURNING id", (principal, session_id, event_type, event_key[:180], json.dumps(details), risk_level))
    return cur.fetchone() is not None


def _challenged(cur, principal, session_id, decision, capability, now):
    """Decision 6: record the challenge, then queue a security notice only for a blocked risky sign-in or a repeatedly
    failed step-up. Same transaction as the decision; a successful step-up never reaches here."""
    cur.execute("SAVEPOINT rapv2_step_up_notice")
    try:
        _notice_if_due(cur, principal, session_id, decision, capability, now)
        cur.execute("RELEASE SAVEPOINT rapv2_step_up_notice")
    except Exception as error:  # noqa: BLE001 - a notice never changes the decision (e.g. migration 129 not applied yet)
        cur.execute("ROLLBACK TO SAVEPOINT rapv2_step_up_notice")
        logging.getLogger("postriff.account_protection").warning(json.dumps({"event": "security_gate.notice_unavailable", "error": type(error).__name__}))


def _notice_if_due(cur, principal, session_id, decision, capability, now):
    from .hosted import audit
    details = {"capability": capability, "riskLevel": decision.risk_level, "reasonCodes": list(decision.reasons), "policyVersion": decision.policy_version}
    _record_once(cur, principal, session_id, "session.step_up_challenged", f"session.step_up_challenged:{session_id}:{capability}:{int(now // 60)}",
                 details, decision.risk_level)
    if decision.risk_level in ("high", "critical"):
        if _record_once(cur, principal, session_id, "session.sign_in_blocked", f"session.sign_in_blocked:{session_id}", details, decision.risk_level):
            audit(cur, None, principal, "security.sign_in_blocked", session_id, {"riskLevel": decision.risk_level, "reasonCodes": list(decision.reasons)})
        return
    # Challenges of this session in the window that no fresh proof has answered since.
    cur.execute("SELECT count(*) FROM public.pr_security_login_events c WHERE c.user_id=%s AND c.session_id=%s AND c.event_type='session.step_up_challenged'"
                " AND c.occurred_at > now() - make_interval(secs => %s)"
                " AND c.occurred_at > coalesce((SELECT max(v.occurred_at) FROM public.pr_security_login_events v WHERE v.user_id=%s AND v.session_id=%s"
                "   AND v.event_type='session.step_up_verified'), '-infinity'::timestamptz)",
                (principal, session_id, STEP_UP_FAILURE_SECONDS, principal, session_id))
    if int(cur.fetchone()[0]) < STEP_UP_FAILURES:
        return
    if _record_once(cur, principal, session_id, "session.step_up_failed", f"session.step_up_failed:{session_id}:{int(now // 3600)}", details, decision.risk_level):
        audit(cur, None, principal, "security.step_up_failed", session_id, {"riskLevel": decision.risk_level, "reasonCodes": list(decision.reasons)})
