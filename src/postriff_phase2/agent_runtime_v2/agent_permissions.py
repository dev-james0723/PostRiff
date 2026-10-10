"""Rafii agent permissions: presets, the consent store, receipts and revocation (rafii-agent-authz/1, CF-2 §2–§7, §16).

Migration 109 holds the rows; this module is the only writer, and only session-authenticated HTTP handlers call its
write functions (PI-3: never from a tool context, never with an API token).

- A person with no row, or whose row is marked `ended_at` (membership ended), resolves to the legacy baseline:
  `LEGACY_BASELINE_V1` with each surface's legacy confirmation, which is exactly what Rafii does today. No backfill,
  ever (INV-3). "Not now" writes only a reminder row (`pr_agent_permission_reminders`), never a grant.
- Every change is one transaction under the workspace lock (`repository.transaction`): the state row's epoch rises,
  one append-only receipt explains it (with the person's idempotency key and a fingerprint of the request), replaced
  grants are revoked (never deleted) and new ones inserted. Revocation handlers run in the same transaction.
- Widening needs `confirmed: true`; Full and Assist on a sensitive category need a sign-in verified within 300 s.
- `Grants.token()` is a digest of what the decision depends on. It is compared for equality only, never ordered.
- Ending a membership (leave, removal) keeps every row and marks it ended; only account deletion erases, through
  `postriff_private.agent_permissions_erase`, in the deletion transaction, before the membership rows go.

Before migration 109 is applied anywhere, `load()` resolves everyone to the legacy baseline and every write answers
404 `agent_permissions_unavailable`, so this code can ship ahead of the migration (DP-9) without changing anything.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from postriff_alpha.domain import AlphaError

from . import authz

CONSENT_VERSION = "agent-permissions/1"
PRESET_VERSION = 1
ALL_DOMAINS = authz.ALL_DOMAINS
CATEGORIES = authz.CATEGORIES
SENSITIVE_ASSIST = ("manage_settings", "manage_connected_services", "execute_automations")   # Assist here needs a fresh sign-in
PRESETS = {
    "recommended": {"categories": {"read_analyze": "assist", "navigate_interact": "assist", "create_edit": "assist",
                                   "manage_settings": "ask", "manage_connected_services": "ask", "execute_automations": "ask"},
                    "domains": ALL_DOMAINS,
                    "spend_confirmation": "all", "step_up": False},       # SD-1 OPEN: 'all' matches today's credit quotes
    "full": {"categories": {c: "assist" for c in CATEGORIES}, "domains": ALL_DOMAINS, "spend_confirmation": "none", "step_up": True},
    "none": {"categories": {}, "domains": (), "spend_confirmation": "all", "step_up": False},
}
LEGACY_EQUIVALENT = {"categories": {"read_analyze": "assist", "navigate_interact": "assist", "create_edit": "assist",
                                    "manage_settings": "assist", "execute_automations": "assist"},
                     "domains": ALL_DOMAINS, "spend_confirmation": "none", "baseline": "legacy_v1"}
SPEND = authz.SPEND
SOURCES = ("onboarding", "settings", "reminder", "chat_link")       # never 'genui' (PI-7): no generated control can widen
REMINDER_ACTIONS = ("shown", "not_now", "dismissed")
REMINDER_SECONDS = 7 * 86400
HISTORY_LIMIT = 50
COPY_FILE = Path(__file__).with_name("permission_copy.json")
COPY = json.loads(COPY_FILE.read_text())
COPY_DIGEST = hashlib.sha256(COPY_FILE.read_bytes()).hexdigest()
_KEY = re.compile(r"^[A-Za-z0-9._:-]{16,120}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PUT_KEYS = {"preset", "scopes", "spendConfirmation", "expectedEpoch", "consentVersion", "copyDigest", "confirmed", "stepUp", "source", "idempotencyKey"}


# --- the resolved grants -----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class AutopilotPolicy:
    id: str
    capability_ids: frozenset
    constraints: dict
    limits: dict
    usage: dict
    expires_at: float


@dataclass(frozen=True)
class Grants:
    workspace_id: str
    user_id: str
    source: str                         # 'legacy' | 'explicit'
    preset: str                         # 'legacy' | 'none' | 'recommended' | 'full' | 'custom'
    baseline: str | None                # 'legacy_v1' | None
    user_epoch: int
    workspace_epoch: int
    ended: bool = False                 # membership ended and not re-decided: resolves as legacy + needsChoice
    categories: Mapping = field(default_factory=dict)
    capabilities: Mapping = field(default_factory=dict)
    domains: frozenset = frozenset()
    spend_confirmation: str = "none"
    catalogue_generation: int = authz.CATALOGUE_GENERATION
    autopilot: tuple = ()
    ceiling: Mapping | None = None
    decided_at: float | None = None
    consent_version: str | None = None

    def token(self) -> str:
        """sha256 of what a decision depends on (CF-2 §1). Equality only: never ordered, never used to skip a check."""
        basis = {"u": self.user_epoch, "w": self.workspace_epoch, "s": self.source, "b": self.baseline, "p": self.preset, "e": self.ended,
                 "g": authz.CATALOGUE_GENERATION}
        return hashlib.sha256(authz.canonical(basis).encode()).hexdigest()

    def scopes(self) -> dict:
        """The explicit scope map ({} for legacy): category:x → mode, domain:x → True, capability:x → mode."""
        if self.source != "explicit":
            return {}
        out = {f"category:{c}": m for c, m in self.categories.items()}
        out.update({f"domain:{d}": True for d in sorted(self.domains)})
        out.update({f"capability:{c}": m for c, m in self.capabilities.items()})
        return out


def legacy(workspace_id, user_id, *, user_epoch=0, workspace_epoch=0, ended=False, ceiling=None) -> Grants:
    return Grants(workspace_id, user_id, "legacy", "legacy", None, user_epoch, workspace_epoch, ended=ended, ceiling=ceiling)


def from_scopes(workspace_id, user_id, scopes: Mapping, *, preset, baseline=None, spend="all", user_epoch=1, workspace_epoch=0, autopilot=(),
                ceiling=None, generation=authz.CATALOGUE_GENERATION, decided_at=None, consent_version=CONSENT_VERSION) -> Grants:
    categories = {k.split(":", 1)[1]: v for k, v in scopes.items() if k.startswith("category:") and v in authz.AUTONOMY}
    capabilities = {k.split(":", 1)[1]: v for k, v in scopes.items() if k.startswith("capability:") and v in ("off", "ask", "assist")}
    domains = frozenset(k.split(":", 1)[1] for k, v in scopes.items() if k.startswith("domain:") and v)
    return Grants(workspace_id, user_id, "explicit", preset, baseline, user_epoch, workspace_epoch, categories=categories, capabilities=capabilities,
                  domains=domains, spend_confirmation=spend, catalogue_generation=generation, autopilot=tuple(autopilot), ceiling=ceiling,
                  decided_at=decided_at, consent_version=consent_version)


def preset_scopes(name: str) -> dict:
    preset = LEGACY_EQUIVALENT if name == "legacy_equivalent" else PRESETS[name]
    scopes = {f"category:{c}": m for c, m in preset["categories"].items()}
    scopes.update({f"domain:{d}": True for d in preset["domains"]})
    return scopes


# --- reading -----------------------------------------------------------------------------------------------------------
def ready(cur) -> bool:
    """Whether migration 109 is applied on this database."""
    cur.execute("SELECT to_regclass('public.pr_agent_permission_state') IS NOT NULL")
    row = cur.fetchone()
    return bool(row and row[0])


def _table(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{name}",))
    row = cur.fetchone()
    return bool(row and row[0])


def epochs(cur, workspace_id, user_id) -> tuple[int, int]:
    """(person epoch, workspace epoch); a missing row is 0. For cache revalidation only."""
    if not ready(cur):
        return 0, 0
    cur.execute("SELECT epoch FROM public.pr_agent_permission_state WHERE workspace_id=%s AND user_id=%s", (workspace_id, user_id))
    row = cur.fetchone()
    cur.execute("SELECT epoch FROM public.pr_agent_workspace_policy WHERE workspace_id=%s", (workspace_id,))
    policy = cur.fetchone()
    return int(row[0]) if row else 0, int(policy[0]) if policy else 0


def load(cur, workspace_id, user_id, *, now: float | None = None) -> Grants:
    """The person's grants now: legacy when there is no row or the row is ended (CF-2 §5)."""
    now = time.time() if now is None else now
    if not ready(cur):
        return legacy(workspace_id, user_id)
    cur.execute("SELECT epoch,ceiling FROM public.pr_agent_workspace_policy WHERE workspace_id=%s", (workspace_id,))
    policy = cur.fetchone()
    workspace_epoch, ceiling = (int(policy[0]), _json(policy[1]) or None) if policy else (0, None)
    cur.execute("SELECT epoch,preset,baseline,spend_confirmation,catalogue_generation,ended_at IS NOT NULL,extract(epoch from decided_at),consent_version "
                "FROM public.pr_agent_permission_state WHERE workspace_id=%s AND user_id=%s", (workspace_id, user_id))
    row = cur.fetchone()
    if row is None or row[5]:
        return legacy(workspace_id, user_id, user_epoch=int(row[0]) if row else 0, workspace_epoch=workspace_epoch, ended=bool(row), ceiling=ceiling)
    cur.execute("SELECT scope,mode FROM public.pr_agent_grants WHERE workspace_id=%s AND user_id=%s AND revoked_at IS NULL", (workspace_id, user_id))
    scopes = {scope: (mode if mode is not None else True) for scope, mode in cur.fetchall()}
    cur.execute("SELECT id::text,capability_ids,constraints,limits,usage,extract(epoch from expires_at) FROM public.pr_agent_autopilot_policies "
                "WHERE workspace_id=%s AND user_id=%s AND revoked_at IS NULL AND starts_at<=to_timestamp(%s::double precision) "
                "AND expires_at>to_timestamp(%s::double precision)", (workspace_id, user_id, now, now))
    autopilot = tuple(AutopilotPolicy(pid, frozenset(ids or ()), _json(c) or {}, _json(l) or {}, _json(u) or {}, float(exp))
                      for pid, ids, c, l, u, exp in cur.fetchall())
    return from_scopes(workspace_id, user_id, scopes, preset=row[1], baseline=row[2], spend=row[3], user_epoch=int(row[0]), workspace_epoch=workspace_epoch,
                       autopilot=autopilot, ceiling=ceiling, generation=int(row[4]), decided_at=float(row[6]) if row[6] is not None else None,
                       consent_version=row[7])


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


