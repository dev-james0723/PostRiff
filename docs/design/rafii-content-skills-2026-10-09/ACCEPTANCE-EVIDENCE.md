# Rafii Content Skills Integration: acceptance ledger (A01–A40)

Spec package: `/Users/ouxianxing/Documents/Rafii-Content-Skills-Spec-2026-10-09` (`ACCEPTANCE.md` holds the requirement text). This is the **only** acceptance ledger for the feature. Lineage, gates, security review, blockers, preview and rollback plans and the authorization request are in [`RELEASE-READINESS.md`](RELEASE-READINESS.md); the A17 review is [`A17-EDITORIAL-REVIEW.md`](A17-EDITORIAL-REVIEW.md); the A24/A25 investigation is [`RENDERING-BLOCKER-REPORT.md`](RENDERING-BLOCKER-REPORT.md).

**Scope.** Evidence for the implementation, not a release receipt. Nothing was pushed, merged, deployed, migrated in production, published, flag-enabled outside a CI sandbox, or run on a paid model.

## Status vocabulary and environments

Status: **VERIFIED**, **PARTIALLY VERIFIED**, **UNVERIFIED**, **BLOCKED**, **FAILED**, **REGRESSION**. Partial means part of the requirement has evidence and the rest is named in "Limitation".

| Env | Meaning |
|---|---|
| U | Python unit tests (`tests/test_rafii_creation_capabilities.py`, `tests/test_asset_consumers.py`, full discovery) |
| PG | Real disposable PostgreSQL 16 via `scripts/postriff_pg_suite.py`, `tests/phase2/postgres_coworker.py` CS01–CS06 |
| N | Node contract tests (`web/tests/*.test.mjs`, `*.test.cjs`) |
| B | Cloud synthetic browser: Next production build → hosted Python → disposable PostgreSQL, Chromium, `RAFII_CREATION_PROJECTION_ENABLED=1`, GenUI default off (`web/tests/content-skills-browser.cjs`) |
| R | Read-only code review (security subagent; Codex CLI) |
| M | Machine-assisted document review (AI agent; not a human) |

**Tested commit for this ledger:** `b559c12c` (run `pt3xq2p12l`). Run `pt3xq2p12l` covered every suite at this exact SHA (receipt `20261010T011715753013Z-ci.json`, remote exit 0, 784 s). Earlier runs are listed in `RELEASE-READINESS.md` §3; an earlier run is never counted as evidence for later code.

## Matrix

