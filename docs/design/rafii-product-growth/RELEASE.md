# RAFII Product Growth v2 — release, activation and rollback

This file prepares the release; it does not authorize one. Every step marked **(James)** is a real external operation that
needs his specific approval for that exact action (DECISIONS D-007). Preparing commands is allowed; executing them is not.

## 1. Release candidate identity (fill at release time)

| Field | Value |
|---|---|
| Repository / branch | `dev-james0723/PostRiff` / `claude/rafii-product-growth-v2` |
| Pull request | #87 (base `fix/rafii-call-lifecycle-20260930` = production `dcb5bcdc`) |
| Candidate SHA | _pending_ |
| CI run (local-gates, scenes) | _pending_ |
| Vercel preview deployment | _pending_ |
| Production before release | `dpl_HSmKDFfjkd8UCaoo2QfgerZUVwLL` @ `dcb5bcdc` (rollback target) |

## 2. Migration order (additive; each needs approval; apply before the code that reads it)

Production has received earlier migrations through one-off, sha-pinned runners (see `scripts/trend_release_migrate.py`
for the current pattern: identity check against the project ref, whole prior ledger match, exact allowed set, plan then
apply the same plan). This program's runner is `scripts/product_growth_release_migrate.py` (`RAFII_GROWTH_MIGRATION_DSN`;
plan with a read-only session, then apply that exact plan). It pins every allowed file below to its reviewed SHA-256 and
refuses any other pending file (`tests/test_product_growth_release.py`).

| Order | File | Owner | SHA-256 | Depends on | Reader released in |
|---|---|---|---|---|---|
| 1 | `047_inbox_operational_sync.sql` | Inbox v1 | `bcb9be5b…a369553` | 044 | this release |
| 2 | `048_pricing_credit_catalog_v2.sql` | Pricing v2 | `a36357de…792ba0` | 020–022 | this release (guarded readers tolerate its absence) |
| 3 | `050_free_lifecycle_bootstrap.sql` | Pricing v2 | `f9aad0a0…b1e7d` | 048 | this release |
| 4 | `080_customer_results.sql` | this program (results) | `846d2be4…53958e0ed1f` | 001–047 | this release |
| 5 | `081_relationships.sql` | this program (relationships) | `0d2b181d…d76f73a33` | 047 (Inbox threads), 080 (won FK; idempotent re-apply adds it if 080 came later) | this release |
| 6 | `083_visual_packs.sql` | this program (visual pack) | `3aedc1a4…d137955c` | 001–047 | this release |
| 7 | `084_briefs_proof_strategy.sql` | this program (briefs/proof) | `5225be48…c99701d5` | 001–047 | this release |
| 8 | `087_source_uploads.sql` | this program (intake) | `0acc1a3f…b5647b65` | 001–047 | this release |
| — | 082 | not used: series live in workspace planning state (D-021) | — | — | — |

Full SHA-256 values are recorded in `DECISIONS.md` and must match the files byte for byte at runner time.

Rules: never edit an applied file; never reorder; staging first; snapshot before and after; verify forced RLS and grants
after each; the previous deployment must keep working with the new schema (all changes additive).

## 3. Flags (all default off; names exactly as in code)