# --- the catalogue diff (correction 5: one function computes widened and denied_now) ------------------------------------------
@dataclass(frozen=True)
class CatalogueDiff:
    widened: frozenset                   # capability ids newly reachable, or reachable with a lower confirmation
    denied_now: frozenset                # capability ids allowed before and denied after
    spend_looser: bool


def _surface(cap) -> authz.Surface:
    surfaces = authz.capability_surfaces(cap)
    # The settings summary uses the strictest reachable surface; the widening diff
    # below evaluates every binding so a restrictive surface cannot hide a widening.
    return max(surfaces, key=lambda x: authz.CONFIRMATIONS.index(x.legacy_confirmation)) if surfaces else authz.Surface("native", cap.name, cap.confirmation)


def catalogue_diff(before: Grants, after: Grants, *, member, state, now: float | None = None) -> CatalogueDiff:
    now = time.time() if now is None else now
    actor = authz.Actor("agent", before.user_id)
    widened, denied = set(), set()
    rank = authz.CONFIRMATIONS.index
    for cap in authz.catalogue():
        for surface in authz.capability_surfaces(cap):
            b = authz.decide(cap, surface=surface, member=member, grants=before, state=state, actor=actor, now=now)
            a = authz.decide(cap, surface=surface, member=member, grants=after, state=state, actor=actor, now=now)
            if b.outcome == "deny" and a.outcome != "deny":
                widened.add(cap.capability_id)
            elif b.outcome != "deny" and a.outcome == "deny":
                denied.add(cap.capability_id)
            elif b.outcome != "deny" and rank(a.required) < rank(b.required):
                widened.add(cap.capability_id)
    # A preset can add a tool to the Manager even when a specialist could already
    # reach it. That is still a widening and must require the person's confirmation.
    from . import capability_registry
    newly_reachable = capability_registry.reach("manager", after) - capability_registry.reach("manager", before)
    for capability_id in newly_reachable:
        cap = authz.capability_by_id(capability_id)
        if cap and any(authz.decide(cap, surface=surface, member=member, grants=after, state=state, actor=actor, now=now).outcome != "deny"
                       for surface in authz.capability_surfaces(cap)):
            widened.add(capability_id)
    looser = set(SPEND.get(after.spend_confirmation, ())) < set(SPEND.get(before.spend_confirmation if before.source == "explicit" else "none", ()))
    return CatalogueDiff(frozenset(widened), frozenset(denied), looser)


