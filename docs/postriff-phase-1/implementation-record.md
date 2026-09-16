# PostRiff founder-alpha implementation record

Date: 2026-09-14. Execution: local founder alpha, complete within the explicitly authorized fixture scope. Full research and real-agent release gates remain unmet.

## Authorization and research state

The latest user instruction explicitly overrides the five-interview prerequisite for this limited private prototype. Use the approved founder summary as provisional design input. Phase 0 remains incomplete; no customer validation or market demand is claimed. P02–P05 stay pending, with interviews to resume after the prototype is ready for testing.

## Scope and boundaries

Four onboarding paths; provisional editable voice; reviewed source facts; neutral core skill templates with isolated private instances; fixture draft and independently adapted variant; explicit preference decisions; durable return state; save and portable export. Existing Studio and original personal skills remain private and unchanged.

The alpha has a separate frontend entry/build, loopback server and SQLite store. No legacy customer/profile/connection data is loaded into its bundle or API. Native agent routes are not enabled; their qualification is reported separately. No deployment, billing, managed generation, social connection, scheduling/publication, outreach or Phase 2.

## Implementation and evidence

New code is scoped under `src/postriff_alpha`, `studio/web/src/founder`, `studio/web/alpha`, an alpha-only Vite configuration and launcher. Baseline hashes of existing source and original personal skill files are in `evidence/baseline.json`. This installed source copy has no Git metadata, so unchanged baseline hashes and an explicit file inventory provide the review boundary. Final results are in [acceptance results](acceptance-results.md) and [the receipt](phase-1-receipt.md).

## R19 and R20 steering during implementation

The in-thread handoff from James adds experienced-AI and new-to-AI onboarding, distinct user-reported relationship and runtime states, scoped portable profile-builder handoff, field-level evidence/privacy review and expanded Personal Voice Package export. Incorporate these into the existing alpha without discarding the completed source/draft/preferences/store slice. The current source hashes are in `evidence/agent-aware-provenance.json`.

Runtime execution remains limited to the user-authorized deterministic fixture. CLI detection/version inspection, preparation, authentication, source access, execution and import are reported separately. No external-agent job or provider usage is inferred from AI relationship answers. The original five-interview gate remains incomplete.

## R21 account boundary

Added the confirmed O0 Google, Apple, Microsoft, email, phone and existing-account surface through a provider-neutral AuthGateway. Only the deterministic local verified-user adapter is implemented. Stable users, workspaces, owner memberships, retry IDs, credential hashes and audit events have separate SQLite records. Account fields never become brand facts. Callback replay is transactional and idempotent; no trial exists. Anonymous samples are now fixed fictional, read-only, memory-only views and cannot accept private imports. The earlier editable sample screenshots are historical and superseded by the R21 browser evidence. No real OAuth, email/SMS, Supabase, provider credential, or Vercel operation occurs.

## R22 You and local profile artwork

The confirmed in-thread addition replaces the lower utility settings destination with You and retains all six work destinations. `YouProfile.tsx` and `you.css` add the five-section hierarchy, editable identity sentence, approved-field constellation/list, exact statement drawer, keyboard review routing, skill/learning summary, voice revision comparison/restore, and distinct fixture usage/account/privacy views. Server-derived graph nodes reference only approved active fields; missing categories remain explicitly optional. There are no psychological or profile-completeness scores.

`visuals.py` builds an opt-in ArtBrief from approved public fields using a fixed allowlist of abstract terms. Raw profile/source text, names, identifiers, private/local fields and optional personality labels never enter the ArtBrief. No image provider or model is called. A separately authored procedural SVG wash has stable geometry, fixed palette variants, a profile revision/asset hash record, explicit refresh, download and removal. Profile changes cannot silently replace a selected wash. The final full draft pack also includes the identity sentence and safe local art artifacts. Real image consent/generation, private cloud assets and real plan metering remain later-phase work.

## Modules and data boundaries