| Flag | Scope | Turns on | Rollback effect |
|---|---|---|---|
| `POSTRIFF_PRICING_V2_ENABLED` | server | v2 catalog, Free bootstrap, managed-credit modes | new workspaces get trials again; existing v2 rows untouched |
| `NEXT_PUBLIC_PRICING_CATALOG` | web build | public pages show the v2 catalog (`v2`) | `legacy` |
| `POSTRIFF_CREATOR_PRICE_EXPERIMENT_ENABLED` + `_COHORT` | server | 49/59/79 assignment for an explicit cohort | assignments stay immutable; no new ones |
| `POSTRIFF_GROWTH_PLATFORM_PREVIEW` | server (JSON policy) | Free first-value runs, platform-funded | Free first-value refuses before paid I/O |
| `RAFII_INBOX_SYNC_ENABLED` / `RAFII_INBOX_REPLY_SEND_ENABLED` | server | Inbox v1 sync / fenced sender | see Inbox runbook |
| `RAFII_FIRST_WEEK_ENABLED` | server | first-week resource (needs `RAFII_WEEKLY_OPERATOR_ENABLED`) | panel hidden; journeys kept |
| `RAFII_SOURCE_UPLOADS_ENABLED`, `RAFII_TRANSCRIPTION_ROUTE` | server | raw PDF/audio intake | new uploads refused; jobs drain |
| `RAFII_RELATIONSHIPS_ENABLED` | server | relationships + follow-ups | records kept, no new reminders |
| `RAFII_RESULTS_ENABLED` | server | results, signed receiver, tracking links | receiver/redirect 404; evidence kept |
| `RAFII_SERIES_ENABLED` | server | Signature Series | series kept; Evergreen unchanged |
| `RAFII_VISUAL_PACK_ENABLED` | server | visual packs | packs/exports kept |
| `RAFII_OPPORTUNITY_BRIEF_ENABLED`, `RAFII_PROOF_V2_ENABLED` | server | briefs, proof revisions, strategy decisions | no new editions/revisions |

Other release prerequisites (no flag): the private Supabase Storage bucket `rafii-source-uploads` (size limit
≤ 30,000,000 bytes; `application/pdf`, `audio/wav`, `audio/mpeg`, `audio/mp4`, `audio/ogg`) must exist before
`RAFII_SOURCE_UPLOADS_ENABLED`; the Python functions need `pypdf==6.19.0` (in `requirements.txt`); the bundled Noto Sans
TC fonts (~11.5 MB, SIL OFL) ship in both Python functions so voice can render carousels too.

## 4. Activation manifest (to be completed per approval)

For each capability: project/environment, migration filenames + checksums, source SHA, flags, workspace allowlist,
per-operation provider capability, budget/consent references, approval owner, rollback condition. Nothing in this table
is active until its row has an approval reference.

| Capability | Environment | Workspace allowlist | Provider / budget | Approval ref | State |
|---|---|---|---|---|---|
| Pricing v2 catalog (Free + Creator view) | production | all new workspaces | none (no paid I/O) | — | not_started |
| Creator checkout (live Stripe Prices 49/59/79) | production | experiment cohort | Stripe live | — | blocked (James) |
| Free first-value preview | production | all Free | platform budget policy | — | blocked (James) |
| First Week Ready | production | internal workspace first | managed credits | — | not_started |
| Raw audio transcription | production | — | provider + budget | — | blocked (James) |
| First-party results receiver | production | one customer-like workspace | none | — | not_started |
| Raw PDF/caption intake | production | internal workspace first | none (local parsing) | — | not_started (bucket needed) |
| Relationships & follow-ups | production | internal workspace first | none (reminders through the existing outbox) | — | not_started |
| Signature Series | production | internal workspace first | managed credits for Rafii drafting only | — | not_started |
| Visual packs (export only) | production | internal workspace first | none (server rendering) | — | not_started |
| Carousel queueing | production | — | a verified multi-image publisher | — | blocked (no verified provider) |

## 5. Rollback

1. Disable admission of new affected work with the flags above; never erase pending jobs, ledger holds, webhook events,
   approvals or receipts. Uncertain operations stay reconcilable; switching off never triggers a second send or charge.
2. Revert to `dpl_HSmKDFfjkd8UCaoo2QfgerZUVwLL` only after confirming the additive schema still serves it.
3. Legacy subscribers keep their entitlements; disabling Creator sale is not a downgrade of existing customers.
4. No destructive down-migration or bulk deletion as ordinary rollback.
5. Triggers: tenant leakage, incorrect charging, duplicate external effects, materially false verification or metric
   claims, unusable core flow, regression beyond the approved operational budget.