# --- revocation handlers (CF-2 §7.3) ------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RevocationEvent:
    workspace_id: str
    user_id: str | None                  # None = a workspace-wide consent narrowing
    denied_now: frozenset
    token_after: str
    receipt_id: str | None
    reason: str
    epoch_after: int = 0


REVOCATION_HANDLERS: list[tuple[str, Callable[[Any, RevocationEvent], int]]] = []


def register_revocation_handler(name: str, fn: Callable[[Any, RevocationEvent], int]) -> None:
    """Other lanes add theirs here (CF-3's approvals and tasks, proposals, suggestions, memory proposals)."""
    REVOCATION_HANDLERS[:] = [(n, f) for n, f in REVOCATION_HANDLERS if n != name] + [(name, fn)]


def _ui_activations(cur, event: RevocationEvent) -> int:
    """H4: unused GenUI activations of this person can no longer be executed."""
    if not event.denied_now or not _table(cur, "pr_ui_activations"):
        return 0
    cur.execute("UPDATE public.pr_ui_activations SET used_at=now() WHERE workspace_id=%s AND (principal=%s::uuid OR %s::uuid IS NULL) AND used_at IS NULL AND expires_at>now()",
                (event.workspace_id, event.user_id, event.user_id))
    return cur.rowcount or 0


def _autopilot(cur, event: RevocationEvent) -> int:
    """H5: a bounded autopilot policy that covers a capability denied now stops."""
    if not event.denied_now:
        return 0
    cur.execute("UPDATE public.pr_agent_autopilot_policies SET revoked_at=now(),revoked_epoch=%s,revoke_reason=%s WHERE workspace_id=%s AND (user_id=%s::uuid OR %s::uuid IS NULL) "
                "AND revoked_at IS NULL AND capability_ids && %s::text[]",
                (event.epoch_after, "membership_ended" if event.reason == "membership_ended" else "permission_changed", event.workspace_id, event.user_id, event.user_id,
                 sorted(event.denied_now)))
    return cur.rowcount or 0


register_revocation_handler("ui_activations", _ui_activations)
register_revocation_handler("autopilot", _autopilot)


def _run_handlers(cur, event: RevocationEvent, *, mode="shadow") -> dict:
    # Shadow stores choices only: no legacy activations, proposals or task rows may change.
    if mode != "enforce":
        authz.log.info(json.dumps({"event": "agent.permission.shadow_revocation", "capabilities": len(event.denied_now)}))
        return {}
    # Handlers share the caller's transaction. A failure rolls back the whole change;
    # reporting success after partial invalidation would violate the receipt contract.
    return {name: int(fn(cur, event) or 0) for name, fn in REVOCATION_HANDLERS}


def _not_recallable(denied: frozenset) -> list[str]:
    if not denied:
        return []
    risks = {cap.capability_id: cap.risk for cap in authz.catalogue()}
    out = []
    if any(risks.get(c) == "R0" for c in denied):
        out.append("sent_to_model_provider")
    out.append("visible_in_past_answers")
    if any(risks.get(c) in ("R1", "R2", "R3") for c in denied):
        out.append("already_applied_changes")
    return out


# --- validation and idempotency -------------------------------------------------------------------------------------------
def _invalid(message: str) -> authz.AuthzError:
    return authz.AuthzError(message, "scope_invalid")


def unavailable() -> authz.AuthzError:
    return authz.AuthzError("Rafii's permission settings aren't available in this workspace yet.", "agent_permissions_unavailable")


def _key(value) -> str:
    if not isinstance(value, str) or not _KEY.match(value):
        raise AlphaError("Send an idempotency key of 16 to 120 letters, digits or . _ : -.", 400)
    return value


def fingerprint(principal: str, body: Mapping) -> str:
    """sha256(principal, canonical body without the key); keys are scoped to workspace and actor."""
    rest = {k: v for k, v in body.items() if k != "idempotencyKey"}
    return hashlib.sha256(authz.canonical({"principal": str(principal), "body": rest}).encode()).hexdigest()