| New area | Responsibility |
|---|---|
| `src/postriff_alpha/auth.py` | Provider-neutral AuthGateway contract; deterministic verified-user adapter; users/memberships/devices/idempotency/audit. No production identity. |
| `domain.py` | Isolated SQLite state, optimistic revision checks, source/brief/variant/profile/preference commands and portable ZIPs. |
| `profiles.py`, `profile_builder_prompt.md` | Relationship intake, guided questions, scoped builder request, untrusted import, field review and Personal Voice Package. |
| `generation.py` | AgentAdapter contract and deterministic fixture v1.0.0; paired sample-language variants; attributed custom quotes. |
| `templates.py` | Three neutral released templates, configuration schema and private instance bindings; plan/trial fixture parity. |
| `visuals.py` | Approved-profile graph/list projection, abstract ArtBrief filter, local procedural SVG and explicit artwork/revision commands. |
| `server.py` | Loopback-only HTTP/static host; workspace authorization; exact Host/Origin/CSRF and CSP; no publisher/billing routes. |
| `studio/web/src/founder` | Separate React entry, onboarding, account fixture, draft/review/learning/You and responsive styles. |
| `studio/web/alpha`, `vite.alpha.config.ts` | Independent alpha build; original client entry/config/build not replaced. |
| `tests/test_postriff_*.py` | 49 behavioral/HTTP/privacy/persistence/import/artifact tests. |
| `scripts/postriff_alpha.py`, `verify_postriff_alpha.py` | Local launcher and bounded privacy/fixture-export validator. |

The store is additive and separate from legacy Studio data. SQLite schema version 1 is guarded; unknown versions fail closed. No legacy data migration, global skill installation or external schema migration occurs. Private database/key files use owner-only permissions. Browser local storage holds the local access credential and unfinished text; approved state is saved server-side. This is OS-account/local capability isolation, not cloud authentication or encryption at rest.

## Verification and repairs

49 focused tests, 70 existing frontend contract tests, TypeScript and the separate Vite build pass. Eight browser journeys cover all four modes at desktop/mobile sizes; R22 regression then covers You field review through resaving/exporting updated drafts. Browser checks include version-only CLI inspection, individual import review, conflicts, .md upload/unsupported-file rejection, keyboard sign-in, focused errors, graph/list parity, artwork removal/persistence, and quota failure without losing work. Source/profile/brief changes preserve original variants until replacement review. Server restart preserves private account/profile/variant state.

Concrete fixes during validation included muted-text contrast, focus recovery after asynchronous changes, closed SQLite connections, strict Hybrid import validation, anonymous sample read-only persistence boundaries, and marking drafts stale after a changed/restored profile. Tests and affected browser checks were rerun after fixes. All 57 original private skill files and seven tracked legacy sources/config files remain unchanged. No new third-party dependency was installed.

CLI detection read Codex 0.154.0, Claude Code 2.1.153 and Gemini 0.45.2. Authentication/history access and real execution remain untested; all real model jobs are blocked/unqualified. Fixture tests do not meet the wider plan's native-agent or three-user voice-recognition gate. Human activation timing, demand, pricing and repeat-use evidence remain absent. Phase 0 remains incomplete and P02–P05 pending.

## Review and local runtime

Founder URL: `http://127.0.0.1:4326/`. Personal data defaults to `~/Library/Application Support/PostRiffFounderAlpha/alpha.sqlite3`. Browser testing used a separate synthetic store and port 4327; no fixture was inserted into the founder store. Original Studio at port 4310 was left running and untouched. Unrelated occupied ports were not reused or stopped.

Use the [source inventory](evidence/source-inventory.json), [privacy report](evidence/privacy-artifact-validation.json), and [eight-journey receipt](evidence/browser-acceptance.json) for review. Evidence marked R21 predates the You utility label; R22 is authoritative for the added profile view. Historical preliminary captures are retained but are not completion evidence.
