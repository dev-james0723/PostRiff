# CF-1 — Capability registry (`rafii-agent-authz/1` §1), amended

**Status:** PROPOSED, amended; independent review and recorded validation required before freeze. Freezes as written once lane J records it in its ledger. Correction 6 (legacy confirmation on the surface binding) is folded in, which was the only condition the critic set for freezing CF-1.
**Base verified:** `origin/consumer-saas` `de4e5907` (PR #138 merged after `2af255fd`). Every file:line below was re-read at that SHA.
**Labels:** IMPLEMENTED = in code today. PROPOSED = defined here, not built. Paths are relative to `src/postriff_phase2/` unless they start with `migrations/`, `web/`, `tests/` or `docs/`.
**Behaviour change:** none. CF-1 is vocabulary, declarations and a read-only registry. Nothing is enforced until CF-2's gate runs in `enforce` mode; `shadow` only computes and logs (INV-11).
**Consumers:** CF-2 (decides with it), CF-3 (reads the engine fields), lane C/H web (reads the public catalogue).

---

## 1. What exists today (IMPLEMENTED, verified at `de4e5907`)

| Piece | Where | How CF-1 uses it |
|---|---|---|
| Process-wide registry `REGISTRY: dict[str, Tool]` filled at import; `catalogue()` | `agent_runtime_v2/tool_adapter.py` | Extended, not replaced. |
| `ToolSpec(name, effect, permission, description, idempotent, approval, voice, audit, tenant)`; validation in `__post_init__` | `agent_runtime_v2/contracts.py:46-69` | Built positionally at about 60 call sites, so every new field is a keyword field with a default, appended after `tenant`. |
| Effects; `FORBIDDEN_EFFECTS = (EXTERNAL_EFFECT, DESTRUCTIVE, SECRET)`; PREPARE_EXTERNAL needs `approval` | `contracts.py:18-21, 59-65` (`__post_init__`) | Unchanged. |
| The single tool gate | `tool_adapter.py:96-144`: scope `:102`, tenant `:104`, voice `:107`, role `:109` (skipped when `ctx.membership is None`), YouTube read-only turn `:111`, cancel before a non-READ effect `:119-120`, schema `:121` | CF-2 adds its gate after `:109`. |
| Role classes; `classify()` falls back to `"edit"` | `permissions.py:15-24, 86-89` | Hotfix HF-1 makes it fail closed (R0, separate lane). |
| Grounded site-agent catalogue: 37 dotted ids (`site_agent/tools.py:30-96` `CATALOG`); `tool_adapter.register_site_tools` (`:406-422`, names from `_SITE_NAMES` `:233`) adapts the 36 read/client tools into `REGISTRY` with the same executor; `automation.patch_propose` (`workspace_mutation`) is not adapted. The grounded agent (viewers, approvers, runtime off) calls `site_tools.run` with the dotted ids. | `site_agent/tools.py`; `agent_runtime_v2/tool_adapter.py` | A registry source with a frozen id rule (§5.1). |
| GenUI action/query bindings; manifest with server-only `actionTargets` | `ui_domain/__init__.py`; `ui_capabilities.py:42 (permission_revision), 91 (build_manifest), 168 (current)`; `ui_contracts.py:398-399` (`SERVER_ONLY_MANIFEST_KEYS`) | Bindings gain a server-only `capability` field; the public contract hash is unchanged. |
| GenUI first-pass gate in code: G03 ≥ 29/30 | `tests/agent_ui_acceptance/test_agent_ui_acceptance_release.py:158` | Superseded for enforcement by DP-1 (§9). |
| Skill lockfile digest hashes explicit keys only | `skill_registry.py` `tool_digest` | New ToolSpec fields must not enter it (INV-9). |

## 2. Invariants (binding on every lane)

- **INV-1 Narrow only.** `allowed = user rights ∩ workspace/resource rights ∩ agent consent ∩ provider grants ∩ capability policy`. No term ever widens another.
- **INV-2 Fail closed.** An unknown capability id is denied. In enforce mode a workspace-tenant tool with no membership is denied (today `tool_adapter.py:109` skips the role check when `ctx.membership is None`). No new hosted action may fall through to `classify()`'s `"edit"` default.
- **INV-3 No silent grants.** No migration inserts rows. A member with no row resolves to `LEGACY_BASELINE_V1`, which is exactly today's behaviour and never includes a capability added after the freeze (§12).
- **INV-4 Grants have no tool path.** Only session-authenticated HTTP handlers write `pr_agent_*` permission tables (CF-2 PI-3).
- **INV-5** `FORBIDDEN_EFFECTS` is unchanged. R3 is native-only in P0: Rafii may navigate or guide to it; the person does it on the native page (DP-5).
- **INV-6 GenUI stays frozen.** `ui_contracts.contract_manifest()` and its hash `c4e2c3ae…`, `public_action()`/`public_query()` and `web/tests/agent-ui-journeys/fixtures/d-catalog.json` are unchanged. The enforcement gate for GenUI workspaces is DP-1's live gate (§9).
- **INV-7 Founder tenant isolation is untouched.** `tenant='founder'` capabilities bypass consumer grants; `rafii_control` `Boundary.authorize` stays the authority.
- **INV-8 Truthful states.** Every denial carries a reason code and the native page where the person can change it. "Unavailable" (flag off, provider missing) is never shown as "off".
- **INV-9** New ToolSpec fields never enter `skill_registry.tool_digest`.
- **INV-10 Confirmation never drops (correction 6).** At every enforcement point (CF-2 E1, E6, E7) the effective confirmation is `required = max(surface.legacy_confirmation, decision.required)` in the order of `CONFIRMATIONS`. No mode (off, shadow, enforce) and no preset can lower the confirmation a surface asks for today.
- **INV-11 Shadow is invisible.** In `shadow` the gate computes `decide()` and logs what it would do; every value a person, a client or the model receives (manifests, query results, tool lists and results, confirmations, receipts, APP_STATE, `permission_revision`) is byte-identical to `off`. Only `enforce` may narrow, deny or add a confirmation (CF-2 §8.2). This is what makes shadow safe on a GenUI workspace before DP-1's live gate (§9).

## 3. Vocabulary (PROPOSED; appended to `agent_runtime_v2/contracts.py`)

```python
CATEGORIES = ("read_analyze", "navigate_interact", "create_edit", "manage_settings",
              "manage_connected_services", "execute_automations")
RISKS = ("R0", "R1", "R2", "R3")        # R0 read · R1 reversible internal · R2 externally visible / shared impact · R3 high-impact or irreversible
CONFIRMATIONS = ("none", "native", "proposal", "approval_step_up")      # ORDERED: max() picks the stricter
COSTS = ("free", "text_credits", "media_credits")    # text_credits: its own 'text_model' writer reservation; media_credits: 'image_generation'/'tool'
IDEMPOTENCY = ("read", "native_key", "receipt_tx", "none")   # how a replay is made safe (CF-3 §8)
RETRY_CLASSES = ("auto", "manual", "never")
EVIDENCE = ("trace", "audit", "receipt")
VERIFICATIONS = ("none", "reread", "provider_receipt")
COMPENSATIONS = ("none", "inverse", "manual", "irreversible")
CAPABILITY_KINDS = ("tool", "ui_action", "ui_query", "context", "native_only")
SURFACES = ("manager", "specialist", "site_agent", "commands_direct", "genui_action", "genui_query", "context")
DATA_DOMAINS = ("public", "web", "account", "screen", "content", "campaigns", "library", "memory_brand", "connections",
                "analytics", "growth_trends", "notifications", "usage_billing", "members", "agent_activity", "automations")
CONSENT_KEYS = ("memory_cloud", "research_web", "media_cloud", "connector_cloud", "growth", "radar",
                "voice_sample_route", "library_purpose")
AUTONOMY = ("ask", "assist")             # autopilot is never a grant level; it is a bounded policy (CF-2 §2)
CATALOGUE_GENERATION = 1                 # +1 whenever a capability is added or its policy widened
R3_REAUTH_SECONDS = 300                  # DP-5: agent-originated R3 needs a sign-in verified within 5 minutes

@dataclass(frozen=True)
class ProviderScope:
    provider: str                        # platform key as stored on the channel ('YouTube', 'Instagram', ...)
    scopes: tuple[str, ...]              # YouTube: youtube.model.has_scopes; others: subset check
    lane: str | None = None              # 'agentic' | 'standard' | None (YouTube authorizationLane)
    capability: str | None = None        # pr_channel_capabilities.capability that must not be 'Unsupported'

@dataclass(frozen=True)
class Limits:
    per_turn: int | None = None
    per_minute: int | None = None        # hosted.throttle(cur, key, limit, 60)
    per_day: int | None = None
    max_usd_micro: int | None = None     # refused before dispatch when the estimate exceeds it
```

**One registry for both contracts.** The draft authz contract (`retry`, `retry_budget`) and the draft task engine (`retry_class`, `max_attempts`, `idempotency`, `paid`, `background`, `inverse_capability_id`) each defined their own per-capability fields. CF-1 now owns all of them; CF-3 reads them and defines none.

## 4. New `ToolSpec` fields (PROPOSED)

All keyword fields appended after `tenant`; every existing positional construction keeps working.

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str; effect: str; permission: str; description: str
    idempotent: bool = True; approval: bool = False; voice: bool = True; audit: str | None = None; tenant: str = "workspace"
    # --- rafii-agent-authz/1 (CF-1) ---
    capability_id: str | None = None             # default f"tool.{name}"
    capability_version: int = 1                  # bump on any semantic change
    category: str | None = None                  # CATEGORIES; default derived
    data_grants: tuple[str, ...] | None = None   # DATA_DOMAINS; None = undeclared (CI lint fails for tenant 'workspace')
    consents: tuple[str, ...] = ()               # CONSENT_KEYS the executor ALREADY pre-checks (correction 22)
    risk: str | None = None                      # RISKS; default derived; "R3" refused in P0
    confirmation: str | None = None              # CONFIRMATIONS; default derived (policy floor, never the surface's)
    cost: str = "free"                           # COSTS
    provider_scopes: tuple[ProviderScope, ...] = ()
    limits: Limits = field(default_factory=Limits)
    timeout_seconds: float = 150.0               # = FunctionTool timeout today; CF-3 may only lower it per step
    idempotency: str | None = None               # IDEMPOTENCY; default derived
    retry_class: str | None = None               # RETRY_CLASSES; default derived
    max_attempts: int | None = None              # 1..5; default derived
    background_eligible: bool = False            # may a cron claim run it (P0: R0 READ only, correction 9)
    evidence: str | None = None
    verification: str | None = None
    compensation: str | None = None
    inverse: str | None = None                   # capability id that undoes it; only with compensation="inverse"
    autopilot_eligible: bool = False             # bounded autopilot policy may cover it (P2 runner)
    explicit_request: bool = False               # only the CURRENT human message can authorize it
    client_requirement: str | None = None        # page uiCapabilities token needed to render (never authority)
    since: int = 1                               # CATALOGUE_GENERATION when added or widened

    def policy(self) -> "CapabilitySpec": ...    # = capability_registry.from_tool(self)
```

**Default derivation, frozen as `contracts.derive_policy(spec)`:**

| Field | READ | CREATE_DRAFT / MUTATE_REVERSIBLE | PREPARE_EXTERNAL, or `approval=True` |
|---|---|---|---|
| category | `read_analyze` | `create_edit` | `execute_automations` |
| risk | R0 | R1 | R2 |
| confirmation (policy floor) | none | none | proposal |
| idempotency | `read` | `none` unless the module declares `native_key`/`receipt_tx` | `native_key` (the proposal digest) |
| retry_class / max_attempts | `auto`/3 if `idempotent`, else `never`/1 | `auto`/3 for `native_key`/`receipt_tx` and `cost="free"`; `manual`/1 if paid; `never`/1 if `idempotency="none"` | `manual`/1 |
| background_eligible | False (opt in per tool) | False | False |
| evidence | trace | audit | audit |
| verification | none | reread | reread |
| compensation | none | manual (truthful: no inverse exists today) | manual |

`paid` (used by CF-3) is derived: `cost != "free"`.

**`__post_init__` rejects only invalid values or impossible combinations:** an unknown enum value; `risk == "R3"`; `risk == "R2"` with `confirmation == "none"`; `inverse` without `compensation == "inverse"`; `autopilot_eligible` outside R1/R2; `background_eligible` with `risk != "R0"` or `effect != READ` (correction 9); `idempotency == "none"` with `retry_class != "never"`. Completeness (`data_grants` declared) is a CI lint, not an import error, because `domain_tools.ensure_registered` swallows extension errors and tools would vanish silently.

`public()` gains `capabilityId`, `capabilityVersion`, `category`, `risk`, `confirmation`, `cost`, `dataGrants`. None of these enter `tool_digest` (INV-9).

## 5. `agent_runtime_v2/capability_registry.py` (PROPOSED, lane A.1)

```python
@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str; version: int; kind: str            # CAPABILITY_KINDS
    name: str; label: str                                  # tool name | actionId | query name | context key | route id
    category: str; risk: str; confirmation: str            # confirmation = POLICY floor; surface confirmation lives on SurfaceBinding
    permission: str; tenant: str; effect: str; approval: bool
    cost: str; paid: bool; data_grants: tuple; consents: tuple; provider_scopes: tuple; limits: Limits
    timeout_seconds: float; idempotency: str; retry_class: str; max_attempts: int; background_eligible: bool
    evidence: str; verification: str; compensation: str; inverse: str | None
    autopilot_eligible: bool; explicit_request: bool; client_requirement: str | None
    since: int; route_id: str | None; feature_flag: str | None; reauth_seconds: int | None

@dataclass(frozen=True)
class SurfaceBinding:                                       # correction 6: confirmation is a property of the SURFACE
    surface: str                                            # SURFACES
    capability_id: str
    legacy_confirmation: str                                # what today's code asks on THIS surface (CONFIRMATIONS)
    binding_ref: str                                        # tool name, actionId or query name on that surface

def ensure() -> dict[str, CapabilitySpec]        # lazily from tool_adapter.REGISTRY + site_tools.CATALOG + ui_domain.ACTIONS/QUERIES + CONTEXT + NATIVE_ONLY
def site_capability(tool_id: str) -> str          # the frozen id rule for the grounded site agent's dotted ids (§5.1)
def get(capability_id) -> CapabilitySpec | None
def for_tool(name) -> CapabilitySpec
def for_action(binding) -> CapabilitySpec
def for_query(binding) -> CapabilitySpec
def surface(surface: str, binding_ref: str) -> SurfaceBinding   # the only source of legacy_confirmation
def reach(surface: str, grants) -> frozenset[str]               # capability ids visible to that agent scope (§13)
def public_catalogue() -> list[dict]                            # §11
def catalogue_digest() -> str                                   # sha256(canonical sorted public entries)
def lint() -> list[str]                                         # §14
```

The registry is built lazily (tests reset `REGISTRY`), cached by the registered name sets.

### 5.1 Site-agent ids (frozen rule)

The grounded site agent is the only surface viewers and approvers reach (`service.py:161-162`), so every entry of its catalogue must have a capability; under INV-2 an unknown id would be denied in enforce. `site_capability(tool_id)` is:

- `"tool." + n`, where `n = tool_id.replace(".", "_")`, when `register_site_tools` registered `n` for this id (the same `_site_executor(tool_id)`). One capability is then bound on two surfaces, `manager`/`specialist` and `site_agent`, each with its own `legacy_confirmation`, and one revoke covers both. At `de4e5907` that is 36 of the 37 ids, and `_SITE_NAMES[id] == n` holds for every one of them.
- `"site." + n` otherwise. At `de4e5907` that is only `automation.patch_propose` → `site.automation_patch_propose` (§7).

`ensure()` adds a `CapabilitySpec` for each `site.` id, with the `data_grants`, risk and confirmation from §7, and a `SurfaceBinding(surface="site_agent", binding_ref=<dotted id>)` for every one of the 37 ids. CF-2 E3 looks ids up only through `site_capability()`.

## 6. Surface bindings and legacy confirmation (correction 6)

The draft stored `legacy_confirmation` on `CapabilitySpec`. The same capability needs different confirmations on different surfaces: GenUI's `draft_edit` action has `requires_confirmation` (native dialog today), while the Manager's `draft_edit` tool runs with none. Under a per-capability value the GenUI edit would have been applied without today's dialog. The value therefore moves to `SurfaceBinding`:

| Surface | `legacy_confirmation` today |
|---|---|
| `manager`, `specialist`, `commands_direct` (model tool calls through `tool_adapter.execute`) | `proposal` when `ToolSpec.approval`, else `none` |
| `site_agent` (grounded agent, `site_agent/tools.py`; ids through `site_capability()`, §5.1) | `proposal` for `site.automation_patch_propose` and the schedule proposals, else `none` |
| `genui_action` | `native` when the binding has `requires_confirmation`; `proposal` when `prepare_only`; else `none` |
| `genui_query`, `context` | `none` |

INV-10 applies everywhere: `required = max(surface(...).legacy_confirmation, decision.required)`.

## 7. Classification of existing tools (PROPOSED overrides)

Lane A.1 applies these as keyword arguments in each registering module. Unlisted rows take the §4 defaults plus the `data_grants` shown. Each `cost` value is confirmed by locating a `ledger.reserve(` call in the executor (`agent_runtime_v2/creative.py:388` image generation; `ideas.py:1463` writer run); a tool without its own reservation is `free`. A site-agent id takes the row of its capability (§5.1): the 36 adapted ids are the `tool.*` rows below under their underscore names (`help_search`, `brand_summary`, `ui_guide`, ...); the one site-only id has its own row.

| Tools | category | risk | cost | data_grants | other |
|---|---|---|---|---|---|
| `help_search`, `help_get`, `route_describe`, `skills_list` | read_analyze | R0 | free | `("public",)` | available under preset `none`; `background_eligible` |
| `ui_navigate`, `ui_show_help` | navigate_interact | R0 | free | `("public",)` | — |
| `ui_guide` | navigate_interact | R0 | free | `("public",)` | `client_requirement="guide"` |
| `ui_voice` (MUTATE_REVERSIBLE override) | navigate_interact | R1 | free | `("account",)` | `client_requirement="voice"` |
| `task_plan`, `task_update`, `pending_approvals` | read_analyze | R0 | free | `("agent_activity",)` | — |
| `proposal_apply` | execute_automations | R2 | free | `("content","automations")` | confirmation `proposal` |
| `site.automation_patch_propose` (grounded site agent only; `workspace_mutation`, requirement `edit`) | execute_automations | R2 | free | `("automations",)` | confirmation `proposal`; `legacy_confirmation` `proposal` on `site_agent`; nothing changes until a person applies it |
| `schedule_propose` | execute_automations | R2 | free | `("content","connections")` | `idempotency="native_key"`; `autopilot_eligible` |
| `automation_change_propose` | execute_automations | R2 | free | `("automations",)` | MUTATE_REVERSIBLE + approval ⇒ R2 |
| `draft_create`, `draft_rewrite` | create_edit | R1 | text_credits | `("content","memory_brand")` | `idempotency="native_key"` (writing-run key) |
| `draft_edit` | create_edit | R1 | free | `("content",)` | compensation `manual` until the restore inverse exists (CF-3 §13) |
| `campaign_link` / `campaign_unlink` | create_edit | R1 | free | `("campaigns","content")` | `idempotency="receipt_tx"`; compensation `inverse`, each names the other |
| `image_generate`, `image_edit`, `image_variant` | create_edit | R1 | media_credits | `("content",)` | `consents=("media_cloud",)` where the executor pre-checks it |
| `image_analyze` | read_analyze | R0 | free | `("content",)` | `consents=("media_cloud",)` |
| `image_list` | read_analyze | R0 | free | `("content",)` | — |
| `memory_context`, `memory_summary`, `voice_check`, `overlay_context` | read_analyze | R0 | free | `("memory_brand",)` | `consents=("memory_cloud",)` only on executors that already check memory egress |
| `brand_summary`, `voice_profile` | read_analyze | R0 | free | `("memory_brand",)` | **gated after HF-1** (correction 22): `site_agent/reads.py:60-97` has no egress check today. HF-1 adds it; only then does the spec declare `consents=("memory_cloud",)`. The registry never claims enforcement that does not exist. |
| `web_research`, `research_search`, `research_fetch`, `source_normalize` | read_analyze | R0 | free | `("web",)` | `consents=("research_web",)` where the executor checks `research.allowed` |
| `weather_now` | read_analyze | R0 | free | `("web",)` | — |
| `library_search`, `library_read` | read_analyze | R0 | free | `("library",)` | per-source cloud consent stays in the executor |
| `library_browse` (D1, PR #152) | read_analyze | R0 | free | `("library",)` | `since=2` ⇒ **not** in `LEGACY_BASELINE_V1` (LIB-D5b, decided) |
| `channels_capabilities` | read_analyze | R0 | free | `("connections",)` | — |
| queue, job, draft, calendar, reviews, publishing, content, entity and workspace reads | read_analyze | R0 | free | `("content",)` | — |
| `automation_list`, `automation_get`, `automation_explain` | read_analyze | R0 | free | `("automations",)` | — |
| `campaign_list`, `campaign_get`, `campaign_items`, `campaign_membership`, `relationships`, `record_attribution` | read_analyze | R0 | free | `("campaigns","content")` | — |
| `attention_summary`, `attention_summary_v2` | read_analyze | R0 | free | `("content",)` | — |
| `member_activity` | read_analyze | R0 | free | `("members",)` | — |
| `notification_list` | read_analyze | R0 | free | `("notifications",)` | output wrapped as untrusted (HF-1) |
| `entitlements_summary` | read_analyze | R0 | free | `("usage_billing",)` | — |
| `privacy_egress_state`, `models_summary` | read_analyze | R0 | free | `("account",)` | — |
| `weekly_plan_get`, `strategy_context`, `creative_plan` | read_analyze | R0 | free | `("content",)` | — |
| `weekly_plan_prepare` | create_edit | R1 | text_credits | `("content",)` | — |
| `engagement_triage` | read_analyze | R0 | free | `("content","connections")` | — |
| `engagement_draft_create`, `source_campaign_create` | create_edit | R1 | free | `("content",)` | — |
| `trend_*` reads (16) | read_analyze | R0 | free | `("growth_trends",)` | — |
| `trend_opportunity_accept`, `trend_lab_check` | create_edit | R1 | free | `("growth_trends",)` | — |
| `trend_watch_create` / `trend_watch_disable` | create_edit | R1 | free | `("growth_trends",)` | inverse pair |
| `youtube_plan_context`, `youtube_recommendations` | read_analyze | R0 | free | `("content","connections")` | `explicit_request=True` |
| `youtube_plan_prepare` | create_edit | R1 | free | `("content","connections")` | `explicit_request=True` |
| `youtube_analytics_summary` | read_analyze | R0 | free | `("analytics","connections")` | `explicit_request=True`; `provider_scopes=(ProviderScope("YouTube",("read","analytics"),lane="agentic"),)` |
| `founder_*` and `rafii_control/intelligence.py` specs | defaults | — | — | `()` allowed | tenant `founder`: grants bypassed (INV-7) |

## 8. GenUI bindings on the same registry

`ui_domain` is owned by lane D; these edits are server-only, so the public shapes and the contract hash do not change. `ActionBinding` and `QueryBinding` gain `capability: str | None = None`; `ui_domain.action(...)`/`query(...)` gain `capability=None, category=None, risk=None, cost="free", data_grants=None`. If `binding.tool` is set the capability is that tool's id (registration asserts effect and tenant agree, as `tool_ok` does in `ui_capabilities.py`); otherwise it is `ui.action.<action_id>` / `ui.query.<name>`. Domains follow the journey: J01/J02 content, J03 library, J04 memory_brand, J05 campaigns, J06 analytics, J07 web, J08 `("automations","connections")`, J09 founder tenant.

| actionId | capability | category | risk | legacy confirmation on `genui_action` | cost |
|---|---|---|---|---|---|
| `draft_edit` | `tool.draft_edit` | create_edit | R1 | native | free |
| `schedule_prepare` | `tool.schedule_propose` | execute_automations | R2 | proposal | free |
| `automation_change_prepare` | `tool.automation_change_propose` | execute_automations | R2 | proposal | free |
| `campaign_link`, `campaign_unlink` | `tool.campaign_link`, `tool.campaign_unlink` | create_edit | R1 | none | free |
| `campaign_create`, `campaign_update` | `ui.action.*` | create_edit | R1 | native | free |
| `library_use_as_source`, `research_save_sources`, `voice_samples_import`, `voice_profile_analyze_local` | `ui.action.*` | create_edit | R1 | native | free |
| `voice_sample_select`, `voice_sample_exclude` | `ui.action.*` | create_edit | R1 | none | free |
| `voice_sample_grant`, `voice_profile_approve`, `preference_decide` (owner) | `ui.action.*` | manage_settings | **R2** with native confirmation (DP-5, decided) | native | free |
| `voice_profile_analyze_ai` (owner, two-phase) | `ui.action.voice_profile_analyze_ai` | create_edit | R1 | native | text_credits |

Manifest effect (CF-2 E4): `build_manifest`/`current` keep a binding only when `authz.gate(...)` is not `deny`, which can happen only in `enforce` (INV-11); `actionTargets[id]` gains server-only `capabilityId`, `capabilityVersion`, `risk`; `permission_revision(member, grants=None)` becomes `sha256(role, summary, grants.token())` only when the permissions mode is `enforce`. In `off` and `shadow` the manifest, including `permissionRevision` and the `revised` flag `current()` derives from it, is byte-identical to today's. Page `uiCapabilities` stays a rendering claim matched against `client_requirement`; it is never an input to `decide()`.

## 9. GenUI gate before enforcement (DP-1, decided 2026-10-09; corrections 7 and 8)

- The release gate is a **fixed 60-case live corpus with ≥ 59/60 first-pass valid (98.3 %)**. The 60 cases and the denominator are fixed in the corpus file before any measurement and never changed afterwards. The coded G03 (≥ 29/30 on 30 cases, `test_agent_ui_acceptance_release.py:158`) stays as the pre-merge CI check only (the CI-fake provider); it is not the release gate.
- **Enforce mode may not be enabled on any workspace where `genui_for(ws).enabled` is true** until that live gate passes on the release SHA **twice**: once with the full manifest and once with a narrowed-grant fixture (Recommended preset, `create_edit=ask`, `analytics` domain off). Both receipts are recorded in J's ledger. The canary 267f7d90 therefore moves shadow → enforce only after those two runs.
- **Fail-closed GenUI allowlist (correction 8).** `config.py:146-154` treats an empty `RAFII_GENUI_WORKSPACES` as every workspace. J adds, before any R1 deploy: (a) a deploy preflight that reads the effective configuration and fails when `RAFII_GENUI_ENABLED=1` and the allowlist is empty, until R4 (GenUI for ordinary users) passes; (b) a CI unit test on `RuntimeConfig` asserting the same rule for the configuration fixtures. A GA-A amendment requiring an explicit `*` for "all workspaces" is the cleaner end state and is GA-A's choice (a config change, not a prompt change, so the contract hash is unchanged). The new fail-closed allowlists (`RAFII_AGENT_PERMISSIONS_WORKSPACES`, `RAFII_TASK_ENGINE_WORKSPACES`) already treat empty as none.
- Every R1–R3 gate receipt records `genui_for("332ed6e6…").enabled == false` during the native runs (correction 20, CF-2 §15).

## 10. Context and native-only entries (static, in `capability_registry`)

`CONTEXT_CAPABILITIES` (kind `context`, R0, read_analyze), each gated before it enters APP_STATE (`service.py:604` `_assemble`): `context.page_summary` → `("public",)`, `context.screen_outline` → `("screen",)`, `context.memory_layers` → `("memory_brand",)`, `context.attention` → `("content",)`, `context.connections` → `("connections",)`.

`NATIVE_ONLY` (kind `native_only`, R3, confirmation `approval_step_up`, no executor, `reauth_seconds = R3_REAUTH_SECONDS = 300`). Rafii may only navigate or guide to `route_id`; every `route_id` must exist in `web/src/lib/site-agent/route-manifest.json` (lint): `connections.connect`, `connections.disconnect` → `channels`; `consent.memory_egress`, `consent.media_egress` → `memory`; `consent.research_egress` → `privacy`; `consent.connector_egress` → `api`; `billing.checkout` → `billing`; `members.manage` → `members`; `security.sessions_mfa` → `profile`; `security.api_tokens` → `api`; `account.delete` → `privacy`; `publish.approve` → `queue`; `automations.auto_publish_authority` → `automations`; `library.delete` → `library`.

**R3 re-authentication (DP-5).** When Rafii hands the person to an R3 route (`ui_navigate`/`ui_guide`), the navigation carries `{reauth: "required", maxAgeSeconds: 300}` and the native action reached through that handoff calls `authz.require_step_up(window=300)` (CF-2 §10). The server issues a single-use handoff nonce bound to principal, workspace, route/action and expiry, stores the pending handoff server-side, and the native endpoint consumes it only after a verified sign-in within 300 seconds. A pending Rafii handoff remains subject to this check if a client omits or changes its marker; a bare client flag is not evidence. Ordinary native actions with no pending Rafii handoff retain today's rule. Whether the 5-minute rule should also apply to native R3 actions not reached through Rafii is DECISIONS-NEEDED R3-1.

## 11. Public catalogue (read by the permissions UI)

`public_catalogue()` returns one entry per consumer-tenant capability; no schemas, no executors:

```json
{"capabilityId":"tool.image_generate","version":1,"kind":"tool","category":"create_edit","risk":"R1",
 "confirmation":"none","cost":"media_credits","dataGrants":["content"],"consents":["media_cloud"],
 "providerScopes":[],"requirement":"edit","surfaces":["manager","specialist","genui_action"],"nativeOnly":false,
 "routeId":null,"reauthSeconds":null,"baseline":true,"since":1,"titleKey":"capabilities.tool.image_generate"}
```

`surfaces` lists where the capability can be reached; the per-surface confirmation is computed with INV-10. Titles and summaries come from the server-authored `agent_runtime_v2/permission_copy.json` (CF-2 §2.4); the fallback is `Tool.label`.

## 12. `LEGACY_BASELINE_V1` and the golden tests

The baseline is a frozen `frozenset` of capability ids, generated once at the freeze commit into `tests/fixtures/agent_permissions/legacy_baseline_v1.json`. It is **every consumer-tenant capability with `since == 1`, of every kind except `native_only`**. Today that is:
- every tool reachable through `sdk_tools` (`MANAGER_TOOLS` in `manager.py`, every `SPECIALISTS[*]["tools"]` in `specialists.py`, the `EXTRA_SCOPES` filled by the coworker, trends and YouTube extensions);
- the grounded site agent's whole `site_tools.CATALOG` (37 ids), under the ids `site_capability()` gives them (§5.1), including `site.automation_patch_propose`;
- all 17 GenUI actions and 45 GenUI queries;
- all five `CONTEXT_CAPABILITIES` (§10): `context.page_summary`, `context.screen_outline`, `context.memory_layers`, `context.attention`, `context.connections`. E11 gates each APP_STATE section by one of them, so leaving them out would strip every existing user's page context in enforce.

`native_only` entries are not in it, because `decide()` answers them (navigate-only) before the baseline check. Founder-tenant capabilities bypass grants (INV-7). Anything with `since > 1` (for example `library_browse`) is never in it. Because the fixture is generated from the registry rather than hand-listed, a kind cannot be forgotten; test 1 also asserts the count per kind.

Golden tests (all remote, `jcb test`/CI):
1. The registry at the freeze equals the fixture (no capability vanishes or appears), and the fixture holds every kind above: 17 actions, 45 queries, 5 context entries, the 37 site-agent ids, and every `sdk_tools` tool.
2. **Legacy is exactly today (DP-3/DP-4; equality, not ≥).** For each legacy form (no row, an ended row, and `LEGACY_EQUIVALENT` before any revoke) and under `off`, `shadow` and `enforce`, `authz.gate` for every baseline capability on every surface it is bound to (`manager`, `specialist`, `commands_direct`, `site_agent`, `genui_action`, `genui_query`, `context`) returns `outcome != "deny"` and `required == legacy_confirmation`. It returns `outcome == "allow"` when the actor carries the evidence that surface collects today: none when the legacy confirmation is `none`, the consumed activation for `native`, the applied proposal for `proposal`. The fixture member is an owner with every declared workspace consent on, every declared provider scope connected, and request text that satisfies `explicit_request`. For an editor and a viewer the only difference allowed is `deny/role`, exactly where today's `member.allows(cap.permission)` refuses.
3. **Explicit presets never lower a surface (correction 6).** Under `none`, `recommended`, `full` and a narrowed `custom`, for every tool on every surface it is reachable from and for all 17 GenUI actions, the effective confirmation is ≥ the surface's `legacy_confirmation`. The fixture stores the expected value per (surface, binding, preset). Only these explicit presets use ≥; legacy uses test 2's equality.
4. **Revoke-from-legacy never widens (correction 5).** For every single-scope revoke applied to a legacy person, `reach()` over every surface gains no capability, no confirmation is lowered, and every baseline capability outside the revoked scope still passes test 2.

## 13. Agent reach and the Manager expansion (correction 5)

`reach(surface, grants)` is the set of capability ids an agent scope may see:
- `manager` = `MANAGER_TOOLS` today, plus `MANAGER_EXPANSION_V1 = {tool.campaign_link, tool.campaign_unlink, tool.draft_edit}` **only when** `grants.source == "explicit"`, `grants.baseline is None` and `grants.preset in ("recommended", "full", "custom")`, which only a confirmed PUT can set (CF-2 §16).
- `LEGACY_EQUIVALENT` (what a legacy person's first revoke materializes) keeps `baseline="legacy_v1"`, so it keeps exactly today's Manager toolset. The draft keyed the expansion on `source == "explicit"` alone, which let a narrowing revoke silently add three Manager tools that then ran under `create_edit=assist`.
- Specialists, site agent and GenUI reach are today's sets, filtered by `decide() != deny` (CF-2 E10).

`reach()` is part of the catalogue diff that computes `widened` and `denied_now` (CF-2 §5). `reach(site_agent, ...)` is the 37 ids of §5.1.

## 14. Lint and CI (lane A.1; remote only)

`capability_registry.lint()` and `tests/test_agent_capability_registry.py` assert: every workspace-tenant tool declares `data_grants`; the expected tool count holds; every inverse pair and native `route_id` exists; binding/tool agreement; every `site_tools.CATALOG` id maps through `site_capability()` to exactly one registered capability, and an adapted id's tool runs `_site_executor(id)`; every non-READ capability declares `idempotency` and `retry_class`; `background_eligible` only on R0 READ; no capability's executor imports `agent_permissions` write functions (PI-3); `consents` are declared only where the executor pre-checks them (a static list of verified call sites); `tool_digest` and the GenUI contract hash are unchanged.

## 15. Ownership and merge order

Lane **A.1** owns `contracts.py` (vocabulary, fields, `derive_policy`), the new `capability_registry.py`, the overrides in the registering modules, and the baseline fixture. It rebases after D1 (#152: `library_browse.py`, `config.py`, `manager.py`, `domain_tools.py`) and C3 (`ui_presenter.py`, `ui_projection.py`) land; GenUI-owned edits (`ui_domain/__init__.py` fields) go through lanes D/F with GA-A as in the draft. Merge order: A1 (this contract, no behaviour change) → CF-2 B1 → A2 gates in shadow.

## 16. Freeze checklist

- [x] Legacy confirmation on the surface binding; INV-10 (correction 6).
- [x] Engine fields owned here, not in CF-3 (one registry).
- [x] `brand_summary`/`voice_profile` text corrected (correction 22).
- [x] Manager expansion keyed on `baseline IS NULL AND preset IN (...)` (correction 5).
- [x] DP-1 gate wording, fail-closed GenUI preflight (corrections 7, 8).
- [x] `library_browse` outside the baseline (LIB-D5b, decided).
- [x] Shadow is invisible (INV-11); the manifest revision changes only in enforce (review of #160).
- [x] The baseline covers every kind, including `context.*` and the grounded site agent's catalogue (frozen `site_capability()` rule); the legacy golden test asserts equality (review of #160).
- [ ] J records the freeze in its ledger and copies the frozen sections into `A-DECISIONS` as one amendment.