def _replayed(cur, workspace_id, principal, key, print_) -> dict | None:
    cur.execute("SELECT id::text,actor::text,request_fingerprint FROM public.pr_agent_consent_receipts WHERE workspace_id=%s AND actor=%s AND idempotency_key=%s "
                "ORDER BY created_at LIMIT 2", (workspace_id, principal, key))
    rows = cur.fetchall()
    if not rows:
        return None
    if any(actor != str(principal) or stored != print_ for _id, actor, stored in rows):
        # Nothing about the other use is revealed (correction 11).
        raise authz.AuthzError("This request id was already used for a different change.", "idempotency_conflict")
    return receipt_view(cur, workspace_id, rows[0][0])


def _scope_value(key: str, value, catalogue_ids: frozenset):
    kind, _, name = key.partition(":")
    if kind == "category" and name in CATEGORIES and value in ("ask", "assist", "off", None):
        return value
    if kind == "domain" and name in ALL_DOMAINS and isinstance(value, bool):
        return value
    if kind == "capability" and name in catalogue_ids and value in ("off", "ask", "assist", None):
        return value
    raise _invalid("One of these permissions isn't one Rafii offers.")


def validate_put(payload) -> dict:
    if not isinstance(payload, dict) or set(payload) - PUT_KEYS:
        raise AlphaError("Send only the documented permission fields.", 400)
    preset = payload.get("preset")
    if preset not in ("recommended", "full", "custom", "none"):
        raise _invalid("Choose Recommended, Full, Custom or Off.")
    scopes = payload.get("scopes") or {}
    if not isinstance(scopes, dict) or len(scopes) > 200:
        raise _invalid("Send permissions as a list of choices.")
    if scopes and preset != "custom":
        raise _invalid("Individual choices go with Custom.")
    ids = frozenset(c.capability_id for c in authz.catalogue() if c.kind != "native_only" and c.tenant != "founder")
    clean_scopes = {key: _scope_value(key, value, ids) for key, value in scopes.items() if isinstance(key, str)} if scopes else {}
    if len(clean_scopes) != len(scopes):
        raise _invalid("One of these permissions isn't one Rafii offers.")
    spend = payload.get("spendConfirmation")
    if spend is not None and spend not in SPEND:
        raise _invalid("Choose when Rafii asks before spending credits.")
    if spend is not None and preset in PRESETS and spend != PRESETS[preset]["spend_confirmation"]:
        raise _invalid("This preset sets its own spending rule. Choose Custom to change it.")
    epoch = payload.get("expectedEpoch")
    if type(epoch) is not int or epoch < 0:
        raise AlphaError("Send the permissions version you are changing (expectedEpoch).", 400)
    source = payload.get("source", "settings")
    if source not in SOURCES:
        raise _invalid("These permissions can only be changed from Rafii's own settings.")
    for flag in ("confirmed", "stepUp"):
        if payload.get(flag) is not None and not isinstance(payload.get(flag), bool):
            raise AlphaError(f"{flag} must be true or false.", 400)
    return {"preset": preset, "scopes": clean_scopes, "spend": spend, "expectedEpoch": epoch, "consentVersion": payload.get("consentVersion"),
            "copyDigest": payload.get("copyDigest"), "confirmed": payload.get("confirmed") is True, "stepUp": payload.get("stepUp") is True,
            "source": source, "idempotencyKey": _key(payload.get("idempotencyKey"))}


def target_of(before: Grants, body: Mapping) -> tuple[str, dict, str]:
    """(preset, scopes, spend) a PUT asks for. Custom changes start from the person's explicit choice, or Recommended."""
    preset = body["preset"]
    if preset != "custom":
        return preset, preset_scopes(preset), PRESETS[preset]["spend_confirmation"]
    base = before.scopes() if before.source == "explicit" else preset_scopes("recommended")
    scopes = dict(base)
    for key, value in body["scopes"].items():
        if key.startswith("domain:"):
            if value:
                scopes[key] = True
            else:
                scopes.pop(key, None)
        elif value is None or (value == "off" and key.startswith("category:")):
            scopes.pop(key, None)
        else:
            scopes[key] = value
    spend = body.get("spend") or (before.spend_confirmation if before.source == "explicit" else PRESETS["recommended"]["spend_confirmation"])
    return preset, scopes, spend


def needs_step_up(before: Grants, preset: str, scopes: Mapping) -> bool:
    """Full, or Assist newly set on a sensitive category (or on a capability inside one) — correction 21, DP-4."""
    if preset == "full":
        return True
    prior = before.scopes()
    for category in SENSITIVE_ASSIST:
        key = f"category:{category}"
        if scopes.get(key) == "assist" and prior.get(key) != "assist":
            return True
    sensitive = {c.capability_id for c in authz.catalogue() if c.category in SENSITIVE_ASSIST}
    return any(k.startswith("capability:") and v == "assist" and prior.get(k) != "assist" and k.split(":", 1)[1] in sensitive for k, v in scopes.items())


# --- writing ----------------------------------------------------------------------------------------------------------------
def _audit(cur, workspace_id, actor, kind, subject, meta) -> None:
    from ..hosted import audit
    audit(cur, workspace_id, actor, kind, str(subject or ""), meta)


