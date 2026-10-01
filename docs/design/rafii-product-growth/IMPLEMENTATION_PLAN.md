# RAFII Product Growth v2 — implementation plan

Working spec: `PRD.md` (v2.0). Decisions: `DECISIONS.md`. Live state per requirement: `STATUS.md`. This file is the
contract every slice works to: actual files, owners, dependency order and acceptance mapping. It is not a research
report; the five read-only maps it was built from are summarized in `evidence/G0-code-map.md`.

- Integration branch: `claude/rafii-product-growth-v2` (draft PR #87, base `fix/rafii-call-lifecycle-20260930` = production `dcb5bcdc`).
- Coordinator (one owner of shared contracts, migrations, lockfiles, billing hooks, metric dictionary, notification
  catalog, integration and release): this session.
- Slice workers branch from the integration branch, own only the paths listed for them, commit focused commits on
  `claude/rpg-<slice>`, and never push, merge, deploy, migrate a hosted database or call a paid/external provider.
  The coordinator merges one slice at a time, reruns affected tests and reviews before the next.

## 1. Shared conventions (all slices)

**Backend (Python, `src/postriff_phase2/`).**
- Routes: add the resource module to `growth_v2_routes.RESOURCES` (already reserved) and implement
  `handle(app, environ, start_response, hosted, token, method, parts)` in it. Public routes (signed webhooks,
  redirects) implement `public(app, environ, start_response, method, path)` and are listed in `growth_v2_routes.PUBLIC`.
  Never edit `hosted_app.py`; the dispatcher is wired once.
- Service attachment: lazy `ensure(hosted)` that sets `hosted.<name> = Service(hosted)` (see `growth/http.py`). Never
  edit `hosted.py` for attachment.
- Authority: every authenticated operation runs inside `hosted.repository.transaction(token, workspace_id)` →
  `(cur, row, principal)`; permission via `permissions.require(member, cls)` with the member from `hosted._membership(row)`
  (see `audience.py`). The path workspace id selects; it never grants. API tokens never reach these routes.
- Feature flag per slice, default off, read with `coworker.flags.enabled(NAME)`-style env check; when off the route
  answers `AlphaError(..., 404, code="feature_disabled")` (the web hides the feature on that code).
- Mutations take `idempotencyKey` (8–80 chars) and, for existing records, `expectedRevision`; replays return the
  existing result, conflicting reuse returns 409 `idempotency_conflict`, stale revision returns 409 `revision_conflict`.
  Responses return authoritative ids + read-back state.
- Errors: `AlphaError(message, status, code=...)` → body `{"error","code"}`; request id stays in `X-Request-ID`. Codes
  map to: `consent_required`, `unsupported_input`, `source_unavailable`, `insufficient_budget`, `approval_required`,
  `approval_expired`, `revision_conflict`, `retry_later`, `delivery_uncertain` (PRD R-ENG-02).
- Envelope additions where relevant (never replace an existing response shape): `definitionVersion`, `asOf`,
  `dataState` (`available|partial|unavailable|stale`), `coverage`, revision/evidence ids, job state, quote state.
- Lists: cursor pagination, default 25, max 50, deterministic order `(occurred_at|created_at DESC, id DESC)`, cursor =
  base64url JSON `[epoch, id]` (same as `audience.py`).
- Audit: `hosted.audit(cur, workspace_id, actor, kind, subject, meta)` — content-free (ids, enums, counts).
- Product events: `growth_events.emit(cur, workspace_id=, event=, entity_id=, revision=, user_id=, values=)` only;
  events must already be in `growth_events.TAXONOMY` (coordinator-owned; ask to add).
- Text never goes into URLs, analytics, audit meta or logs. Source excerpts are data, never instructions.
- Time: store UTC instants plus an IANA zone for civil scheduling; test DST gaps/overlaps.

**Database (`migrations/postriff/08x_*.sql`).** Additive, idempotent (`if not exists`), wrapped in `begin/commit`.
Workspace-owned tables: `workspace_id uuid not null references public.pr_workspaces(id) on delete cascade` (account
deletion cascades; no registry), forced RLS, `revoke all … from public, anon, authenticated`, `grant select … to
authenticated` + policy `tenant_read using (postriff_private.member(workspace_id))`, `grant all … to service_role` +
policy `trusted_write` (pattern: 047). Cross-record references are composite `(workspace_id, id)` foreign keys so a
record can never point at another workspace's row (add `unique (workspace_id, id)` to a referenced table when missing).
Indexes for `(workspace_id, occurred_at, id)`. Register the file with one `\ir` line in `tests/phase2/rls.sql` after
the 050 line. PostgreSQL tests: `tests/phase2/postgres_<slice>*.py` (auto-discovered), run with
`RAFII_PG_PORT=<your port> PYTHONPATH=src:tests .venv-growth/bin/python scripts/rafii_pg_private.py <stem>`.
Never apply anything to a hosted database.

**Web (`web/src/`).** API client per slice in `web/src/lib/growth-v2/<slice>.ts` built on
`web/src/lib/growth-v2/request.ts` (`createRequester`, `isFeatureDisabled`, `idempotencyKey`); hooks in
`web/src/lib/growth-v2/<slice>-hooks.ts` (TanStack Query, keys `['growth-v2', workspaceId, <slice>, …]`); types in
`web/src/lib/growth-v2/<slice>-types.ts`. Never edit `web/src/lib/api/client.ts`/`types.ts`. UI lives inside the
existing surfaces named per slice (Weekly, Inbox, Library, Growth/Analytics, Queue, agent panel) — no new top-level
navigation. Reuse `@/components/ui/*` and `@/components/rafii` (Surface, tokens); keyboard focus, visible labels,
`role="alert"` for errors, no success toast for a failed write, reduced motion respected, EN + zh-Hant strings via the
existing locale pattern. Pure logic gets `web/tests/<slice>.test.mjs` (`node --test`).

**Agent tools.** Typed tools go in `src/postriff_phase2/<slice>/agent_tools.py` using
`agent_runtime_v2.tool_adapter.register(contracts.ToolSpec(name, EFFECT, permission, description, voice=True), schema, label)`
(pattern: `coworker/agent_tools.py`). Reads are `READ`; saving drafts is `CREATE_DRAFT`; reversible edits are
`MUTATE_REVERSIBLE`; anything external is only ever `PREPARE_EXTERNAL` with `approval=True`. Voice and text identical.
The coordinator wires each module into `skill_registry.registered_tools()` at integration.

**Local resources.** This Mac is shared and under memory pressure: no `next build/dev`, no Playwright, no Docker, no
`npm install`/`npm ci`, no dev servers. Allowed: focused Python unit tests, focused disposable-PostgreSQL groups on
your own port, `node --test` on pure web modules (with `web/node_modules` symlinked read-only to the canonical
checkout's). Full builds, typecheck, lint and browser suites run in PR CI.

## 2. Slices, owners and contracts

| Slice | Requirements · AC | Owner | Migration · flag · PG port | Depends on |
|---|---|---|---|---|
| G0-PRICING | R-COM-01..04 · AC01–AC05 | coordinator (backend), W-PRICING-WEB (UI) | none · `POSTRIFF_PRICING_V2_ENABLED` etc. · 55871 | — |
| G0-METRICS | R-MET-01..03 · AC31–AC35 | coordinator | 086 if needed · — · 55871 | Founder P1 057 (proposed) |
| G1-CONTINUE | R-FWR-01 · AC06–AC07 | coordinator | 085 · `RAFII_FIRST_WEEK_ENABLED` · 55871 | `variant_import` |
| G1-WEEK | R-FWR-02/03 · AC08–AC10 | coordinator | 085 · `RAFII_FIRST_WEEK_ENABLED` | Weekly Operator, credit quotes |
| G1-INTAKE | R-FWR-04 · AC11–AC12 | W-INTAKE (`src/postriff_phase2/source_uploads/`) | 087 · `RAFII_SOURCE_UPLOADS_ENABLED` · 55887 | storage, durable job |
| G2-REL | R-REL-01/02 · AC13–AC15 | W-REL | 081 · `RAFII_RELATIONSHIPS_ENABLED` · 55881 | Inbox v1, result events (080) |
| G2-OUT | R-OUT-01..03 · AC16–AC19 | W-OUT | 080 · `RAFII_RESULTS_ENABLED` · 55882 | `results/signing.py`, `results/model.py` |
| G3-SER | R-SER-01/02 · AC20–AC21 | W-SER | 082 · `RAFII_SERIES_ENABLED` · 55883 | Evergreen, overlays |
| G3-VIS | R-VIS-01..03 · AC22–AC23 | W-VIS | 083 · `RAFII_VISUAL_PACK_ENABLED` · 55884 | creative plan, storage, Queue manifest |
| G4-LOOP | R-BRF-01/02, R-PROOF-01/02 · AC24–AC27 | W-LOOP | 084 · `RAFII_OPPORTUNITY_BRIEF_ENABLED`, `RAFII_PROOF_V2_ENABLED` · 55885 | results summary, pack exports (interfaces below) |
| G4-RELEASE | R-ENG, R-NFR, §15–§16 · AC28–AC30, AC36–AC40 | coordinator | — | all |

### Cross-slice interfaces (stable names; implement exactly)
- `results.service.period_summary(cur, workspace_id, start, end) -> dict` — `model.summarize` output per provenance plus
  `{"definition": ASSOCIATION_DEFINITION, "asOf", "dataState"}`; no text. Used by proof (G4-LOOP) and goals.
- `visual_pack.service.handoff_counts(cur, workspace_id, start, end) -> {"exportReady","downloaded","userConfirmedUsed","queued","verifiedPublished"}`.
- `relationships.service.due_followups(cur, workspace_id, now) -> [ {id, dueAt, timeZone, threadId|None} ]` for the detector.
- `first_week.service.week_scope(state, week_id) -> {"frozen": bool, "slots": [...], "scopeRevision": int}`.
- A slice whose dependency module is absent treats the data as `dataState="unavailable"` with a reason; it never
  substitutes zero or a demo value.

### G0-PRICING (coordinator; UI by W-PRICING-WEB after the API contract lands)
Merged: Tasks 1–4 (`feat/rafii-pricing-credits-v2`), Task 5 ported (`825e54b7`). Remaining:
1. Task 5 fixes (a known-failed preview attempt still consumes the preview — kept, decision for James, see D-008); fix the
   vacuous assertion; Radar quote/start refuse paid sources for Free before I/O; Growth AI for `managed_credits`
   goes through `CreditRequests`/`Ledger.reserve` (quote → reserve → settle at 300 credits/USD) instead of failing
   closed; designated base checks stay platform-funded only under the approved policy.
2. Task 6: `billingMode` (`free_preview|managed_credits|legacy_allowances`) in `usage_view`; `planTerms` filtered to
   public/checkout-enabled/current terms with catalog fields; subscription `priceVariantId` + effective amount;
   effective assigned Creator price; Free preview remaining; public read-only `GET /api/plans` built from the same
   catalog rows (single source for public pages, app and checkout).
3. Task 10: v2 pack listing policy stays disabled; contract test that a flag alone cannot sell a pack.
4. Task 11: variant/checkout/renewal attribution and platform-funded cost in existing telemetry.
5. W-PRICING-WEB (Tasks 7–9): public pricing/landing/plan cards/JSON-LD/terms/auth/CTA/help from `GET /api/plans`;
   billing UI branched on `billingMode`; work surfaces (writing-now, capture, ideas, attention, model catalog, tours,
   help) mode-aware; receipt explaining every remaining legacy hit.

### G0-METRICS (coordinator)
`metric_definitions.py`: versioned definitions (PRD §12) registered as `proposed_definition_not_activated`; pure
computations with the §15.2 golden payment fixtures; `growth.fleet` relabels status counts ("subscriptions by current
status") and computes cash-paid conversion/retention from `pr_credit_subscription_grants` (+ `pr_invoices` when the
Founder P1 057 table exists) with `dataState=partial`, reason `legacy_plan_invoices_not_recorded`. Reuse
`source_paid_conversion`; add `first_cash_paid_conversion` as the workspace-level event. A Control slice patch is
offered to the Founder owner; nothing financial is activated.

### G1-CONTINUE / G1-WEEK (coordinator)
- `variant_import`: a free, non-paid trusted command creating a canonical draft from consented user text (source +
  variant), idempotent per `(workspace, idempotency key)`; a different text under the same key conflicts.
- Continuation (web): consent dialog on the anonymous Post Doctor (original and/or edited text), sessionStorage record
  `rafii.continue.v1.<nonce>` (24 h expiry, text + source/version ids + qualitative result), opaque nonce only in
  `/auth/sign-up?next=/app/weekly?continue=<nonce>`; after auth confirm the workspace, import, then clear. Recovery
  states: expired, storage unavailable, wrong account, duplicate import, other workspace.
- First week: `first-week` resource: start/resume journey (checkpoint references only in `state.coworker.weekly`),
  purpose/audience questions only when Brand Brain lacks them, one accepted draft, deterministic 3-post/1-channel week
  (no connected channel required to plan or edit), item review, Queue approvals, receipts read back from Queue,
  frozen committed scope with versioned changes, per-slot cost state; paid drafting only with a credit quote
  (managed credits) or refused for Free (deterministic preview only).

### G1-INTAKE (W-INTAKE)
Signed direct upload to storage (pattern `video_uploads.py`), audio ≤10 min/30 MB, PDF ≤20 MB/100 pages/60,000
extracted characters (limits shown before upload); content sniffing; PDF text extraction with a bounded pure-Python
parser (new dependency recorded), scanned/no-text → `unsupported`; audio transcription only through a configured,
budgeted route (`RAFII_TRANSCRIPTION_ROUTE`, default unset → truthful `unsupported`), synthetic transcriber for tests
only; durable leased job with attempts/cancel/progress and an immutable result reference; transcript/text correction
before `source` + `approve_source`; raw upload retention class in `privacy.py`.

### G2-REL (W-REL)
`relationships` + `relationship_threads` + append-only `relationship_events` (transitions, snooze/close/reopen,
assignment), states `new|replied|waiting|follow_up_due|won|closed`, `won` requires a declared result id, member-only
assignment, thread refs scoped to the workspace (composite FK; add `unique(workspace_id,id)` to `pr_audience_threads`),
due follow-ups → detector → Attention (`relationship.follow_up_due`, never urgent) + catalog event, reply via existing
`draft_reply` → `reply_preview` → `approve_reply` (no new sender), unsupported channels shown as assisted links.

### G2-OUT (W-OUT)
Tables: result connections (encrypted current + previous secret with grace expiry, fingerprint, rate budget, health),
append-only result events (identity unique per `(workspace, connection, provider_event_id)`, provenance, type,
occurred/received, amount minor + currency, link/campaign association + definition, correction link), quarantine,
tracking links (server-created opaque slug, HTTPS public destination via `net_guard.public_https_url`, campaign
binding, daily aggregate clicks + likely-bot count, no IP/fingerprint). Public: `POST /api/results/webhook/{connectionId}`
(size cap → connection lookup → per-connection throttle → signature → parse → normalize → idempotent insert),
`GET /api/l/{slug}` (302, appends `rafii_ref=<slug>.<YYYYMMDD>`). Authenticated: declare/amend/reverse, list,
connection create/rotate/pause/remove/health, link create/disable/list. `scripts/results_test_producer.py` signs
documented test events. UI in Growth/Analytics.

### G3-SER (W-SER)
Series stored as a campaign of `kind:"series"` with a `series` body (audience question, goal, source refs, owner,
status, 2–6 episode plan) without touching `goal/audience/facts`; episodes with role/angle, claims, source version,
review/expiry date, draft/asset refs, lineage to the original (immutable); exact-duplicate refusal + similarity warning
(trigram, CJK-safe); expired/missing claim → `needs_fact_review` blocking release; angle accept/reject and
"do not repeat" stored as scoped, revocable overlays (new `strategy` memory type with a `seriesId` scope), read by the
next episode plan; Evergreen keeps working and can follow a series.

### G3-VIS (W-VIS)
Server-side Pillow renderer with a bundled OFL Noto Sans TC (license + sha256 in repo, under `src/postriff_phase2/`),
six 1080×1350 slides, deterministic layout, glyph coverage, measured wrapping (CJK-aware), safe areas, overflow →
offer shorter copy (never shrink indefinitely); PNG storage path; versioned pack + manifest (order, dimensions,
sha256, lineage, alt text, caption); edits invalidate approvals/exports; export zip; Queue handoff with ordered asset
ids + frozen manifest only where an exact provider/format supports it — and fix the publishers that silently drop
media beyond the first (refuse >1 image where unsupported); `export_ready → downloaded → user_confirmed_used` and the
existing `provider_accepted/verified` stay distinct; editor in the existing creative/Library surface.

### G4-LOOP (W-LOOP)
Brief composer (stored-only: trends weekly pool, listening, stored Radar scans; never paid I/O on GET), 0–3 items per
edition with source, times, coverage, relevance, angle, effort and one action; edition id + material digest; catalog
event with `audience:'actor'`, ≤1 opportunity digest per recipient per local day, existing quiet hours/mute/
unsubscribe; actions accept/dismiss/not_relevant with reason codes and outcome references. Proof revisions: a new
revision when late data changes material counts (prior kept), `asOf`, watermark, workspace timezone, definition
version, assisted exports separately, unresolved slots, outcomes by provenance, actual/unknown cost, next-step
proposal; strategy decisions accept/edit/reject/revoke (versioned, scoped, revocable) consumed by
`growth_loop.planning_context`; the week records `appliedDecisions`/`notApplied{reason}`.

## 3. Acceptance mapping (summary; evidence lives in STATUS.md)

AC01–AC05 G0-PRICING · AC06–AC07 G1-CONTINUE · AC08–AC10 G1-WEEK · AC11–AC12 G1-INTAKE · AC13–AC15 G2-REL ·
AC16–AC19 G2-OUT · AC20–AC21 G3-SER · AC22–AC23 G3-VIS · AC24–AC27 G4-LOOP · AC28 agent tools (all slices) ·
AC29–AC30 every migration + PostgreSQL group · AC31–AC35 G0-METRICS · AC36–AC38 G4-RELEASE security/a11y/limits ·
AC39 integrated journey · AC40 release receipts.

## 4. Integration order

1. Scaffolding + G0 fixes (coordinator) → push → CI.
2. Slices in parallel; merge order W-OUT, W-REL, W-INTAKE, W-SER, W-VIS, W-LOOP, W-PRICING-WEB, each followed by
   affected unit/PostgreSQL tests and a review; push after each merge.
3. G1 continuation/first week (coordinator) interleaved.
4. Whole-branch review, CI green, preview build, release preparation (`RELEASE.md`), authorization requests.
