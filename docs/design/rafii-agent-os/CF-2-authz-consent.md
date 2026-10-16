# CF-2 — Consent, permissions and enforcement (`rafii-agent-authz/1` §2–§5), amended

**Status:** PROPOSED, amended; independent review and recorded validation required before freeze. Every critical and high correction that touches CF-2 is folded into this text and into the one DDL file [`migrations/109_agent_permissions.sql`](migrations/109_agent_permissions.sql). One literal stays open by James's instruction: the Recommended preset's spend-confirmation scope (DECISIONS-NEEDED **SD-1**). It is a versioned preset value, not schema: the column already accepts every option, so CF-2 can freeze with the recommended value and change only `PRESETS` if James picks the other one before launch.
**Depends on:** CF-1 (registry, `SurfaceBinding`, INV-10). **Consumed by:** CF-3 (`decide_for_step`, `Grants.token()`, error codes), lanes C/H (HTTP shapes, error table), G (autopilot shape).
**Base verified:** `origin/consumer-saas` `de4e5907`. Paths relative to `src/postriff_phase2/` unless they start with `migrations/`, `web/`, `tests/` or `docs/`.

**James decisions applied (2026-10-09):** DP-3/DP-4 (existing users and "Not now" keep today's behaviour, no backfill, reminder at most every 7 days; Recommended = read/navigate/create at Assist, everything else at Ask; Full needs a fresh sign-in, never covers R2/R3, respects workspace budget ceilings), DP-5 (R2 native button; R3 navigate-only with re-auth ≤ 5 min; typed/spoken "yes" only for the legacy schedule/automation proposals; consent-type GenUI actions stay R2 with native confirmation), DP-8 (332ed6e6 is the ordinary-user test workspace), DP-1 (live 60-case gate before enforce on a GenUI workspace, CF-1 §9).

---

## 1. Concepts

- **Scopes** (strings): `category:<CATEGORY>` with mode `ask` or `assist`; `domain:<DATA_DOMAIN>` with no mode; `capability:<capability_id>` with mode `off`, `ask` or `assist` (Custom's fine-grained switches; it can grant one capability while its category is off, but its data domains are still required).
- **Presets:** versioned literal scope sets `recommended`, `full`, `none`. `custom` is what the person chose. `legacy` is the code-resolved state when no row exists or the row has `ended_at` set.
- **Autonomy:** *Ask* — Rafii proposes and every R1 change needs a native confirmation. *Assist* — R0 and free R1 run directly; costs follow `spend_confirmation`. *Autopilot* — only through `pr_agent_autopilot_policies` (bounded capability list, constraints, limits, expiry ≤ 30 days, step-up to create, never R3; P2 runner only).
- **Epochs (cache invalidation only).** `pr_agent_permission_state.epoch` per person (missing row = 0) is bumped on every change; `pr_agent_workspace_policy.epoch` per workspace (missing row = 0) is bumped when an owner narrows a workspace consent or changes a ceiling.
- **`Grants.token()` (correction 3):** `sha256(canonical({"u": user_epoch, "w": workspace_epoch, "s": source, "b": baseline, "p": preset, "e": ended, "g": CATALOGUE_GENERATION}))`, 64 hex. It keys caches, the GenUI `permission_revision`, and is recorded on tasks, attempts and approvals as `authz_token`. It is **compared only for equality (`<>`), never ordered**, and it never decides whether a check runs: `decide()` runs on every claim and every inline step start regardless (§8.4). The draft's epoch sum (X2) is dropped: it could fall when rows were removed, and it never moved for provider disconnects, flags, plan changes or consent paths that skip `bump_workspace`.
- **Catalogue generation floor:** the state row stores the `catalogue_generation` it was decided under. A capability with `since >` that generation and risk ≥ R1 is floored to `native`, so it asks once; new tools never silently join a granted category.

## 2. Presets and copy (frozen literals in `agent_runtime_v2/agent_permissions.py`)

```python
CONSENT_VERSION = "agent-permissions/1"
PRESET_VERSION = 1
ALL_DOMAINS = tuple(d for d in DATA_DOMAINS if d != "public")           # 'public' is always allowed
SENSITIVE_ASSIST = ("manage_settings", "manage_connected_services", "execute_automations")   # assist here needs step-up
PRESETS = {
  "recommended": {"categories": {"read_analyze": "assist", "navigate_interact": "assist", "create_edit": "assist",
                                 "manage_settings": "ask", "manage_connected_services": "ask", "execute_automations": "ask"},
                  "domains": ALL_DOMAINS,
                  "spend_confirmation": "all"},          # SD-1 OPEN: recommendation 'all' = matches today's credit quotes
  "full":        {"categories": {c: "assist" for c in CATEGORIES}, "domains": ALL_DOMAINS,
                  "spend_confirmation": "none", "step_up": True},
  "none":        {"categories": {}, "domains": (), "spend_confirmation": "all"},
}
LEGACY_EQUIVALENT = {"categories": {"read_analyze": "assist", "navigate_interact": "assist", "create_edit": "assist",
                                    "manage_settings": "assist", "execute_automations": "assist"},
                     "domains": ALL_DOMAINS, "spend_confirmation": "none", "baseline": "legacy_v1"}
SPEND = {"none": (), "media": ("media_credits",), "all": ("text_credits", "media_credits")}
```

- **SD-1 (open; recommendation `all`).** Today's credit quotes make no media/text distinction: on a workspace with an active credit policy, every paid writer run (`ideas.py:1312,1463`), every media-notes read (`media_notes.py:261,318`) and every image (`credit_requests.py:23`, "Images need a separate credit approval") needs its own person-confirmed limit (`credit_wallet.py` `prepare`: "Confirm this task credit limit before generating", 402). `all` matches that. A valid credit quote bound to the same request digest counts as the native spend confirmation, so a credit-billed person is asked once, not twice.
- **Full** never lowers a risk floor: R2 keeps its native confirmation or proposal, R3 stays native-only. Full sets `spend_confirmation='none'` but never bypasses `billing.reserve`'s own stops (`billing.py:200-225`: per-request maximum, per-person 24 h stop, workspace/global budgets, founder cap, and a credit-billed workspace's quote), the task's `budget_ceiling_usd_micro` (CF-3 §9) or an owner's `pr_agent_workspace_policy.ceiling`. Choosing Full needs a fresh sign-in (§10).
- `LEGACY_EQUIVALENT` is materialized only when a legacy person narrows something, so the rest keeps today's behaviour. It keeps `baseline='legacy_v1'`, so it keeps today's Manager toolset (CF-1 §13).
- `permission_copy.json` (server-authored) holds `{consentVersion, categories, domains, presets, capabilities, spend, revoke, notRecallable, reminder}` copy. Its sha256 is the `copy_digest` the browser must echo on PUT. Wording, launch languages and legal review are DP-6 (DECISIONS-NEEDED); the contract fixes only the keys.

## 3. Defaults (DP-3/DP-4, decided)

- **Existing members, new members and anyone choosing "Not now"** resolve to `Grants(source="legacy", preset="legacy", user_epoch=0)`: exactly today (`LEGACY_BASELINE_V1` with each surface's legacy confirmation). No backfill, no new category (`manage_connected_services` has nothing), no autopilot, no R3.
- **Reminder:** non-blocking, at most every 7 days per person and workspace, across devices. The cadence is server-side in `pr_agent_permission_reminders` (109), which never grants or narrows anything. GET returns `reminder: {due, nextAt}`; the client reports `POST …/agent/permissions/reminder {action: "shown"|"not_now"|"dismissed"}`. "Not now" stores only the reminder row.
- **Viewers and approvers** may save any preset; `decide()` step (b) always clips by role. They still reach only the grounded site agent (`service.py:161-162`).

## 4. Data model — migration 109 (full DDL in [`migrations/109_agent_permissions.sql`](migrations/109_agent_permissions.sql))

| Table | Purpose | Amendments folded in |
|---|---|---|
| `pr_agent_permission_state` | one row per person and workspace after a choice | FK to `pr_memberships(workspace_id, user_id)` **ON DELETE RESTRICT**; `ended_at` (membership ended, correction 12); `step_up_at` with CHECK "Full needs a recorded fresh sign-in"; server has **no DELETE** |
| `pr_agent_consent_receipts` | append-only receipt per change | `request_fingerprint` (correction 11); `source` excludes GenUI (PI-7); `unique (id, workspace_id, user_id)` so grants and autopilot reference the same person by composite key (correction 13); CHECK "a widening to Full carries step-up evidence" |
| `pr_agent_grants` | one row per granted scope | FK to state **ON DELETE RESTRICT** (a cascade cannot erase history, correction 12); composite FK to its receipt; server may only write `revoked_*`, once (trigger) |
| `pr_agent_workspace_policy` | workspace epoch + optional category ceiling | unchanged (owner API deferred, DP-22) |
| `pr_agent_autopilot_policies` | P2 bounded autopilot | FK to state **ON DELETE RESTRICT**; composite FK to receipt; `membership_ended` revoke reason |
| `pr_agent_permission_reminders` | reminder cadence (DP-3/DP-4) | new; not history, follows the membership row |
| ~~`pr_agent_approvals`~~ | — | **removed from 109** (X1): one approvals table, in 108 |

All tables: forced RLS, `service_only` policy, `REVOKE ALL` from `public, anon, authenticated, service_role` then explicit per-table server grants (the 105/106 pattern, which also neutralizes Supabase's default privileges). `postriff_private.agent_permissions_erase(wid)` is the only delete path (§6). Rollback: flags off; tables stay.

## 5. Store API (`agent_runtime_v2/agent_permissions.py`, lane B; frozen signatures)

```python
@dataclass(frozen=True)
class AutopilotPolicy: id: str; capability_ids: frozenset; constraints: dict; limits: dict; usage: dict; expires_at: float

@dataclass(frozen=True)
class Grants:
    workspace_id: str; user_id: str
    source: str                         # 'legacy' | 'explicit'
    preset: str                         # 'legacy' | 'none' | 'recommended' | 'full' | 'custom'
    baseline: str | None                # 'legacy_v1' | None
    user_epoch: int; workspace_epoch: int
    ended: bool                         # membership ended and not re-decided: resolves as legacy + needsChoice
    categories: Mapping[str, str]; capabilities: Mapping[str, str]; domains: frozenset
    spend_confirmation: str             # 'none' | 'media' | 'all'
    catalogue_generation: int
    autopilot: tuple[AutopilotPolicy, ...]
    ceiling: Mapping[str, str] | None
    def token(self) -> str: ...         # §1; 64 hex

def load(cur, workspace_id, user_id, *, now) -> Grants              # 3 indexed reads; legacy when no row OR ended_at set
def epochs(cur, workspace_id, user_id) -> tuple[int, int]          # 2 PK reads (cache revalidation only)
def view(cur, workspace_id, user_id, member, state, *, now) -> dict           # GET payload (§16)
def apply_decision(cur, *, workspace_id, principal, token, payload, source, now) -> dict   # PUT; step-up aware; returns receipt
def revoke(cur, *, workspace_id, principal, scopes, all_, idempotency_key, source, now) -> dict
def history(cur, workspace_id, user_id, *, cursor=None, limit=50) -> dict
def remind(cur, *, workspace_id, principal, action, idempotency_key, now) -> dict
def bump_workspace(cur, workspace_id, *, actor, reason, denied_consents) -> dict
def on_membership_ended(cur, workspace_id, user_id, *, actor) -> None          # §6
def erase_workspace(cur, workspace_id) -> int                                   # §6; account deletion only
def catalogue_diff(before: Grants, after: Grants, *, member, state) -> CatalogueDiff
def consent_effect(cur, workspace_id, before, after, principal) -> None         # appended to repository.effects

@dataclass(frozen=True)
class CatalogueDiff:                     # correction 5: ONE function computes both
    widened: frozenset                   # capability ids newly reachable on any surface, less restricted, or with a lower confirmation
    denied_now: frozenset                # capability ids allowed before and denied after
    spend_looser: bool

@dataclass(frozen=True)
class RevocationEvent:
    workspace_id: str; user_id: str | None           # None = workspace-wide consent narrowing
    denied_now: frozenset; token_after: str; receipt_id: str; reason: str
REVOCATION_HANDLERS: list[tuple[str, Callable[[Any, RevocationEvent], int]]] = []
def register_revocation_handler(name, fn) -> None
```

`catalogue_diff` evaluates `decide()` for every `public_catalogue()` entry on every surface it is reachable from (CF-1 `reach()`), under both `Grants`. `widened` is non-empty when any capability becomes reachable (including Manager-scope membership), moves from `deny` to anything else, or gets a lower effective confirmation; `spend_looser` when the spend set shrinks. The receipt's `widened` column is `bool(diff.widened) or diff.spend_looser`. The same diff yields `denied_now` for revocation.

## 6. Membership end and account deletion (correction 12)

- `pr_memberships` has PK `(workspace_id, user_id)` and `status in ('active','revoked')` (`001_phase2.sql:13-17`). Leaving (`hosted.py` `leave_workspace`, the UPDATE at `:801`) and removal (`remove_member`, `:1033`) are UPDATEs to `status='revoked'`; a re-invite reactivates the same row (`_join`, `:1117`). So no foreign-key cascade fires on removal.
- `on_membership_ended(cur, workspace_id, user_id, *, actor)` runs in the same transaction as **every** path that sets `status='revoked'`: revoke every active grant (`membership_ended`), revoke autopilot, set `preset='none'`, `baseline=NULL`, `ended_at=now()`, bump the epoch, write a `membership_ended` receipt, run `REVOCATION_HANDLERS` (including CF-3's `agent_tasks`). A test enumerates every `UPDATE public.pr_memberships SET status='revoked'` in `src/` and fails if any path lacks the call.
- `load()` treats `ended_at IS NOT NULL` as no choice (legacy + `needsChoice`), so a re-invited member is like any other member and old grants never return. A later confirmed PUT clears `ended_at`.
- **Account deletion** (`account_deletion.py`, which deletes `pr_memberships` at `:154` and then `pr_workspaces`) calls `agent_permissions.erase_workspace(cur, workspace_id)` — i.e. `postriff_private.agent_permissions_erase(wid)` — in the same transaction, **before** the membership delete. The function refuses unless the workspace carries `accountDeletion` and deletes children first. Without the call the RESTRICT foreign key makes the membership delete fail loudly; it never silently drops or keeps history. The disposable-PostgreSQL suite proves both (tests/phase2/postgres_agent_os_ddl.py AOS-04). The function is `SECURITY DEFINER` like `100_youtube_api_privacy_erasure.sql`'s erasure function; J confirms read-only that the migration owner bypasses RLS on staging, as that precedent already requires.

**Other delete paths:** `scripts/validate_postriff_hosted_preview.py` deletes test memberships before deleting their workspace; it must perform approved disposable workspace erasure first once permission rows exist. Cross-workspace profile deletion is currently unsupported by the legacy account-delete path: RESTRICT must fail closed, without deleting another workspace's consent history. A person-scoped erasure workflow and its authorization are explicitly deferred with DP-18; do not claim multi-workspace deletion works.

## 7. Revocation: one transaction, derivative invalidation

PUT, revoke, membership end and consent paths run inside `repository.transaction` (`hosted.py:113-133`), which locks `pr_workspaces FOR UPDATE OF w`; every tool's `ctx.workspace()` takes the same lock, so a revocation and an in-flight effect serialize.

**Mode boundary:** in shadow, permission choices and shadow diagnostics may be stored, but H1–H4 and all read-time filters below must not change legacy proposals, activations, task state, context, manifests or receipts. Compute would-invalidate counts only. Enforcement effects run only in `enforce`; workspace consent paths retain their pre-existing independent enforcement. `user_id=None` means every affected person in that workspace, never an SQL equality to NULL.

1. Lock or insert the state row; bump `epoch`; set `revoked_*` on replaced/removed grants; insert new rows (receipt first).
2. `diff = catalogue_diff(before, after)`.
3. Run `REVOCATION_HANDLERS`, storing counts in `receipt.invalidated`:
   - **H1 `approvals`** (rows now in 108): `UPDATE pr_agent_approvals SET state='revoked', decided_at=now(), decision_surface='system' WHERE workspace_id=%s AND (requested_for=%s OR %s IS NULL) AND state IN ('pending','approved') AND capability_id = ANY(%s)`.
   - **H2 `proposals`:** open `siteAgent.proposals` created in the last 24 h by this person whose type maps to a denied capability (`schedule_draft`/`reschedule_post` → `tool.schedule_propose`, `automation_change` → `tool.automation_change_propose`) close with the `dismiss_proposal` transition and `closedReason: "permission_revoked"`.
   - **H3 `agent_tasks`** (CF-3 §14): open steps of this person's tasks whose capability is denied become `blocked/permission_revoked`; their checkpoints are discarded; `next_wake_at=now()` on the rest. For `membership_ended`, the person's open tasks are cancelled (`cancelled_by_revocation`) except delegate steps that observe an external effect (CF-3 §4.4), which keep polling as the read-only observer (CF-3 §6.1, verdict `observe`) until the job is final or the hard cap.
   - **H4 `ui_activations`:** `UPDATE pr_ui_activations SET used_at=now() WHERE workspace_id=%s AND (principal=%s OR %s IS NULL) AND used_at IS NULL AND expires_at > now()`.
   - **H5 `autopilot`:** revoke policies whose `capability_ids && denied_now` (`permission_changed`).
   - Placeholders other lanes fill: `suggestions` (P2), `memory_proposals` (Brand Brain lane).
4. **Read-time filters** (no writes, effective from the next request): GenUI manifests narrow in `current()` because `permission_revision` includes `grants.token()`; `ui_store.snapshot` serves the native fallback with `revokedByPermission: true`; `service._history` (`service.py:590`) drops prior assistant messages whose `artifact.trace.authz.capabilities` overlap the denied set; in-process caches key on `grants.token()`.
5. `not_recallable` is filled truthfully: `sent_to_model_provider` when any revoked R0 capability was used; `visible_in_past_answers`; `already_applied_changes` when an R1+ capability was revoked.
6. Audit `agent.permission.revoked` / `agent.permission.revoked_all` (§14).
7. **Workspace consent narrowing:** turning off `memory_egress`, `research_egress`, `media_egress` or `connector_egress` bumps `pr_agent_workspace_policy.epoch` and runs the handlers with `user_id=None`. Lane B adds explicit `bump_workspace` calls on consent paths outside `repository.command` (radar/growth consent, voice sample revoke). Because `decide()` runs on every claim (§8.4), a missed bump can delay a cache invalidation but never lets a step run against a stale verdict.
8. "Turn off Rafii's access" (`all: true`): preset `none`, every row revoked, every autopilot policy revoked, one epoch bump.
9. Reconnecting a channel never restores consent; disconnecting changes no grants (the existing purge cascade runs as today). Provider truth is re-read on every decision (§12.1).

## 8. Enforcement (lane A.2)

### 8.1 `agent_runtime_v2/authz.py`

```python
@dataclass(frozen=True)
class Actor:
    kind: str            # 'agent' (model tool call) | 'human_ui' (GenUI control after its activation) | 'approval' | 'autopilot' | 'recipe'
    principal: str
    request_text: str = ""   # ONLY the current human message of this request. Cron, continuation, retry and every context that
                             # is not a fresh human message pass "" (correction 9), so explicit_request capabilities deny there.
    evidence: dict | None = None   # {'activationId'} | {'approvalId','digest','stepUp'} | {'creditQuoteId','requestDigest'} | {'policyId'}

@dataclass(frozen=True)
class Decision:
    outcome: str         # 'allow' | 'confirm' | 'approve' | 'step_up' | 'deny'
    reason: str          # REASON_CODES
    capability_id: str; capability_version: int; category: str; risk: str
    required: str        # effective confirmation AFTER INV-10 (never below the surface's legacy confirmation)
    detail: str | None = None; policy_id: str | None = None; token: str = ""

REASON_CODES = ("allowed", "founder_tenant", "role", "workspace_consent", "workspace_ceiling", "feature_off", "not_in_baseline",
                "category_off", "capability_off", "domain_off", "provider_not_connected", "provider_reauth_required",
                "provider_scope_missing", "provider_lane_mismatch", "provider_capability_unsupported", "explicit_request_required",
                "needs_confirmation", "needs_approval", "needs_step_up", "native_only", "autopilot_not_covered", "autopilot_limit",
                "rate_limited", "cost_limit", "membership_missing", "permissions_changed")
CONSENT_READERS = {   # IMPLEMENTED readers; absent means off
  "memory_cloud":    lambda s, t: memory.egress(s).get("cloud") is True,
  "research_web":    lambda s, t: research.allowed(s),
  "media_cloud":     lambda s, t: media_consent.decision(s).get("cloud") is True,
  "connector_cloud": lambda s, t: productivity_connectors.egress_decision(s).get("cloud") is True,
  "growth":          lambda s, t: bool(s.get("growthConsent")),
  "radar":           lambda s, t: bool((s.get("radarConsent") or {}).get("sources")),
  "voice_sample_route": lambda s, t: True,   # enforced per sample by voice_sources; declared for the UI only
  "library_purpose": lambda s, t: True,      # delegates to library_intelligence.policy.recheck once #144 merges
}
FLOOR = {"R0": {"ask": "none", "assist": "none"}, "R1": {"ask": "native", "assist": "none"}}   # R2: cap.confirmation; R3: approval_step_up

def decide(cap, *, surface, member, grants, state, actor, provider_view=None, target=None, now) -> Decision:
    legacy = capability_registry.surface(surface.name, surface.binding_ref).legacy_confirmation
    # (a) capability policy (static)
    if cap.kind == "native_only":                                      return _d(cap, "step_up", "native_only")
    if cap.tenant == "founder":                                        return _d(cap, "allow", "founder_tenant")
    # (b) user rights (authoritative, unchanged)
    if member is None:                                                 return _d(cap, "deny", "membership_missing")
    if not member.allows(cap.permission):                              return _d(cap, "deny", "role")
    # (c) workspace / resource rights
    for key in cap.consents:
        if not CONSENT_READERS[key](state, target):                    return _d(cap, "deny", "workspace_consent", key)
    if grants.ceiling and grants.ceiling.get(cap.category) == "off":   return _d(cap, "deny", "workspace_ceiling")
    # (d) agent consent
    if grants.source == "legacy":
        if cap.capability_id not in LEGACY_BASELINE_V1:                return _d(cap, "deny", "not_in_baseline")
        required = legacy
    else:
        if grants.baseline == "legacy_v1" and cap.capability_id not in LEGACY_BASELINE_V1:
                                                                       return _d(cap, "deny", "not_in_baseline")
        override = grants.capabilities.get(cap.capability_id)
        if override == "off":                                          return _d(cap, "deny", "capability_off")
        mode = override or grants.categories.get(cap.category)
        if grants.ceiling and grants.ceiling.get(cap.category) == "ask": mode = "ask" if mode else None
        if mode is None:
            if cap.risk == "R0" and cap.data_grants == ("public",):     mode = "assist"
            else:                                                      return _d(cap, "deny", "category_off")
        missing = [d for d in cap.data_grants if d != "public" and d not in grants.domains]
        if missing:                                                    return _d(cap, "deny", "domain_off", missing[0])
        floor = FLOOR[cap.risk][mode] if cap.risk in FLOOR else ("approval_step_up" if cap.risk == "R3" else cap.confirmation)
        if cap.cost in SPEND[grants.spend_confirmation]:              floor = _max(floor, "native")
        if cap.since > grants.catalogue_generation and cap.risk != "R0": floor = _max(floor, "native")
        required = _max(legacy, _max(cap.confirmation, floor))        # INV-10
    # (e) provider grants (read-only; never decrypts)
    for scope in cap.provider_scopes:
        reason = provider_grants.check(provider_view, scope, target, now=now)
        if reason:                                                     return _d(cap, "deny", reason)
    # (f) explicit request: only the current human message
    if cap.explicit_request and actor.kind == "agent" and not EXPLICIT_REQUEST[cap.capability_id](actor.request_text):
                                                                       return _d(cap, "deny", "explicit_request_required")
    # (g) autonomy and confirmation
    if actor.kind == "autopilot":
        policy = _autopilot_cover(grants, cap, target, now)
        if policy and cap.autopilot_eligible and cap.risk in ("R1", "R2"): return _d(cap, "allow", "allowed", policy_id=policy.id)
        return _d(cap, "deny", "autopilot_not_covered")
    if required == "none":                                             return _d(cap, "allow", "allowed")
    if required == "native":
        return _d(cap, "allow", "allowed") if _evidence_ok(actor, cap) else _d(cap, "confirm", "needs_confirmation")
    if required == "proposal":
        return _d(cap, "allow", "allowed") if (cap.approval or actor.kind == "approval") else _d(cap, "approve", "needs_approval")
    return _d(cap, "allow", "allowed") if _step_up_ok(actor, now, window=R3_REAUTH_SECONDS) else _d(cap, "step_up", "needs_step_up")
```

`_evidence_ok` is true for `human_ui` with an activation consumed for this capability, for `approval` with a matching `approvalId` and `digest`, and for spend floors when a valid credit quote for the same request digest is presented. `decide()` is **pure** over DB-derived state and constants; no model output feeds it (PI-6).

### 8.2 Modes

`authz.gate(ctx, cap, args, surface) -> Decision` wraps `decide()` with `RuntimeConfig.permissions_for(workspace_id)`. The other entry points (`gate_site`, `gate_proposal`, `recheck`, `recheck_principal`, `decide_for_step`) apply the same three modes:

- **`off`** returns `allow` without evaluating, with `required` = the surface's `legacy_confirmation`: exactly today's behaviour.
- **`shadow`** evaluates `decide()` and logs `agent.authz.shadow` with `wouldOutcome`, `wouldRequired` and `wouldReason`, then returns the **same Decision `off` returns**. Everything a person, a client or the model receives is byte-identical to `off`: every GenUI manifest (bindings, `actionTargets`, `permissionRevision` and the `revised` flag), every query result, the activate response including `confirmation.required`, every execute receipt and `pr_ui_actions` row, tool results and error bodies (E1–E3), the Manager and specialist tool lists (E10), APP_STATE (E11), proposal applies (E7), and the task engine's step verdicts. No approval row is created and no grant-derived value enters a cache key a client can see.
- **`enforce`** returns the decision. **Only `enforce` may narrow, deny or add a confirmation**; `shadow` and `off` never do (CF-1 INV-11). So shadow on a GenUI workspace (267f7d90) is allowed before DP-1's live gate, and enforce is not.

Rate and cost limits apply after an `allow` (`hosted.throttle`, ledger counters, the executor's estimate), as today. **Enforce requires `task_engine_for(ws) == 'on'` in the same workspace** (X1: approvals are engine rows; CF-3 §21.1); shadow needs no approval rows.

### 8.3 Where it runs

| # | Path | Today (file:line) | Change |
|---|---|---|---|
| E1 | Every model tool call (Manager, specialists, `commands.direct`, GenUI `run_tool`) | `tool_adapter.execute` `:96-144` | After the role check at `:109`, `decision = authz.gate(ctx, spec.policy(), args, surface)`. In enforce: **deny** → `{ok:false, code:"agent_permission_denied", reason, category, settingsHref:"/app/account/agent"}`; **confirm** → `task_engine.request_approval(...)` (CF-3 §10.1) and `{ok:false, needsUser:true, code:"needs_confirmation", approvalId, summary, expiresAt}`; **step_up** → `{ok:false, needsUser:true, code:"native_only", href, reauth:{maxAgeSeconds:300}}`; `ctx.membership is None` is a deny. In off and shadow the gate returns the off result, so the call runs as today. Sets `ctx.active_capability` and the `authz.IN_TOOL` ContextVar around the executor. |
| E2 | Every executor transaction | `context.py:141-150` `workspace()` | When `ctx.active_capability` is set, `authz.recheck(cur, ctx)` re-runs the gate in this transaction (cheap, pure); a deny (enforce only) raises `AlphaError(403, code="agent_permission_revoked")`. |
| E3 | Grounded site agent | `site_agent/tools.py` `run()` | `authz.gate_site(ctx, capability_registry.site_capability(tool_id))` when `ctx.grants` is present, on the grounded path only (a call that arrives through `tool_adapter._site_executor` was gated by E1 under its own surface and carries `authz.IN_TOOL`). All 37 ids resolve (CF-1 §5.1): the 36 adapted ids to their `tool.*` capability, `automation.patch_propose` to `site.automation_patch_propose` (R2, proposal). A deny (enforce only) is a `blocked` tool record with code `agent_permission_denied`. |
| E4 | GenUI manifest | `ui_capabilities.py:42, 91, 168` | Keep bindings whose `authz.gate` is not deny (so bindings narrow only in enforce); `permission_revision` includes `grants.token()` only in enforce; `UiAuth` gains `grants` when the mode is not off, so shadow can log what it would remove. |
| E5 | GenUI query | `ui_queries.py` | `authz.gate(actor=human_ui)`; a deny (enforce only) → the existing 403 → `denied`. |
| E6 | GenUI activate/execute | `ui_actions.py:84 (_confirmation), 91 (activate), 193 (execute)` | Modes `off` and `shadow`: today's `_confirmation` and execute path unchanged; shadow only logs `wouldOutcome`/`wouldRequired`. **Enforce** — activate: deny → 403 `agent_permission_denied`; **`confirmation.required = (decision.required != "none")`**, which with INV-10 can only turn a confirmation on, never off. Execute: the gate runs again; deny → stored `rejected` receipt with that code. Two-phase: recheck immediately before the paid dispatch. |
| E7 | Legacy proposal apply | `approvals.py:136` decide; `service.py:1081, 1095` claim/resume pending run | `authz.gate_proposal(...)` re-decides the proposal's capability **for its creator** with `actor.kind="approval"`; a deny (enforce only) → 403 `agent_permission_revoked`. The decider's own right to apply (approve class) is checked as today. **Resume rule (correction 2, same as CF-3 §10.3; it is the engine's rule, so it applies where `task_engine_for(ws) == 'on'` and today's apply path runs unchanged elsewhere):** the paused run resumes only when the decider is the task's `created_by`; otherwise the proposal is applied, the continuation becomes `blocked/needs_input` with `needsMe.kind='continue'` for the creator, the response says `resumed:'none'`, and no continuation text is returned to the decider. |
| E8 | New approvals | — | Decided only through CF-3's `resolve_approval` (§11). There is no separate `agent_approvals.decide` executor. |
| E9 | Background principals | `automation_runs.py:38` `principal_repository` | Gains `capability=`; every transaction calls `authz.recheck_principal(...)`. Human-configured automations are not gated by agent grants in P0 (they are the person's own standing instructions). |
| E10 | Manager and specialist build | `manager.py`; `specialists.build` | Tools come from `reach(surface, grants)`; drop those whose `authz.gate` is deny (enforce only). Tools that only need confirmation stay. |
| E11 | Context assembly | `service.py:604` `_assemble`, `:590` `_history` | Each APP_STATE section is passed through the explicit `authz.context_gate` protocol below on its `context.*` capability (all five are in `LEGACY_BASELINE_V1`, CF-1 §12); enforce reads only when its effective result is `allow`. `_history` applies the revoked-capability filter in enforce. |
| E12 | Grants at turn start | `service.py` turn transaction | `ctx.grants = agent_permissions.load(...)`; same in `run_tool`, `commands.direct` and the site-agent context. |

**E11 adapter protocol (shared by assembly and Context Lens):**

```python
def context_gate(capability_id: str, *, cur, state: dict, workspace_id: str,
                 principal: str, member, config, now: float) -> Literal["allow", "deny"]: ...
```

Call with the caller's already-open, workspace-locked transaction and server-resolved state/member, including Context Lens `Inputs.cur`/`state`; never open a nested transaction. `off` returns `allow` before registry or database reads. Otherwise resolve the registered context capability and its `context` surface binding, load this principal's grants once for the transaction, then call `decide()` with `Actor("agent", principal, request_text="")`. In `shadow`, log content-free `wouldOutcome`/`wouldReason` or evaluation error and return effective `allow` regardless. In `enforce`, only `Decision.outcome == "allow"` returns `allow`; `confirm`, `approve`, `step_up`, `deny`, an unknown capability or any lookup/evaluation error returns `deny`. No prompt text, content or provider/model calls enter the adapter. Existing membership, role and workspace checks apply independently in every mode. A missing permission module preserves the pre-integration path; a present module with an incompatible/missing adapter is an integration failure, covered by tests using the actual modules rather than only a fake `gate`.

New `RafiiRunContext` fields (added by A.1's first commit together with CF-3's stubs, X11): `grants`, `active_capability`, `authz_actor`, `authz_evidence`, `authz_mode`, plus CF-3's `step_binding` and `effect_key()`.

### 8.4 The step seam for CF-3 (X3, correction 3)

```python
@dataclass(frozen=True)
class StepVerdict:
    verdict: str          # 'allow' | 'approve' | 'step_up' | 'deny' | 'observe' (read-only external-effect observer, CF-3 §6.1)
    approval_kind: str | None   # 'agent_action' (from confirm) | 'proposal' (from approve) | 'spend' | 'step_up_action'
    reason_code: str      # CF-3 step reason code (table below), or 'allowed'
    authz_reason: str     # the REASON_CODES value
    token: str            # Grants.token() used for this decision
    required_permission: str; approver_policy: str; requires_step_up: bool

def decide_for_step(cur, task, step, *, actor: Actor, now) -> StepVerdict
```

It loads grants, workspace state and the provider view in `cur`, calls `decide()` with the step's capability and `surface=manager` (or the step's recorded surface), and maps the outcome. **CF-3 calls it on every claim and every inline step start**; the epoch is used only to invalidate cached `Grants`. A provider disconnect between s1 and s2 therefore blocks s2 with zero epoch change (acceptance test CF-2 A7). In `off` and `shadow` it returns `allow` (shadow logs the would-be verdict), and the permission gate adds no restriction to independently enabled engine execution (CF-3 §21.1). The read-only observer exception below is engine lifecycle authority, not a new permission grant.

**Observer exception (one rule).** For a cron poll of a `delegate` step with `observes_external` (`publish_job`, `automation_item`) **on a task that is cancel-requested or whose creator's membership has ended**, `decide_for_step` returns `observe` without loading grants: the poll reads one record by id inside `step.workspace_id`, writes only that step's mirror, never acts, never spends and makes no provider request. Every other claim, including the same observer while its creator is an active member on an open task, is decided normally. 108 accepts the `observe` verdict only on such steps and only from cron (guard + CHECK).

| `decide()` outcome / reason | Step verdict | Step `reason_code` |
|---|---|---|
| allow / allowed, founder_tenant | allow | — (founder-tenant capabilities are refused at plan time by CF-3) |
| confirm / needs_confirmation | approve (`agent_action`, or `spend` when only the spend floor asked) | — (`awaiting_approval`) |
| approve / needs_approval | approve (`proposal`) | — |
| step_up / needs_step_up | step_up (`step_up_action`) | — |
| step_up / native_only | deny | `needs_input` (with the native href) |
| deny / role, not_in_baseline, category_off, capability_off, domain_off, workspace_consent, workspace_ceiling, autopilot_not_covered | deny | `permission_revoked` if this step was allowed under an earlier token, else `permission_missing` |
| deny / permissions_changed | deny | `permission_revoked` |
| deny / membership_missing | deny | `member_inactive` |
| deny / provider_not_connected, provider_reauth_required | deny | `provider_disconnected` |
| deny / provider_scope_missing, provider_lane_mismatch, provider_capability_unsupported | deny | `provider_grant_missing` |
| deny / explicit_request_required | deny | `needs_input` |
| deny / feature_off | deny | `feature_unavailable` |
| deny / cost_limit, autopilot_limit | deny | `budget` |
| allow then rate_limited (post-allow limit) | — | retried with backoff (`retryable`), never blocked |
| — (observer exception above) | observe | — (the step keeps mirroring its job) |

## 9. Approvals (owned by CF-3's engine; the rules are frozen here)

- **One route (correction 4):** `POST /api/workspaces/{w}/agent/approvals/{approvalId}/decide {decision:'approve'|'reject', digest, idempotencyKey}`. The legacy body on `POST …/agent/approvals/decide` (`{conversationId, messageId, proposalId, digest, decision:'apply'|'dismiss', timeZone?}`, `http.py:78-79` → `service.py:1267`) stays byte-compatible and internally calls the same `task_engine.resolve_approval`. For the new kinds an approval only moves its step to `queued`; the step then executes solely through the engine's claim, receipt and lease path (inline, in the creator's request). A legacy proposal is applied through the existing proposal apply path, unchanged, which completes its `approval` step.
- **One digest:** new kinds use `sha256(capability_id, input_digest, sorted target {type,id,revision}, risk, generation)`; drift → 409 `approval_stale`. Proposals keep the proposal digest.
- **Who decides:** `agent_action` and `spend` → the task's creator only (`task_owner`; enforced by a CHECK in 108). Legacy proposals keep today's `role_approve`. `step_up_action` (R3) → `task_owner` or `role_owner` per verdict, with `require_step_up(window=300)`.
- **Channels (DP-5, decided; correction 17):** R2 needs a native button. A typed or spoken "yes" binds only to the legacy proposal types `schedule_draft`, `reschedule_post`, `automation_change`, within 600 s (`approvals.py:19, 73-98`). Against any other approval it returns the turn result `needs_panel_confirmation` with zero state change; a voice turn says "Confirm on screen." 108 enforces the same rule in a CHECK on `decision_surface`. Consent-type GenUI actions stay R2 with native confirmation.
- **Summaries (PI-8):** server-built from the current record; any model-supplied string appears only as labelled, quoted data.

## 10. Step-up (Full, sensitive Assist, R3, autopilot)

`authz.require_step_up(repository, token, principal, *, window)` requires all of: `repository.assert_fresh(token, principal)` (`hosted.py:135`); the newest signed `amr` method timestamp within `window`, via a new `hosted_identity.verified_method_time(...)` generalising the WebAuthn/passkey readers (JWT `iat` alone never counts — a refresh resets it); `aal2` when MFA is enforced; not an API token.

| Change | Window | Proof stored |
|---|---|---|
| PUT `preset:'full'` (DP-4) | 300 s | `state.step_up_at`, `receipt.step_up {method, at, aal}` (a CHECK in 109 refuses a Full widening without it) |
| PUT that sets `assist` on `manage_settings`, `manage_connected_services` or `execute_automations` (by category or by a capability in them) (correction 21) | 300 s | same |
| Agent-originated R3 handoff; `step_up_action` approvals (DP-5) | 300 s (`R3_REAUTH_SECONDS`) | approval `step_up` |
| Autopilot create (P2) | 300 s | policy `step_up_at` |

`"agent_autopilot_enable"` joins `permissions.STEP_UP_ACTIONS`. Native pages keep their own step-up (`STEP_UP_WINDOW = 600`, `permissions.py:57-58`); see DECISIONS-NEEDED R3-1 for whether those pages adopt 300 s outside a Rafii handoff.

## 11. Provider grants and prompt-injection rules

### 11.1 `agent_runtime_v2/provider_grants.py`

`ProviderView` is built once per transaction from the same customer truth as the Channels page (`channels.customer_view(channels.with_youtube_credential_status(...))`, `pr_channel_capabilities` levels). `check()` returns `provider_not_connected`, `provider_reauth_required` (disconnected, identity_known, token_expired, reauthorization_required, client_binding_missing), `provider_scope_missing`, `provider_lane_mismatch` or `provider_capability_unsupported`. It never calls `token_for_worker`/`reverify_for_worker` and never returns grant fields; executors' own gates (for example `youtube/agent_tools.py`) stay authoritative. Using `with_youtube_credential_status` also fixes the agent-vs-Channels disagreement (HF-2).

### 11.2 Rules (frozen)

- **PI-1 Authority inputs:** the verified session principal; DB rows (memberships, workspace consents, `pr_agent_*`); server constants; and, for `explicit_request` capabilities, the current human message of the current request. Tool arguments, history, retrieved data and model paraphrase never count.
- **PI-2 Untrusted data:** every tool result, page outline, Library/document text, web page, comment, notification, memory body, trend example and provider string reaches models as `untrusted(...)` data and is never parsed for grants, approvals or targets.
- **PI-3 Grant writes are human-only:** `apply_decision`, `revoke`, `remind` and autopilot create raise `AlphaError(403, code="agent_permissions_human_only")` when `authz.IN_TOOL` is set or the token is an API token. The registry lint fails if a capability's executor imports them.
- **PI-4 No self-approval:** approvals are created only from a `confirm`/`approve` verdict and decided only by a session whose principal satisfies the approver policy. The model has no approve tool.
- **PI-5 Targets (extended by correction 9):** at **plan time** every target id in a step's inputs must be in that turn's `ctx.ledger.known_ids ∪ ctx.chip_refs`; at **execution** it is re-resolved with `workspace_id = step.workspace_id`. External text cannot introduce new targets.
- **PI-6 Pure decisions:** `decide()` reads no model field; copy is server-authored and digest-checked.
- **PI-7 GenUI cannot widen:** no GenUI binding targets agent permissions in P0 (109 refuses `source='genui'` receipts).
- **PI-8 Summaries quote:** generic `SUMMARIZERS` render model-supplied strings as labelled, quoted data, each line ≤ 240 characters.

## 12. Cross-member exposure rules that CF-2 relies on

Conversations are workspace-shared (`ideas.py:703-722`). CF-3 makes tasks, approvals and idempotency per person (corrections 1, 2, 10, 11). Answers drawing on personal domains (`notifications`, `usage_billing`, `account`) stay visible to co-members in shared conversations until DP-18 (conversation privacy) is decided; that is deferred and recorded in DECISIONS-NEEDED.

## 13. Client-visible error codes (one table for CF-2 and CF-3; correction 16)

This is the **only** client-visible error vocabulary for the agent permission and task surfaces. TypeScript and Python constants are generated from one fixture, `tests/fixtures/agent_tasks/contracts/error-codes.json` (lane A.2 creates it from this table; a test asserts both languages match it). The draft codes `permission_revoked`, `permission_missing`, `agent_approval_closed`, `agent_approval_expired`, `agent_approval_digest` and `agent_approval_stale` are retired as error codes.

### 13.1 Errors

| Code | HTTP | Emitted by | Meaning |
|---|---|---|---|
| `agent_permissions_unavailable` | 404 | permissions routes | The permissions mode is off for this workspace. |
| `agent_permissions_changed` | 409 | PUT | `expectedEpoch` is stale; the body carries `current`. |
| `agent_permissions_copy_stale` | 409 | PUT | `consentVersion`/`copyDigest` is not the server's. |
| `confirmation_required` | 400 | PUT | A widening without `confirmed: true`. |
| `step_up_required` | 403 | PUT (Full, sensitive Assist), approval decide (R3), R3 handoff, autopilot create | A sign-in verified within `maxAgeSeconds` is needed; body `{stepUp:{required:true, reason, maxAgeSeconds}}`. |
| `agent_permissions_human_only` | 403 | grant writes | Called from a tool context or with an API token. |
| `scope_invalid` | 400 | PUT, revoke, autopilot | Unknown, founder-tenant or native-only capability; unknown domain; a constraint id outside this workspace (correction 13). |
| `idempotency_conflict` | 409 | PUT, revoke, approval decide, task create, cancel, retry, undo | Same namespaced key with a different body; task/approval workspace-wide keys also reject another member. Permission receipt keys are per actor (§16). Nothing about another actor is revealed. |
| `agent_permission_denied` | 403 / tool result | E1, E3, E5, E6; step claim | `decide()` denied; body `{reason, category, settingsHref}`. |
| `agent_permission_revoked` | 403 / tool result | E2, E7, approval decide, step claim and retry | Allowed earlier, denied now. |
| `approval_unavailable` | 404 | `approvals/{id}/decide` | Unknown, another workspace's, or not visible to the caller. |
| `approval_closed` | 409 | approval decide | Not pending; the body carries the stored outcome. |
| `approval_expired` | 409 | approval decide | Past `expires_at`. |
| `approval_stale` | 409 | approval decide | The client's digest is not the current one, or a target revision drifted (the step becomes `blocked/target_changed`). A grant that no longer allows it is `agent_permission_revoked`. |
| `approval_forbidden` | 403 | approval decide | The caller does not satisfy the approver policy. |
| `task_unavailable` | 404 | task routes | Unknown, another workspace's, or the engine is off for this workspace. |
| `task_forbidden` | 403 | task routes | Workspace scope without the owner class; cancel/retry/continue/undo/diagnostics by someone not allowed (CF-3 §17.2). |
| `task_conflict` | 409 | cancel, retry, `task_update` | Version compare-and-set failed. |
| `task_terminal` | 409 | cancel, continue | The task is completed or failed. |
| `task_too_long` | 400 | `task_plan` | More than 12 steps (existing). |
| `step_unknown` | 404 | step routes, `task_update` | Unknown step (existing). |
| `step_closed` | 409 | `task_update` | Terminal step (existing). |
| `step_not_retryable` | 409 | retry | Retry class `never`, R2/R3 auto, or not failed/blocked. |
| `retry_budget_exhausted` | 409 | retry | Generation 4 reached or the task's attempts are spent. |
| `undo_unavailable` | 409 | undo | No compensation for this step. |
| `undo_expired` | 409 | undo | Past `undo_until`. |
| `undo_conflict` | 409 | undo | The target changed since Rafii edited it; nothing was undone. |
| `proposal_digest` | 409 | legacy proposal apply | Existing digest mismatch; no new grant is inferred. |
| `approve_required`, `edit_required`, `owner_required` | 403 | legacy proposal apply | Existing role errors are preserved; no new grant is inferred. |
| `proposal_closed` | 409 | legacy `approvals/decide` body only | Unchanged legacy code (`site_agent/proposals.py:191`). |
| `proposal_expired` | 409 | legacy body only | Unchanged (`proposals.py:193`). |
| `proposal_stale` | 409 | legacy body only | Unchanged (`proposals.py:207-216`). |

### 13.2 Non-error result codes (tool and turn results, HTTP 200/201)

| Result code | Where | Meaning |
|---|---|---|
| `needs_confirmation` | tool result | An approval row was created; body `approvalId, summary, expiresAt`; render the native card. |
| `native_only` | tool result | R3: Rafii can only take you there; body `href`, `reauth`. |
| `needs_panel_confirmation` | turn result | A typed or spoken "yes" met a non-legacy approval; nothing changed. |

### 13.3 Step and task reason codes (state data, never an HTTP `code`)

| Reason code | Shown when |
|---|---|
| `permission_revoked`, `permission_missing`, `member_inactive`, `provider_disconnected`, `provider_grant_missing`, `budget`, `budget_ceiling`, `feature_unavailable`, `needs_input`, `needs_conversation`, `step_failed`, `target_changed` | blocked states |
| `dependency_failed`, `approval_expired`, `approval_rejected`, `task_expired`, `task_superseded`, `outcome_unknown`, `runtime_changed`, `cancelled_by_person`, `cancelled_by_revocation` | terminal states |

Clients render reason codes through copy keys; the mapping from `REASON_CODES` is §8.4.

## 14. Audit and correlated observability

- **Person-level kinds, added to `SECURITY_KINDS`** (`hosted.py:924`): `agent.permission.preset_applied`, `agent.permission.changed`, `agent.permission.revoked`, `agent.permission.revoked_all`, `agent.permission.membership_ended`, `agent.autopilot.enabled`, `agent.autopilot.revoked`, `agent.autopilot.expired`.
- **Workspace-level:** `agent.approval.requested`, `agent.approval.decided`, `agent.action.applied` (one per successful non-R0 effect unless the domain path already audits), `agent.action.denied` (R1+), `agent.permission.workspace_epoch`.
- **Meta (content-free):** `{capabilityId, capabilityVersion, category, risk, decision, reason, token, runId, traceId, taskId, stepKey, approvalId, policyId, receiptId, source, preset, widened}`. No schema change (`pr_audit_events.kind` is only length-checked).
- **Run trace:** `pr_agent_runs.artifact.trace.authz = {mode, token, capabilities: [ids used], decisions: [{tool, capabilityId, outcome, reason}]}`.
- **Logs:** one JSON line per decision `{"event":"agent.authz", outcome, reason, capabilityId, risk, mode, traceId, runId}` (shadow: `agent.authz.shadow`); R0 allows go only to the trace.

## 15. Flags, rollout and gates

- `config.FLAGS` gains `RAFII_AGENT_PERMISSIONS_ENABLED` (store, UI, shadow) and `RAFII_AGENT_PERMISSIONS_ENFORCED`, plus `RAFII_AGENT_PERMISSIONS_WORKSPACES` (empty = **no** workspace; `*` must be explicit, X10). `RuntimeConfig.permissions_for(ws)` → `off | shadow | enforce`; it is not in `ui_contracts.FLAGS`, so the GenUI hash is unchanged. If the requested mode is enforce and `genui_for(ws).enabled`, the effective mode is shadow unless a verified DP-1 receipt for the current release SHA covers both fixed 60-case runs (full manifest and narrowed grants). Missing/stale evidence always downgrades to shadow, including when the GenUI allowlist later becomes empty or broadens. This server-side check is re-evaluated on every config resolution; a rollout checklist alone is insufficient.
- **Rollout:** off → shadow on 267f7d90 (allowed before DP-1 because shadow returns exactly the off result, §8.2 and A13; requirement: zero would-deny on baseline turns, which is an observation on top of the deterministic legacy golden A1) → shadow on 332ed6e6 → enforce on 332ed6e6 (not a GenUI workspace; native surfaces) → enforce on 267f7d90 **only after** DP-1's two live runs (CF-1 §9) → wider.
- **GenUI allowlist preflight (correction 8):** a deploy is refused when `RAFII_GENUI_ENABLED=1` and `RAFII_GENUI_WORKSPACES` is empty, until R4 passes (CF-1 §9).
- **Ordinary-user evidence (correction 20; DP-8):** every R1–R3 gate receipt records read-only proof that 332ed6e6 has no `founderOps` marker (`billing.py` founder markers) and no Founder plan (PR #121), is not in `RAFII_GENUI_WORKSPACES` or any founder allowlist during the native runs (`genui_for(332ed6e6).enabled == false`), and that the editor and viewer runs use invited accounts that are not the founder account. Owner steps run as dfestival.office.
- **Library (LIB-D1..D5, approved canary-first):** `library_browse` is outside `LEGACY_BASELINE_V1`; under enforce a person picks a preset once before Rafii browses their Library. LIB-D1's general-release condition (an owner toggle, off by default, plus the privacy page update) is an R2 GA gate item, not a P0 contract change.

## 16. HTTP API (session-only; `require_session_token`, guard and Origin check; `repository.transaction` with requirement `read`; a person reads and writes only their own row)

`permissions.ACTION_CLASSES` gains explicit `agent_permissions_set: "read"`, `agent_permissions_revoke: "read"`, `agent_permissions_remind: "read"`, `agent_autopilot_enable: "read"`, `agent_workspace_ceiling: "owner"`, so nothing falls through to `classify()`'s default. Mode `off` → every route returns 404 `agent_permissions_unavailable`.

**`GET /api/workspaces/{w}/agent/permissions`**

```json
{"available": true, "mode": "shadow|enforce",
 "state": {"source": "legacy|explicit", "preset": "legacy|none|recommended|full|custom", "baseline": null, "epoch": 0,
           "spendConfirmation": "none|media|all", "decidedAt": null, "consentVersion": null, "needsChoice": true,
           "ended": false, "newSinceDecision": 0},
 "reminder": {"due": true, "nextAt": null},
 "role": {"role": "editor", "can_publish": false},
 "categories": [{"id": "create_edit", "mode": "assist|ask|null",
                 "effective": {"state": "on|asks|off|clipped|unavailable", "reasons": [{"code": "role", "message": "..."}]}}],
 "domains": [{"id": "library", "granted": true, "clippedBy": null}],
 "capabilities": [{"capabilityId": "tool.image_generate", "...": "public_catalogue entry",
                   "effective": {"outcome": "allow|confirm|approve|step_up|deny", "reason": "...", "required": "none|native|proposal|approval_step_up"}}],
 "presets": [{"id": "recommended", "version": 1, "scopes": {"category:read_analyze": "assist"}, "spendConfirmation": "all", "stepUp": false},
             {"id": "full", "version": 1, "scopes": {"category:execute_automations": "assist"}, "spendConfirmation": "none", "stepUp": true}],
 "autopilot": {"available": false, "policies": []},
 "pendingApprovals": 0,
 "consentVersion": "agent-permissions/1", "copyDigest": "<64 hex>", "catalogueDigest": "<64 hex>", "copy": {}}
```

**`PUT /api/workspaces/{w}/agent/permissions`**

```json
{"preset": "recommended|full|custom|none",
 "scopes": {"category:create_edit": "ask", "domain:notifications": false, "capability:tool.image_generate": "off"},
 "spendConfirmation": "all", "expectedEpoch": 0, "consentVersion": "agent-permissions/1", "copyDigest": "<64 hex>",
 "confirmed": true, "stepUp": true, "source": "onboarding|settings|reminder|chat_link", "idempotencyKey": "<16-120>"}
```

Rules:
- `scopes` only with `custom`; every `capability:` scope must be in `public_catalogue()` (consumer tenant, not native-only) and every `domain:` in `DATA_DOMAINS` minus `public`, else 400 `scope_invalid`.
- `expectedEpoch` must equal the current epoch (0 for legacy) → else 409 `agent_permissions_changed`. `copyDigest` must match → else 409 `agent_permissions_copy_stale`.
- **Widening** is `catalogue_diff(before, after).widened` non-empty or `spend_looser`; it needs `confirmed: true` → else 400 `confirmation_required`. Narrowing needs nothing.
- **Step-up (correction 21, DP-4):** when the target is `preset:'full'`, or the change sets `assist` on any `SENSITIVE_ASSIST` category (or a capability in one), the body must carry `stepUp: true` **and** `authz.require_step_up(window=300)` must pass → else 403 `step_up_required`. `stepUp: true` is only the client's declaration that it ran the re-auth flow for this change (so a page cannot silently upgrade with a token that happens to be fresh); the server's check is the authority. The receipt stores `step_up {method, at, aal}`; the state stores `step_up_at`.
- **Idempotency (correction 11):** `request_fingerprint = sha256(principal, canonical body without idempotencyKey)`. Within `(workspace_id, actor)`, same key + same fingerprint → the stored receipt; same key + different fingerprint → 409 `idempotency_conflict`. Another actor uses an independent key namespace and cannot retrieve the first actor's receipt. Task request and approval-decision keys keep their separately documented workspace-wide scope.
- A PUT on an `ended_at` row clears `ended_at`.
- Response: `{state, receipt: {id, kind, epochBefore, epochAfter, widened, invalidated, notRecallable, stepUp}, ...GET body}`.

**`POST …/agent/permissions/revoke`** `{"scopes": [...]}` or `{"all": true}`, plus `idempotencyKey`. Narrowing only: no `confirmed`, no step-up, no `expectedEpoch`. For a legacy person it materializes `LEGACY_EQUIVALENT` minus the revoked scopes (`preset: custom`, `baseline: legacy_v1`), so the Manager toolset never grows (CF-1 §13). Returns the receipt.

**`POST …/agent/permissions/reminder`** `{"action": "shown|not_now|dismissed"}` → `{reminder: {due:false, nextAt}}`. No request-key field is promised: update the single person/workspace reminder row only when its seven-day cadence is due, in the same transaction. Replays during the same cadence window do not increment `prompts`. Never touches grants.

**`GET …/agent/permissions/history?cursor=<receiptId>&limit=50`** → `{"items": [{id, at, kind, source, actorIsYou, presetBefore, presetAfter, changes: [{scope, from, to}], widened, invalidated, notRecallable}], "next": null}`. Own receipts only; owners and admins see everyone's through the workspace audit log.

**Approvals:** see §9 (one route plus the unchanged legacy body). **Autopilot** (shape frozen, built in P2 behind `RAFII_AGENT_AUTOPILOT_ENABLED`): `POST …/agent/permissions/autopilot {capabilityIds, constraints, limits, expiresAt, stepUp: true, idempotencyKey}` (step-up 300 s; ≤ 30 days; only `autopilot_eligible` capabilities whose category is already `assist`; constraint ids validated in the workspace → `scope_invalid`) and `POST …/agent/permissions/autopilot/{id}/revoke`.

## 17. Minimal UI contract (lane B; unchanged from the draft except where noted)

- Shared client: `web/src/lib/api/agent-permissions-types.ts` and `agent-permissions.ts` (`getAgentPermissions`, `putAgentPermissions`, `revokeAgentPermissions`, `remindAgentPermissions`, `getAgentPermissionHistory`). Approval decisions go through the task client (CF-3 §17), not a second approvals client. Error handling uses the §13 fixture only.
- **Settings → Rafii Agent → Permissions** at `/app/account/agent`, registered in nav, both route-manifest twins (byte-identical, `tests/test_site_agent.py:125`), breadcrumbs and a help doc. Sections: preset (Recommended, Full, Custom; a legacy person sees "Current (before permissions)"), six category rows with truthful clip notes, data domains (interactive under Custom), spending, autopilot ("Not available yet"), history, and "Turn off Rafii's access" (hold-to-confirm). Widening opens the confirm dialog and sends `confirmed: true`; Full and sensitive Assist run the existing re-auth flow first and send `stepUp: true`. Shadow mode shows "Preview: these choices are saved but not enforced yet."
- **Onboarding:** a non-blocking step after the WelcomeDialog when GET returns `available && state.needsChoice && reminder.due`; never mounted in AppGate; Recommended pre-selected; nothing saved until "Save"; "Not now" posts the reminder only. PR #144 edits `welcome-dialog.tsx` and `tours.ts` (coordinate; mount after #144 merges or as a reminder card).
- **Chat approval card:** native card outside the generated subtree (a bounded edit in `site-agent/answer.tsx`, GenUI lane F); Approve/Reject call `POST agent/approvals/{id}/decide`; a voice turn says "Confirm on screen."
- **Accessibility:** labelled radios/switches, 44 px targets, focus return, one status region, `StateMessage kind="permission"` for clipped rows, 320 px and long CJK labels, axe scenes through `jcb e2e`.

## 18. Lanes, tests and acceptance

| Lane A.2 (enforcement) | Lane B (store, API, UI) |
|---|---|
| `authz.py`, `provider_grants.py`; `tool_adapter.py` E1; `context.py` E2 (fields land in A.1's commit, X11); `site_agent/tools.py` E3; GenUI E4–E6 through lanes D/F with GA-A; `approvals.py`/`service.py` E7 seams via J; `automation_runs.py` E9 | 109 DDL handed to J (J creates the file, D-A18); `agent_permissions.py`, `permission_copy.json`; HTTP routes in `http.py` (J-owned seam); `SECURITY_KINDS`; `permissions.py` ACTION_CLASSES and STEP_UP_ACTIONS; `on_membership_ended` call sites; `account_deletion.py` erase call; revocation handlers H1, H2, H4, H5; all web files in §17 |

Frozen interfaces: B → A: `Grants`, `load`, `epochs`, `catalogue_diff`, `RevocationEvent`, `register_revocation_handler`, `LEGACY_EQUIVALENT`, `PRESETS`. A → B: `CapabilitySpec`, `SurfaceBinding`, `public_catalogue()`, `catalogue_digest()`, `reach()`, `decide()`, `Actor`, `Decision`, `REASON_CODES`, `decide_for_step`, `authz.IN_TOOL`. Merge order: A1 (CF-1) → B1 (109, store, GET/PUT/revoke/history/reminder, shadow only) → A2 (gates in shadow) → B2 (UI) → enforce on 332ed6e6 → enforce on 267f7d90 after DP-1.

**Acceptance (all remote: `jcb test`/CI; PG tests with real owner/editor/viewer roles and a second tenant, never asserting through a service-role bypass):**
- A1 Legacy golden (CF-1 §12 test 2): for no row, an ended row and `LEGACY_EQUIVALENT`, under `off`, `shadow` and `enforce`, every baseline capability on every surface (including `site_agent` and the five `context.*` entries) is not denied and has `required == legacy_confirmation`; explicit presets keep the ≥ fixture (CF-1 §12 test 3).
- A2 Revoke-from-legacy never adds a reachable capability or lowers a confirmation (correction 5).
- A3 Each preset writes exactly its rows; widening without `confirmed` → 400; stale epoch → 409; stale copy → 409; Full without `stepUp` → 403; Full with a stale sign-in → 403 `step_up_required`; sensitive Assist the same.
- A4 Idempotency: same key + same body replays; same key + other body → 409 `idempotency_conflict`.
- A5 `scope_invalid` for unknown, founder-tenant and native-only capability ids and foreign constraint ids.
- A6 Membership end on every revoke path (enumerated): rows kept, `ended_at` set, epoch bumped, handlers run; re-invite → `needsChoice` and no old grant effective; account deletion erases and completes.
- A7 **Provider disconnect between s1 and s2 blocks s2 with zero epoch change** (correction 3).
- A8 Mid-turn revoke raises `agent_permission_revoked` in `ctx.workspace()`.
- A9 Prompt-injection fixtures: instructions inside Library, comment, notification or web fixtures never change a decision, an approval target or a step target (PI-5 at plan and execution).
- A10 Ask flip: `confirmation.required` true for `campaign_link` under Ask; never false where the surface asked today (INV-10).
- A11 DDL behaviour on PostgreSQL: `tests/phase2/postgres_agent_os_ddl.py` (this PR) — forced RLS, browser roles denied, append-only history, RESTRICT on membership delete, erase guard.
- A12 GenUI: CI-fake G03 unchanged pre-merge; DP-1 live 60-case gate twice (full + narrowed) before enforce on any GenUI workspace.
- A13 Shadow is invisible: for a narrowed-grant person (Recommended with `create_edit=ask` and the `analytics` domain off) in shadow on a GenUI workspace, the GenUI manifest (public and server-only keys, including `actionTargets` and `permissionRevision`), every query result, the activate response with its `confirmation`, the execute receipt, E1–E3 tool results, the E10 tool lists, the E11 APP_STATE and the E7 proposal apply are byte-identical to `off` for the same requests, while `agent.authz.shadow` logs carry the would-deny and would-confirm values.
- A14 Grounded site agent: a viewer and an editor under legacy in enforce get today's record for every one of the 37 site-agent ids (CF-1 §5.1), and `site.automation_patch_propose` still only prepares a proposal.

## 19. Freeze checklist

- [x] X1: no approvals table in 109; one route and one digest (correction 4).
- [x] `authz_token` compared with `<>`; decide on every claim; epoch sum dropped (correction 3).
- [x] Resume rule identical to CF-3 (correction 2).
- [x] `widened` and `denied_now` from one catalogue diff; Manager expansion keyed on baseline and preset (correction 5).
- [x] INV-10 at E1/E6/E7 (correction 6).
- [x] Membership end via status + `ended_at` + RESTRICT; erase only in account deletion (correction 12).
- [x] Composite receipt keys; `scope_invalid` validation (correction 13).
- [x] Consent receipt fingerprint (correction 11).
- [x] One client-visible error table (correction 16).
- [x] `yes` only for legacy proposals (correction 17, DP-5).
- [x] PUT `stepUp` field; Full and sensitive Assist need a fresh sign-in (correction 21, DP-4).
- [x] Non-founder proof and GenUI allowlist preflight in the gates (corrections 8, 20).
- [x] Shadow returns exactly the off result at every enforcement point; only enforce narrows, denies or adds a confirmation; A13 (review of #160).
- [x] E3 resolves every site-agent id through `site_capability()`; E11's context capabilities are in the baseline; A1 is an equality golden (review of #160).
- [x] Observer exception for cancelled tasks and ended memberships (`observe` verdict, 108 guard) (review of #160).
- [ ] SD-1 (Recommended spend scope) — open; the frozen default is `all`.
- [ ] DP-6 copy and languages before B2 reaches general release (does not block the freeze).