def _write(cur, *, workspace_id, user_id, actor, kind, source, before: Grants, preset, scopes, spend, baseline, widened, step_up, key, print_,
           now, revoke_reason, denied, ended=False, mode="shadow") -> str:
    """One change: handlers, the state row, the receipt, then the grant rows (CF-2 §7.1–§7.3)."""
    cur.execute("SELECT epoch FROM public.pr_agent_permission_state WHERE workspace_id=%s AND user_id=%s FOR UPDATE", (workspace_id, user_id))
    locked = cur.fetchone()
    current = int(locked[0]) if locked else 0
    if current != before.user_epoch:
        raise authz.AuthzError("Your Rafii permissions changed in another window. Reload and try again.", "agent_permissions_changed",
                               extra={"current": {"epoch": current}})
    epoch = current + 1
    after_token = replace(before, user_epoch=epoch, source="legacy" if ended else "explicit", preset="legacy" if ended else preset,
                          baseline=None if ended else baseline, ended=ended).token()
    invalidated = _run_handlers(cur, RevocationEvent(workspace_id, user_id, frozenset(denied), after_token, None, revoke_reason, epoch), mode=mode) if denied else {}
    step_up_at = step_up.get("at") if step_up else None
    cur.execute("INSERT INTO public.pr_agent_permission_state(workspace_id,user_id,epoch,preset,preset_version,baseline,spend_confirmation,consent_version,"
                "copy_digest,catalogue_generation,catalogue_digest,decided_by,decided_at,step_up_at,ended_at,updated_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s::double precision),to_timestamp(%s::double precision),"
                "to_timestamp(%s::double precision),to_timestamp(%s::double precision)) "
                "ON CONFLICT (workspace_id,user_id) DO UPDATE SET epoch=EXCLUDED.epoch,preset=EXCLUDED.preset,preset_version=EXCLUDED.preset_version,"
                "baseline=EXCLUDED.baseline,spend_confirmation=EXCLUDED.spend_confirmation,consent_version=EXCLUDED.consent_version,"
                "copy_digest=EXCLUDED.copy_digest,catalogue_generation=EXCLUDED.catalogue_generation,catalogue_digest=EXCLUDED.catalogue_digest,"
                "decided_by=EXCLUDED.decided_by,decided_at=EXCLUDED.decided_at,"
                "step_up_at=coalesce(EXCLUDED.step_up_at,public.pr_agent_permission_state.step_up_at),ended_at=EXCLUDED.ended_at,updated_at=EXCLUDED.updated_at",
                (workspace_id, user_id, epoch, "none" if ended else preset, PRESET_VERSION, None if ended else baseline, spend, CONSENT_VERSION, COPY_DIGEST,
                 authz.CATALOGUE_GENERATION, authz.catalogue_digest(), actor, now, step_up_at, now if ended else None, now))
    scopes_before = {**before.scopes(), "spend": before.spend_confirmation if before.source == "explicit" else None}
    scopes_after = {} if ended else {**scopes, "spend": spend}
    cur.execute("INSERT INTO public.pr_agent_consent_receipts(workspace_id,user_id,actor,kind,source,epoch_before,epoch_after,preset_before,preset_after,"
                "scopes_before,scopes_after,widened,consent_version,copy_digest,catalogue_digest,step_up,invalidated,not_recallable,idempotency_key,"
                "request_fingerprint,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,"
                "to_timestamp(%s::double precision)) RETURNING id::text",
                (workspace_id, user_id, actor, kind, source, current, epoch, before.preset, "none" if ended else preset, json.dumps(scopes_before),
                 json.dumps(scopes_after), bool(widened), CONSENT_VERSION, COPY_DIGEST if source != "system" else None, authz.catalogue_digest(),
                 json.dumps(step_up or {}), json.dumps(invalidated), json.dumps(_not_recallable(frozenset(denied))), key, print_, now))
    receipt_id = cur.fetchone()[0]
    active = before.scopes() if before.source == "explicit" else {}
    keep = {} if ended else scopes
    for scope, mode in active.items():
        if keep.get(scope) != mode:
            cur.execute("UPDATE public.pr_agent_grants SET revoked_epoch=%s,revoked_by=%s,revoked_at=to_timestamp(%s::double precision),revoke_reason=%s "
                        "WHERE workspace_id=%s AND user_id=%s AND scope=%s AND revoked_at IS NULL", (epoch, actor, now, revoke_reason, workspace_id, user_id, scope))
    for scope, mode in keep.items():
        if active.get(scope) != mode:
            cur.execute("INSERT INTO public.pr_agent_grants(workspace_id,user_id,scope,mode,granted_epoch,granted_by,granted_at,receipt_id) "
                        "VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s::double precision),%s)",
                        (workspace_id, user_id, scope, None if mode is True else mode, epoch, actor, now, receipt_id))
    return receipt_id


def apply_decision(cur, *, workspace_id, principal, member, state, token, payload, now, step_up: Callable[[], dict] | None = None, mode="shadow") -> dict:
    """PUT …/agent/permissions (CF-2 §16). Returns the stored receipt; the HTTP layer adds the fresh GET body."""
    authz.human_only(token)
    if not ready(cur):
        raise unavailable()
    body = validate_put(payload)
    print_ = fingerprint(principal, payload)
    replay = _replayed(cur, workspace_id, principal, body["idempotencyKey"], print_)
    if replay is not None:
        return replay
    before = load(cur, workspace_id, principal, now=now)
    if body["expectedEpoch"] != before.user_epoch:
        raise authz.AuthzError("Your Rafii permissions changed in another window. Reload and try again.", "agent_permissions_changed",
                               extra={"current": {"epoch": before.user_epoch, "preset": before.preset}})
    if body["consentVersion"] != CONSENT_VERSION or body["copyDigest"] != COPY_DIGEST:
        raise authz.AuthzError("These permission choices were updated. Reload to see the current wording.", "agent_permissions_copy_stale")
    preset, scopes, spend = target_of(before, body)
    after = from_scopes(workspace_id, principal, scopes, preset=preset, spend=spend, user_epoch=before.user_epoch + 1,
                        workspace_epoch=before.workspace_epoch, ceiling=before.ceiling)
    diff = catalogue_diff(before, after, member=member, state=state, now=now)
    widened = bool(diff.widened) or diff.spend_looser
    if widened and not body["confirmed"]:
        raise authz.AuthzError("Confirm that Rafii may do more before saving.", "confirmation_required")
    proof = None
    if needs_step_up(before, preset, scopes):
        if not body["stepUp"] or step_up is None:
            raise authz.step_up_required("full" if preset == "full" else "sensitive_assist")
        proof = step_up()
    kind = "custom_changed" if preset == "custom" else "preset_applied"
    receipt_id = _write(cur, workspace_id=workspace_id, user_id=principal, actor=principal, kind=kind, source=body["source"], before=before, preset=preset,
                        scopes=scopes, spend=spend, baseline=None, widened=widened, step_up=proof, key=body["idempotencyKey"], print_=print_, now=now,
                        revoke_reason="changed", denied=diff.denied_now, mode=mode)
    _audit(cur, workspace_id, principal, "agent.permission.preset_applied" if kind == "preset_applied" else "agent.permission.changed", principal,
           {"receiptId": receipt_id, "preset": preset, "widened": widened, "source": body["source"], "epoch": before.user_epoch + 1})
    return receipt_view(cur, workspace_id, receipt_id)


