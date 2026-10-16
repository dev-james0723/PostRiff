"""Rafii Account Protection v2, P1 item 2: the deterministic risk policy. Pure functions, no I/O, no model.

Given the server-derived signals for one session and the proof its signed token carries, `evaluate` returns the same
decision every time for the same inputs, stamped with POLICY_VERSION so a stored decision can be reproduced. An LLM
never takes part in an authorization decision (02-ARCHITECTURE §E).

Signals (all read by the server, never accepted from a request):
  revoked            the session id is in pr_session_revocations
  device             "known" (a browser this person used before this session), "new" (first seen with this session),
                     "revoked", or None (no browser cookie / registry off)
  recent_change      a second factor was added or removed, or other sessions were signed out, within RECENT_CHANGE_SECONDS
  factor_changed_at  when a second factor was last removed (epoch seconds, 0 for never): a proof made before it is void
Proof: the newest sign-in method Supabase signed into the token's `amr` claim, its time, and the token's AAL.

Step-up counts only a fresh, independent second factor on an AAL2 session: TOTP or a WebAuthn MFA ceremony within
STEP_UP_SECONDS. A refreshed token's `iat` never counts (it is not read at all), and neither does any email-delivered
proof (a one-time code or magic link to the same inbox an attacker may hold), a password, OAuth, or a passkey sign-in.

A known browser is never sufficient on its own (the device cookie is a copyable hint): a sensitive capability without
fresh proof needs a low-risk session that is already AAL2. A proof made before the factor was removed proves nothing.
Private workspace data (`private_data`) is gated only at high risk, so an unknown browser can still read its work while
one right after a factor or sign-out change cannot.
"""
from __future__ import annotations

from dataclasses import dataclass, field

POLICY_VERSION = 2
STEP_UP_SECONDS = 600
RECENT_CHANGE_SECONDS = 24 * 3600
# Capabilities whose misuse outlives the session: a persistent credential, a connected account, wider Agent authority
# or a copy of the data. Everything else is gated by the existing workspace, membership and MFA rules only.
SENSITIVE = frozenset({"api_tokens", "connections", "agent_grants", "exports"})
# Reading private workspace state (drafts, library, settings): step-up only when the risk is high.
PRIVATE = frozenset({"private_data"})
# Supabase `amr` methods that are an independent second factor, and how pr_session_security names them.
INDEPENDENT_FACTORS = {"totp": "totp", "mfa/webauthn": "webauthn_mfa"}
LEVELS = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class Signals:
    revoked: bool = False
    device: str | None = None
    recent_change: bool = False
    factor_changed_at: float = 0.0


@dataclass(frozen=True)
class Proof:
    method: str | None = None
    at: float = 0.0
    aal: str = "aal1"


@dataclass(frozen=True)
class Decision:
    outcome: str                 # allow | step_up | revoked
    risk_level: str              # low | medium | high | critical
    enforcement: str             # allow | challenge | revoked (pr_session_security.enforcement)
    reasons: tuple = field(default_factory=tuple)
    step_up_method: str | None = None   # set when a fresh independent proof satisfied the step-up
    policy_version: int = POLICY_VERSION

    def body(self):
        """What a client may see: the outcome, level and reason codes. Never a signal value or a device id."""
        return {"outcome": self.outcome, "riskLevel": self.risk_level, "reasonCodes": list(self.reasons), "policyVersion": self.policy_version}


def fresh_factor(proof, now, factor_changed_at=0.0):
    """The pr_session_security step_up_method name when `proof` is a fresh independent second factor made after the
    last factor removal, else None."""
    if not isinstance(proof, Proof) or proof.aal != "aal2":
        return None
    method = INDEPENDENT_FACTORS.get(proof.method or "")
    if method is None or type(proof.at) not in (int, float) or proof.at <= 0:
        return None
    if factor_changed_at and float(proof.at) <= float(factor_changed_at):
        return None
    age = float(now) - float(proof.at)
    # A timestamp from the future is not fresher proof; allow only small clock skew.
    return method if -60 <= age <= STEP_UP_SECONDS else None


def assess(signals):
    """(risk level, reason codes) from the signals alone."""
    reasons = []
    if signals.device != "known":
        reasons.append("unknown_device" if signals.device in (None, "new") else "revoked_device")
    if signals.recent_change:
        reasons.append("recent_account_change")
    if signals.device == "revoked" or len(reasons) == 2:
        level = "high"
    elif reasons:
        level = "medium"
    else:
        level = "low"
    return level, tuple(reasons)


def evaluate(signals, proof, now, capability):
    """The decision for using `capability` from this session now."""
    if signals.revoked:
        return Decision("revoked", "critical", "revoked", ("session_revoked",))
    level, reasons = assess(signals)
    if capability in PRIVATE:
        gated = level in ("high", "critical")
    else:
        gated = capability in SENSITIVE
    if not gated:
        return Decision("allow", level, "allow", reasons)
    method = fresh_factor(proof, now, signals.factor_changed_at)
    if method is not None:
        return Decision("allow", level, "allow", reasons, step_up_method=method)
    aal2 = isinstance(proof, Proof) and proof.aal == "aal2"
    if level == "low" and capability in SENSITIVE:
        if aal2:
            return Decision("allow", level, "allow", reasons)
        # A known browser alone (a copied cookie with an AAL1 bearer reads the same) is not proof.
        reasons = reasons + ("aal1_session",)
    return Decision("step_up", level, "challenge", reasons)