| ID | Status | Expected behaviour (short) | Evidence | Env | Observed | Limitation → next action |
|---|---|---|---|---|---|---|
| A01 | VERIFIED | Recompute every active public platform skill and native format; entries ≠ executable skills | `InventoryTest` | U | 33 platform rows, 56 formats, parity with `channel_adapters.PROFILES`; 91 registry entries counted separately | — |
| A02 | VERIFIED | Reproduce Facebook's exclusion, then fix it without breaking the five | `RolloutTest`; CS01 | U, PG, B | `platform_not_enabled` with flags off; drafted with wave 1; the five never flag-dependent | — |
| A03 | VERIFIED | UI view, API validation and client types share one revision; CI catches drift | `test_web_fixture_matches_the_live_projection`, `creation-capabilities.test.mjs`; 409 `schema_revision_mismatch` | U, N | Fixture shape equals live projection | — |
| A04 | VERIFIED | Unknown, retired, forged or private skills/formats fail safely; a client cannot enable a platform by name | `ValidationTest`, `test_native_formats_are_offered_and_accepted_only_while_a_wave_is_on` | U, N | Stable codes incl. new `format_not_enabled`; forged `draftable` ignored by the client | — |
| A05 | VERIFIED | Draft, copy, export work unconnected; OAuth only where needed | `WriterRouteTest`; CS01, CS03, CS04; browser facts | U, PG, B | Facebook drafted with no account; review says "draft, copy and export only" | — |
| A06 | VERIFIED | Two accounts, formats, locales stay distinct; cross-workspace binding rejected | `test_two_accounts_formats_and_locales_stay_distinct`, `test_cross_workspace_account_binding_is_rejected` | U | Key (platform, language, account, format) | — |
| A07 | VERIFIED | Missing Facebook Page explicit; no substitution or implied authorization | `WriterRouteTest`; CS01; `draftFacts` "Needs Facebook Page before publishing" | U, PG, N | `unresolved: ["page_ref"]`; `choose_account` with several Pages | — |
| A08 | PARTIALLY VERIFIED | Qualified route passes core + channel instructions with ids, versions, hashes | `SkillRouteTest`; CS01 `skillRoute.qualified` | U, PG | Bindings and hashes recorded; adapter text in composed instructions | No live model receipt → A39 (D3) |
| A09 | VERIFIED | Missing library or skill never yields a platform-qualified success | `test_missing_library_or_adapter_is_a_generic_draft`; review fact "Unverified generic draft" | U, N | `skillRoute.generic=true` plus warning | — |
| A10 | VERIFIED | Multi-platform CJK budget: whole files or recorded omission, no silent clip | `test_multi_platform_cjk_budget_drops_whole_files_and_records_cuts` | U | 16 CJK destinations under 60 kB; 9 kB records a cut and demotes the route | — |
| A11 | VERIFIED | Registry-v2 and workflow flags on/off match behaviour; disabled pack never reported as executed | `test_registry_v2_flag_on_and_off_matches_bindings`, `RolloutTest`, flags-off format test | U, PG | Flags off now also leave the five's formats unchanged (security fix S-1) | — |
| A12 | VERIFIED | Backward-compatible requests, saved drafts, defaults, aliases | Full Python discovery; `test_existing_turns_keep_the_exact_prompt` | U | Full discovery 4519 OK (371 skipped) at `b559c12c` | — |
| A13 | VERIFIED | Native fields schema-validated, separate from private notes, faithful text projection | `test_text_projection_is_faithful_including_xiaohongshu_title_first`, structural-field test | U | Bare-string slides/frames refused by schema, normalised at ingestion (Codex P2) | — |
| A14 | VERIFIED | Positive and negative tests for every advertised format; unknown constraints visibly unverified | `test_every_format_has_a_positive_and_negative_native_case` | U, N | 56 formats; `characterLimit: null` where unknown; review fact "limits unverified" | — |
| A15 | VERIFIED | Instagram post/carousel/story/reel and Facebook post/story/reel distinct from media and publish readiness | `test_instagram_and_facebook_formats_are_distinct_from_media_and_publishing`, `test_publish_readiness_matches_the_approval_gate_for_every_format`; browser | U, B | Non-default formats read `export_only`, matching the approval gate | — |
| A16 | PARTIALLY VERIFIED | EN, zh-Hans-CN, zh-Hant-TW, zh-Hant-HK, yue-Hant-HK keep script, register, facts, brand terms | `LocaleTest`; benchmark fixture route | U | Four distinct tags with their guides; script lint passes | Register quality from a real model **BLOCKED** → D3 (paid benchmark) |
| A17 | PARTIALLY VERIFIED | Pack review covers all composed references; no blanket algorithm claims, hashtag quotas or invented anecdotes | `A17-EDITORIAL-REVIEW.md` (M); `test_no_blanket_algorithm_claims_or_quotas` | M, U | 2 FAIL (unsourced Xiaohongshu ranking claim; X thread contradiction) and 2 CONCERN fixed in `cf9d0e0a`; 17 CONCERN open | **Human editorial sign-off UNVERIFIED** → D6; ~45 non-Chinese locale guides not reviewed |
| A18 | VERIFIED | Real source → FactPack, brief, variants, campaign with evidence chain | CS01 | PG | `factPackId`, `evidenceId` preserved | — |
| A19 | VERIFIED | Snippets, disputes, injected commands never become facts or tools; viewer denied before egress | `test_snippets_disputes_and_injection_never_become_usable_facts`; CS03 | U, PG | Injection line unusable; viewer refused before writes | — |
| A20 | VERIFIED | Intake reports its true capability | `test_intake_reports_its_true_capability` | U | `pdf_text_required`, `transcript_required`, `captions_required`; image reference-only | — |
| A21 | VERIFIED | Same key/input: no duplicate campaign, draft or charge; regenerate makes a revision | CS02, CS06 | PG | Identical request returns the same campaign and runs; replayed regenerate with the same `requestKey` returns its revision with no new run (S-3) | — |
| A22 | PARTIALLY VERIFIED | Source, voice, skill or media-spec change invalidates descendants and approvals, never other edits | `test_a_changed_link_marks_earlier_campaigns_stale_without_touching_them`; fingerprint staleness | U | Stale marking verified; reused sources keep the person's fact approvals (S-2) | Media-spec change invalidation not separately tested → add with A24 |
| A23 | PARTIALLY VERIFIED | Cancel, reload, network, provider failure resume safely; only failed stages retry | CS03, CS06 | PG | Provider failure keeps finished copy; retry writes only missing targets; concurrent retry 409 `campaign_busy`; stale claim taken over once | Browser reload mid-campaign not exercised → preview §6 |
| A24 | BLOCKED | Static media with real bytes, order, dimensions, safe areas, provenance, preview | `RENDERING-BLOCKER-REPORT.md` | R | A no-cost renderer can reuse the document runtime, but needs CJK fonts in the production bundle and a new media state | → D4 |
| A25 | BLOCKED | Video-ready only with playable verified video; script/cover never passes | `RENDERING-BLOCKER-REPORT.md`; `draftFacts` Reel test; browser Reel fact | R, N, B | No path marks video ready; review says "Rafii wrote the script, not a video" | No encoder in production → D5 (V0 verify uploads; V1 needs infra decision) |
| A26 | VERIFIED | Missing renderer/input → saved brief or blocker; copy kept | CS01 | PG | `media.state` `brief_saved` / `planned` with `missingAssets` | — |
| A27 | PARTIALLY VERIFIED | Humanizer, meaning and platform checks record versions and real results | CS01, CS03 (existing stage) | PG | Evaluator version and meaning findings per draft | No new evaluator; quality of the checks themselves not re-assessed |
| A28 | VERIFIED | Copy/export keeps paragraphs, Unicode, fields, order, attribution; no notes leak | `test_export_keeps_paragraphs_unicode_order_and_hides_private_notes`, `test_export_writes_list_items_as_text_and_survives_broken_unicode`, structural-field test; CS03, CS04 | U, PG, N | Manifest sha256 equals the bytes; list items as text; lone surrogates replaced; client copy uses the same layout | — |
| A29 | VERIFIED | Review shows exact target, account, locale; can revise one variant; no public post as a side effect | `native-draft-facts.test.mjs`; browser review facts at 1440 and 390 px; existing per-variant Edit and proposed update (`pipeline-card.tsx:200`, GAP-D04) | N, B | Each draft lists account, format, writing guide, media, publishing and limits; Instagram carousel and Facebook Reel read "Export only"; Reel reads "Rafii wrote the script, not a video"; Facebook reads "No Facebook account connected"; format fields and "Copy with format fields" present; drafting created 0 reviews and 0 jobs; at both widths | Facts appear only while a wave is on (by design) |
| A30 | VERIFIED | Publish requires live provider/account/plan/scope/content-hash approval; edited or expired approvals fail | `NativeFormatPublishTest` (incl. native-record-only case); existing approval suite | U | Gate reads `format` and `native.formatId` | — |
| A31 | VERIFIED | Ambiguous outcomes reconcile before retry; export or HTTP success never a receipt | Existing reconciliation suite; `published: false` | U, PG | — | — |
| A32 | PARTIALLY VERIFIED | Typed UI works with GenUI off; 390 px, keyboard, accessibility, locale have browser evidence | Browser run `pt3xq2p12l` | B | PASS at 1440 and 390 px: composer formats, keyboard reach to the format select and the caption editor, axe 0 serious/critical in the review region, accessibility tree reads term/definition pairs, 0 px overflow, no page errors. Screenshots `evidence/CLOUD-SYNTHETIC-{composer,review}-{1440,390}.png` (sha256 in RELEASE-READINESS §3) | **Real screen reader UNVERIFIED** and **signed-in production session UNVERIFIED** → preview §6 step 5 (needs a person) |
| A33 | VERIFIED | Analytics joins the right verified post/variant/account with definition, window, coverage | CS05 | PG | Mismatched observation never joins | — |
| A34 | VERIFIED | Missing, stale, partial, unsupported ≠ zero; no conflation | `test_variant_join_keeps_definitions_and_never_zero_fills`; CS05 | U, PG | `value: null` with state | "unsupported" collapses to "unavailable" (S-9, P3) |
| A35 | VERIFIED | Preference, observation, hypothesis separate; no causal claims | `test_learning_summary_keeps_three_kinds_apart` | U | `causal: false` | — |
| A36 | VERIFIED | Preview, accept, reject, undo, revoke learning; no other tenant | CS05 | PG | Owner undo; editor 403 | — |
| A37 | VERIFIED | Approval, egress, budget, HistoryImport, privacy unchanged; costs bounded | Full suite; flags-off tests | U, PG | No new paid path; benchmark refuses paid runs | — |
| A38 | VERIFIED | PostgreSQL/RLS/concurrency on a real DB | Run `pt3xq2p12l` | PG | Every `tests/phase2/postgres_*.py` group passed on PostgreSQL 16.15, CS01–CS06 included | — |
| A39 | BLOCKED | Fixed paired benchmark, zero critical violations, reviewed quality; paid needs authorization | `scripts/content_skills_benchmark.py` | U | Fixture route: 67 cases, 0 critical violations | Paid route **not wired** and not authorized → D3 |
| A40 | BLOCKED | Release checks on the exact release; authorized production verification; rollback keeps data | — | — | No release authority | → D1, D2, D7 |

## Rollout and rollback

See `RELEASE-READINESS.md` §6–§7. In short: enable `RAFII_CREATION_PROJECTION_ENABLED` on a preview first; only then consider `RAFII_CREATION_ALL_PLATFORMS_ENABLED`. Turning the flags off hides the extra platforms, the non-default formats and the review facts; saved drafts, exports and campaigns stay and still export.