def revoke(cur, *, workspace_id, principal, member, state, token, payload, now, mode="shadow") -> dict:
    """POST …/agent/permissions/revoke: narrowing only. A legacy person's first revoke materializes LEGACY_EQUIVALENT minus
    what they turned off (preset custom, baseline legacy_v1), so nothing Rafii could reach before becomes reachable."""
    authz.human_only(token)
    if not ready(cur):
        raise unavailable()
    if not isinstance(payload, dict) or set(payload) - {"scopes", "all", "idempotencyKey", "source"}:
        raise AlphaError("Send the permissions to turn off, or all: true.", 400)
    all_ = payload.get("all") is True
    scopes_in = payload.get("scopes") or []
    if all_ == bool(scopes_in) or not isinstance(scopes_in, list) or len(scopes_in) > 100:
        raise AlphaError("Send the permissions to turn off, or all: true.", 400)
    ids = frozenset(c.capability_id for c in authz.catalogue())
    for scope in scopes_in:
        if not isinstance(scope, str):
            raise _invalid("One of these permissions isn't one Rafii offers.")
        _scope_value(scope, "off" if not scope.startswith("domain:") else False, ids)
    source = payload.get("source", "settings")
    if source not in SOURCES:
        raise _invalid("These permissions can only be changed from Rafii's own settings.")
    key = _key(payload.get("idempotencyKey"))
    print_ = fingerprint(principal, payload)
    replay = _replayed(cur, workspace_id, principal, key, print_)
    if replay is not None:
        return replay
    before = load(cur, workspace_id, principal, now=now)
    if all_:
        preset, scopes, spend, baseline = "none", {}, "all", None
    else:
        explicit = before.source == "explicit"
        scopes = before.scopes() if explicit else preset_scopes("legacy_equivalent")
        spend = before.spend_confirmation if explicit else LEGACY_EQUIVALENT["spend_confirmation"]
        baseline = before.baseline if explicit else LEGACY_EQUIVALENT["baseline"]
        preset = "custom"
        for scope in scopes_in:
            if scope.startswith("capability:"):
                scopes[scope] = "off"
            else:
                scopes.pop(scope, None)
    after = from_scopes(workspace_id, principal, scopes, preset=preset, baseline=baseline, spend=spend, user_epoch=before.user_epoch + 1,
                        workspace_epoch=before.workspace_epoch, ceiling=before.ceiling)
    diff = catalogue_diff(before, after, member=member, state=state, now=now)
    if diff.widened or diff.spend_looser:
        # By construction a revoke only narrows; refuse rather than store a widening as a "revoke".
        raise _invalid("That change would let Rafii do more. Use the permission choices instead.")
    receipt_id = _write(cur, workspace_id=workspace_id, user_id=principal, actor=principal, kind="revoked_all" if all_ else "revoked", source=source,
                        before=before, preset=preset, scopes=scopes, spend=spend, baseline=baseline, widened=False, step_up=None, key=key, print_=print_,
                        now=now, revoke_reason="revoked_all" if all_ else "revoked", denied=diff.denied_now, mode=mode)
    if all_:
        cur.execute("UPDATE public.pr_agent_autopilot_policies SET revoked_at=now(),revoked_epoch=%s,revoke_reason='revoked' WHERE workspace_id=%s AND user_id=%s "
                    "AND revoked_at IS NULL", (before.user_epoch + 1, workspace_id, principal))
    _audit(cur, workspace_id, principal, "agent.permission.revoked_all" if all_ else "agent.permission.revoked", principal,
           {"receiptId": receipt_id, "scopes": len(scopes_in), "epoch": before.user_epoch + 1})
    return receipt_view(cur, workspace_id, receipt_id)


def on_membership_ended(cur, workspace_id, user_id, *, actor, now: float | None = None, mode="off") -> str | None:
    """Every path that sets pr_memberships.status='revoked' calls this in the same transaction (CF-2 §6). Rows stay;
    the state is marked ended, every grant and autopilot policy is revoked, the epoch rises and handlers run. A person
    who never chose anything has no row and nothing to end. Re-invited later, they start from the legacy baseline."""
    now = time.time() if now is None else now
    if not ready(cur):
        return None
    cur.execute("SELECT ended_at IS NOT NULL FROM public.pr_agent_permission_state WHERE workspace_id=%s AND user_id=%s FOR UPDATE", (workspace_id, user_id))
    row = cur.fetchone()
    if row is None or row[0]:
        return None
    before = load(cur, workspace_id, user_id, now=now)
    denied = frozenset(c.capability_id for c in authz.catalogue())
    receipt_id = _write(cur, workspace_id=workspace_id, user_id=user_id, actor=actor, kind="membership_ended", source="system", before=before, preset="none",
                        scopes={}, spend="all", baseline=None, widened=False, step_up=None, key=f"membership-ended:{uuid.uuid4().hex}",
                        print_=hashlib.sha256(f"membership-ended:{workspace_id}:{user_id}:{now}".encode()).hexdigest(), now=now,
                        revoke_reason="membership_ended", denied=denied, ended=True, mode=mode)
    cur.execute("UPDATE public.pr_agent_autopilot_policies SET revoked_at=now(),revoked_epoch=%s,revoke_reason='membership_ended' WHERE workspace_id=%s "
                "AND user_id=%s AND revoked_at IS NULL", (before.user_epoch + 1, workspace_id, user_id))
    _audit(cur, workspace_id, actor, "agent.permission.membership_ended", user_id, {"receiptId": receipt_id, "epoch": before.user_epoch + 1})
    return receipt_id


