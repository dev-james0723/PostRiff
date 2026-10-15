"""Rafii Account Protection v2, P1 item 2: the deterministic risk policy. Pure functions, no I/O, no model.

Given the server-derived signals for one session and the proof its signed token carries, `evaluate` returns the same
decision every time for the same inputs, stamped with POLICY_VERSION so a stored decision can be reproduced. An LLM
never takes part in an authorization decision (02-ARCHITECTURE §E).

Signals (all read by the server, never accepted from a request):
  revoked            the session id is in pr_session_revocations
  device             "known" (a browser this person used before this session), "new" (first seen with this session),
                     "revoked", or None (no browser cookie / registry off)
  recent_change      a second factor was added or removed, or other sessions were signed out, within RECENT_CHANGE_SECONDS
Proof: the newest sign-in method Supabase signed into the token's `amr` claim, its time, and the token's AAL.

Step-up counts only a fresh, independent second factor on an AAL2 session: TOTP or a WebAuthn MFA ceremony within
STEP_UP_SECONDS. A refreshed token's `iat` never counts (it is not read at all), and neither does any email-delivered
proof (a one-time code or magic link to the same inbox an attacker may hold), a password, OAuth, or a passkey sign-in.
"""
from __future__ import annotations

from dataclasses import dataclass, field

POLICY_VERSION = 1
STEP_UP_SECONDS = 600
RECENT_CHANGE_SECONDS = 24 * 3600
# Capabilities whose misuse outlives the session: a persistent credential, a connected account, wider Agent authority
# or a copy of the data. Everything else is gated by the existing workspace, membership and MFA rules only.
SENSITIVE = frozenset({"api_tokens", "connections", "agent_grants", "exports"})
# Supabase `amr` methods that are an independent second factor, and how pr_session_security names them.
INDEPENDENT_FACTORS = {"totp": "totp", "mfa/webauthn": "webauthn_mfa"}
LEVELS = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class Signals:
    revoked: bool = False
    device: str | None = None
    recent_change: bool = False


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


def fresh_factor(proof, now):
    """The pr_session_security step_up_method name when `proof` is a fresh independent second factor, else None."""
    if not isinstance(proof, Proof) or proof.aal != "aal2":
        return None
    method = INDEPENDENT_FACTORS.get(proof.method or "")
    if method is None or type(proof.at) not in (int, float) or proof.at <= 0:
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
    if capability not in SENSITIVE or level == "low":
        return Decision("allow", level, "allow", reasons)
    method = fresh_factor(proof, now)
    if method is not None:
        return Decision("allow", level, "allow", reasons, step_up_method=method)
    return Decision("step_up", level, "challenge", reasons)