def erase_workspace(cur, workspace_id) -> int:
    """Account deletion only, before its membership delete (the RESTRICT foreign keys refuse otherwise)."""
    if not ready(cur):
        return 0
    cur.execute("SELECT postriff_private.agent_permissions_erase(%s)", (workspace_id,))
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


# --- reminder (DP-3/DP-4: non-blocking, at most every 7 days) ---------------------------------------------------------------
def reminder(cur, workspace_id, user_id, grants: Grants, *, now) -> dict:
    if grants.source == "explicit":
        return {"due": False, "nextAt": None}
    cur.execute("SELECT extract(epoch from last_prompted_at) FROM public.pr_agent_permission_reminders WHERE workspace_id=%s AND user_id=%s",
                (workspace_id, user_id))
    row = cur.fetchone()
    if not row:
        return {"due": True, "nextAt": None}
    next_at = float(row[0]) + REMINDER_SECONDS
    return {"due": now >= next_at, "nextAt": next_at}


def remind(cur, *, workspace_id, principal, token, payload, now) -> dict:
    """POST …/agent/permissions/reminder. Stores only when the reminder was shown or set aside; never a grant."""
    authz.human_only(token)
    if not ready(cur):
        raise unavailable()
    if not isinstance(payload, dict) or set(payload) - {"action"} or payload.get("action") not in REMINDER_ACTIONS:
        raise AlphaError("Send shown, not_now or dismissed.", 400)
    action = payload["action"]
    response = None if action == "shown" else action
    # The membership/workspace transaction serializes devices; duplicate calls in the
    # same cadence preserve the original prompt timestamp and never increment twice.
    cur.execute("INSERT INTO public.pr_agent_permission_reminders(workspace_id,user_id,last_prompted_at,last_response,prompts,updated_at) "
                "VALUES(%s,%s,to_timestamp(%s::double precision),%s,1,now()) ON CONFLICT (workspace_id,user_id) DO UPDATE SET "
                "last_prompted_at=EXCLUDED.last_prompted_at,last_response=EXCLUDED.last_response,"
                "prompts=public.pr_agent_permission_reminders.prompts+1,updated_at=now() "
                "WHERE public.pr_agent_permission_reminders.last_prompted_at <= EXCLUDED.last_prompted_at-interval '7 days'",
                (workspace_id, principal, now, response))
    if response:
        cur.execute("UPDATE public.pr_agent_permission_reminders SET last_response=%s,updated_at=now() WHERE workspace_id=%s AND user_id=%s",
                    (response, workspace_id, principal))
    cur.execute("SELECT extract(epoch from last_prompted_at) FROM public.pr_agent_permission_reminders WHERE workspace_id=%s AND user_id=%s",
                (workspace_id, principal))
    next_at = float(cur.fetchone()[0]) + REMINDER_SECONDS
    return {"reminder": {"due": now >= next_at, "nextAt": next_at}}



# --- views ------------------------------------------------------------------------------------------------------------------
def _changes(before: Mapping, after: Mapping) -> list[dict]:
    keys = sorted(set(before) | set(after))
    return [{"scope": k, "from": before.get(k), "to": after.get(k)} for k in keys if before.get(k) != after.get(k)]


def _receipt(row, principal=None) -> dict:
    rid, at, kind, source, actor, epoch_before, epoch_after, preset_before, preset_after, before, after, widened, invalidated, not_recallable, step_up = row
    before, after = _json(before) or {}, _json(after) or {}
    out = {"id": rid, "at": float(at), "kind": kind, "source": source, "epochBefore": int(epoch_before), "epochAfter": int(epoch_after),
           "presetBefore": preset_before, "presetAfter": preset_after, "changes": _changes(before, after), "widened": bool(widened),
           "invalidated": _json(invalidated) or {}, "notRecallable": _json(not_recallable) or [], "stepUp": bool(_json(step_up) or {})}
    if principal is not None:
        out["actorIsYou"] = actor == str(principal)
    return out


RECEIPT_COLUMNS = ("id::text,extract(epoch from created_at),kind,source,actor::text,epoch_before,epoch_after,preset_before,preset_after,scopes_before,"
                   "scopes_after,widened,invalidated,not_recallable,step_up")


def receipt_view(cur, workspace_id, receipt_id) -> dict:
    cur.execute(f"SELECT {RECEIPT_COLUMNS} FROM public.pr_agent_consent_receipts WHERE workspace_id=%s AND id=%s", (workspace_id, receipt_id))
    row = cur.fetchone()
    if not row:
        raise AlphaError("That change isn't available.", 404)
    return _receipt(row)


def history(cur, workspace_id, user_id, *, viewer, cursor=None, limit=HISTORY_LIMIT) -> dict:
    """Receipts about one person, newest first. People read their own; owners and admins may read a member's."""
    if not ready(cur):
        raise unavailable()
    if cursor is not None and (not isinstance(cursor, str) or not _UUID.match(cursor)):
        raise AlphaError("Invalid cursor.", 400)
    limit = max(1, min(int(limit or HISTORY_LIMIT), HISTORY_LIMIT))
    where, params = "workspace_id=%s AND user_id=%s", [workspace_id, user_id]
    if cursor:
        where += (" AND (created_at,id) < (SELECT created_at,id FROM public.pr_agent_consent_receipts WHERE workspace_id=%s AND user_id=%s AND id=%s)")
        params += [workspace_id, user_id, cursor]
    cur.execute(f"SELECT {RECEIPT_COLUMNS} FROM public.pr_agent_consent_receipts WHERE {where} ORDER BY created_at DESC, id DESC LIMIT %s", (*params, limit + 1))
    rows = cur.fetchall()
    items = [_receipt(row, viewer) for row in rows[:limit]]
    return {"items": items, "next": items[-1]["id"] if len(rows) > limit else None}


def _category_view(cat: str, grants: Grants, decisions: list) -> dict:
    mine = [d for d in decisions if d.category == cat]
    mode = grants.categories.get(cat) if grants.source == "explicit" else LEGACY_EQUIVALENT["categories"].get(cat)
    if grants.ceiling and grants.ceiling.get(cat) == "off":
        effective = {"state": "clipped", "reasons": [{"code": "workspace_ceiling"}]}
    elif not mine:
        effective = {"state": "unavailable", "reasons": []}
    elif all(d.reason == "role" for d in mine):
        effective = {"state": "clipped", "reasons": [{"code": "role"}]}
    elif all(d.outcome == "deny" for d in mine):
        effective = {"state": "off", "reasons": [{"code": mine[0].reason}]}
    elif mode == "ask" or all(d.outcome != "allow" for d in mine if d.outcome != "deny"):
        effective = {"state": "asks", "reasons": []}
    else:
        effective = {"state": "on", "reasons": []}
    return {"id": cat, "mode": mode, "effective": effective, "capabilityCount": len(mine)}


def presets_view() -> list[dict]:
    out = []
    for pid in ("recommended", "full", "none"):
        preset = PRESETS[pid]
        out.append({"id": pid, "version": PRESET_VERSION, "scopes": preset_scopes(pid), "spendConfirmation": preset["spend_confirmation"],
                    "stepUp": bool(preset["step_up"])})
    return out


def view(cur, workspace_id, user_id, member, state, *, mode, now) -> dict:
    """GET …/agent/permissions (CF-2 §16) for the signed-in person."""
    if not ready(cur):
        raise unavailable()
    grants = load(cur, workspace_id, user_id, now=now)
    actor = authz.Actor("agent", user_id)
    caps = authz.catalogue()
    decisions = [authz.decide(cap, surface=_surface(cap), member=member, grants=grants, state=state, actor=actor, now=now) for cap in caps]
    entries = authz.public_catalogue()
    by_id = {d.capability_id: d for d in decisions}
    pending = 0
    if _table(cur, "pr_agent_approvals"):
        cur.execute("SELECT count(*) FROM public.pr_agent_approvals WHERE workspace_id=%s AND requested_for=%s AND state='pending' AND expires_at>now()",
                    (workspace_id, user_id))
        pending = int(cur.fetchone()[0])
    explicit = grants.source == "explicit"
    domains = sorted(grants.domains) if explicit else list(ALL_DOMAINS)
    return {
        "available": True, "mode": mode,
        "state": {"source": grants.source, "preset": grants.preset, "baseline": grants.baseline, "epoch": grants.user_epoch,
                  "spendConfirmation": grants.spend_confirmation if explicit else "none", "decidedAt": grants.decided_at,
                  "consentVersion": grants.consent_version if explicit else None, "needsChoice": not explicit, "ended": grants.ended,
                  "newSinceDecision": sum(1 for c in caps if explicit and c.since > grants.catalogue_generation), "token": grants.token()},
        "reminder": reminder(cur, workspace_id, user_id, grants, now=now),
        "role": member.summary() if member is not None else None,
        "categories": [_category_view(cat, grants, decisions) for cat in CATEGORIES],
        "domains": [{"id": d, "granted": d in domains, "clippedBy": None} for d in ALL_DOMAINS],
        "capabilities": [{**entry, "effective": by_id[entry["capabilityId"]].public()} for entry in entries if entry["capabilityId"] in by_id],
        "presets": presets_view(),
        "autopilot": {"available": False, "policies": [{"id": p.id, "capabilityIds": sorted(p.capability_ids), "expiresAt": p.expires_at} for p in grants.autopilot]},
        "pendingApprovals": pending,
        "consentVersion": CONSENT_VERSION, "copyDigest": COPY_DIGEST, "catalogueDigest": authz.catalogue_digest(), "copy": COPY,
    }


def members_overview(cur, workspace_id) -> dict:
    """Owners and admins: who chose what (no history bodies, no scopes of anyone's private data)."""
    if not ready(cur):
        raise unavailable()
    cur.execute("SELECT m.user_id::text,m.role,coalesce(p.display_name,''),s.preset,s.epoch,extract(epoch from s.decided_at),s.ended_at IS NOT NULL,"
                "s.spend_confirmation FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id LEFT JOIN public.pr_agent_permission_state s "
                "ON s.workspace_id=m.workspace_id AND s.user_id=m.user_id WHERE m.workspace_id=%s AND m.status='active' AND p.deleted_at IS NULL "
                "ORDER BY m.role, m.user_id", (workspace_id,))
    members = []
    for uid, role, name, preset, epoch, decided, ended, spend in cur.fetchall():
        explicit = preset is not None and not ended
        members.append({"userId": uid, "displayName": name, "role": role, "source": "explicit" if explicit else "legacy",
                        "preset": preset if explicit else "legacy", "epoch": int(epoch or 0), "decidedAt": float(decided) if decided and explicit else None,
                        "spendConfirmation": spend if explicit else None})
    return {"members": members}
