# Rafii Content Skills Integration: acceptance evidence (A01–A40)

Spec package: `/Users/ouxianxing/Documents/Rafii-Content-Skills-Spec-2026-10-09` (README, PRD, ENGINEERING-SPEC, STATE-AND-SOURCES, PLATFORM-MATRIX, ACCEPTANCE).

**Scope of this file.** It records evidence for the implementation and is not a release receipt. Nothing here was pushed, merged, deployed, migrated in production, published, or run on a paid model.

## Build identity

| Item | Value |
|---|---|
| Branch | `claude/rafii-content-skills-20261009` (isolated worktree `.agent-worktrees/rafii-content-skills-20261009`) |
| Base | `origin/consumer-saas` `220d2de1` (PR #149 merge), re-fetched 2026-10-09 |
| Flags added | `RAFII_CREATION_PROJECTION_ENABLED` (wave 1: Facebook) and `RAFII_CREATION_ALL_PLATFORMS_ENABLED` (every mapped platform). Both are off by default. No existing flag was changed. |
| Remote validation | JCB → Depot `depot-ubuntu-24.04-16`, task `ci:content-skills:jcb` (`scripts/cloud-content-skills-validation.sh`). The JCB mapping was remapped temporarily and then restored; it was never committed. |

### Remote runs

| Run | Commit | Result |
|---|---|---|
| `wknq6470gd` | `758d65ec` | 4394 of 4396 Python tests passed. Two legacy-record errors were fixed afterwards. |
| `zkwzx2gd3z` | `9650ac2c` | Python 4398 OK. PostgreSQL: CS01–03 failed because the harness had revoked its IG account. Fixed. |
| `2cxfhw54jk` | `550a996c` | Python OK. PostgreSQL: CS01, CS04 and CS05 passed. CS02 and CS03 found a real duplicate-source bug, which was fixed. |
| `87br6f0pln` | `8df9d86b` | Python 4403 OK (371 skipped). Every PostgreSQL group passed, CS01–CS05 included. Web contracts: one source-level test still bound the old identifier. Fixed. |
| `7qbh8hm9fn` | `54a5af6d` | Exit 0 (receipt `20261009T221058009992Z-ci.json`). Node web contracts 852/852. Remote type check clean. Lint has warnings only, none in changed files. Production build compiled. Browser A32 PASS. Python and PostgreSQL were not rerun because `54a5af6d` changes only a web test and a script after `8df9d86b`. |

### Local runs

Only targeted unit runs and the deterministic benchmark ran locally; each takes seconds.
- `python3 -m unittest test_rafii_creation_capabilities`: 39 tests.
- `scripts/content_skills_benchmark.py`: 67 cases.

### Independent review

A read-only Codex CLI review ran in fallback mode (the official plugin is not installed) against `origin/consumer-saas`. It returned one P1 and eight P2 findings, all reproduced and fixed in `8df9d86b`:
- format publish preflight;
- native fields carried through an accepted update;
- export of scripts and frames;
- the CLI route and native formats;
- the ambiguous formatless fallback;
- chip de-duplication;
- format restore when a conversation reopens;
- regenerate numbering;
- per-metric freshness.

## Status per requirement

Status vocabulary: verified / failed / blocked / unverified / not_applicable. Evidence names the test or run.

| ID | Status | Evidence and reason |
|---|---|---|
| A01 | verified | `InventoryTest`: 33 platform rows and 56 native formats, recomputed from the registry and the channel SKILL.md tables; parity with `james_au_social.channel_adapters.PROFILES`; registry entries (91) counted separately from installed skill packages. |
| A02 | verified | Reproduced first: `check_destinations([Facebook])` returned `AlphaError: Choose supported destinations.` at `220d2de1`. Fixed behind wave 1 (`RolloutTest`). Real database: CS01 drafts unconnected Facebook. The original five do not depend on any flag. |
| A03 | verified | One projection serves validation, every runtime, campaigns, automations, v2 tools and the composer facet (`/api/ideas/models` → `creation`). The revision travels with each turn; a stale one returns 409 `schema_revision_mismatch`. Drift is caught by Python `test_web_fixture_matches_the_live_projection` and `test_web_fallback_matches_the_server_original_set`, plus node `creation-capabilities.test.mjs`. |
| A04 | verified | Stable codes: `unknown_platform`, `platform_not_enabled`, `unknown_format`, `format_platform_mismatch`, `duplicate_destination`, `schema_revision_mismatch`. Private `james-au-*` skills never appear as rows. The v2 `draft_create` tool cannot enable a platform by naming it. The client ignores a forged `draftable` entry (node). The CLI route uses the same projection. |
| A05 | verified | CS01 drafts Facebook with no account (unit `WriterRouteTest`). Export works without OAuth (CS03, CS04). Publishing still requires the live chain. |
| A06 | verified | Uniqueness key is (platform, language, account, format), checked in validation, `resolve_destinations`, `same_slot` and model parse. Ambiguous formatless answers are refused. `bind_accounts` and `_campaign_destinations` refuse cross-workspace or revoked accounts. |
| A07 | verified | An unbound Facebook draft lists `page_ref` as unresolved and never substitutes one. With several Pages, `publish_route` returns `choose_account`. Approval refuses non-default formats with `format_not_publishable`. |
| A08 | verified (code route) | Every draftable platform binds the editorial core, the adapter contract and the channel adapter with version and sha256, and the adapter text is in the composed instructions (`SkillRouteTest`). `native.skillRoute` is recorded on each draft (CS01 asserts it is qualified). Live model receipt of the prompt: see A39. |
| A09 | verified | A missing library or adapter, or a hard cut of the skill text, produces `skillRoute.generic=true` and a warning that the draft is an unvalidated generic draft. |
| A10 | verified | 16 CJK destinations stay within the 60 kB budget with no hard cut and every route qualified. A 9 kB budget records a cut and demotes the route. |
| A11 | verified | Registry-v2 on and off: the Humanizer pack is bound, or recorded as omitted, and never reported as executed. Rollout flags on and off (`RolloutTest`). Real database: CS01 with all flags on. |
| A12 | verified | Full Python suite 4403 OK (`87br6f0pln`). `PLATFORMS` and `DEFAULT_REQUEST_DESTINATIONS` are unchanged. A turn with only the original five keeps the exact system prompt and payload. Formatless saved drafts still refresh in place. |
| A13 | verified | `rafii.native-draft.v1`: public slots, bindings, `privateNotes`, media and constraints are kept apart. `text_projection` is faithful for 33 platforms × 5 locales (Xiaohongshu title first). The person's edit wins (`current_native`). |
| A14 | verified | Positive and negative cases for all 56 formats (`test_every_format_has_a_positive_and_negative_native_case`). Constraints stay `verified: false`; no limit is invented, and `characterLimit` is `null` where unknown. |
| A15 | verified | Instagram post, carousel, story and reel; Facebook page_post, story and reel. Media `needs_input` and publish `not_checked` are separate from draft readiness. Browser checks are in A32. |
| A16 | blocked (model) / verified (deterministic) | The four Chinese tags are distinct and each binds its own locale guide. The deterministic writer passes the script lint for Simplified and Traditional. Register quality from a real model needs the paid benchmark, which is not authorized. |
| A17 | verified (automated + edits) / unverified (human editorial) | Automated scan: no hashtag quotas, reach guarantees or invented-anecdote instructions. Xiaohongshu tags and the closing line are now optional. Dated native-reasoning sections were added for Xiaohongshu, Douyin, Bilibili, Zhihu, Weibo and WeChat Channels, with versions bumped and relocked. A human editorial review of the full composed packs is still owed. |
| A18 | verified | CS01 on real PostgreSQL: SourceArtifact → FactPack → brief → drafts → campaign, with `factPackId` and `evidenceId` preserved. |
| A19 | verified | Unit: injected text never becomes a claim, disputed figures are unusable, and the existing R01 marks snippets unusable. CS03: a viewer is refused before any write or egress. |
| A20 | verified | `source_intake` refuses a PDF without text (`pdf_text_required`), a voice memo without transcript (`transcript_required`) and an untimed transcript (`captions_required`). An image is reference-only. |
| A21 | verified | CS02: an identical request returns the same campaign with no new runs or drafts. Explicit `regenerate` creates `_r2` and leaves the original untouched. Numbering is monotonic over bounded history. |
| A22 | verified (stale marking) | A changed link marks earlier campaigns stale without touching their drafts. A fingerprint change (registry, capability, voice or brand) marks a campaign `stale: inputs_changed`. Approvals stay bound by the existing content hash at approval time. |
| A23 | verified | CS03: a writer failure keeps the campaign (`needs_input`, retryable). `retry` writes only the missing targets under a new writer key; attempts = 2. |
| A24 | blocked | No static renderer route is qualified in this branch. Managed image generation is a paid provider route and was not authorized. Creative briefs are saved instead (A26). |
| A25 | verified (no false claim) / blocked (production) | No path marks video ready: video formats stay `needs_input`, and a script is labelled as a script. Producing playable video needs a renderer or the user's own media; not exercised. |
| A26 | verified | CS01: `media.state` is `brief_saved` or `planned` with `missingAssets`, while the copy and the other variants are kept. |
| A27 | verified (existing stage) | The Source-to-Campaign quality stage records the Humanizer evaluator version and meaning findings per draft (existing code, run in CS01 and CS03). No new evaluator was introduced. |
| A28 | verified | Unit: paragraphs, Unicode (emoji, CJK), slide and segment order, scripts and frames are exported; private notes never are. CS03 and CS04: manifest sha256 matches; `published: false`. |
| A29 | unverified (UI display) / verified (no side effect) | CS01 creates no scheduling or publishing job. Drafts carry account, locale and format. The existing review UI does not yet show the native format or skill route beside each draft. |
| A30 | verified | The existing approval chain is unchanged. The new `format_not_publishable` gate is covered by `test_asset_consumers.NativeFormatPublishTest`. Edited or expired approvals are covered by the existing suite (Python OK). |
| A31 | verified | Reconciliation is unchanged (existing suite). The export package states it is not a publication receipt (`published: false`). |
| A32 | verified (synthetic cloud browser) | Run `7qbh8hm9fn`: a Next production build with Python, disposable PostgreSQL and GenUI at its default (off). Results:<br>- the facet offers the original five plus Facebook;<br>- Instagram's four formats and Facebook's three are offered, each with what it still needs;<br>- the Facebook select is reachable by Tab;<br>- overflow is 0 at 1440 and 390 px;<br>- no page errors.<br>Evidence (sha256-checked): `evidence/CLOUD-SYNTHETIC-composer-1440.png`, `evidence/CLOUD-SYNTHETIC-composer-390.png`, `evidence/CLOUD-SYNTHETIC-content-skills.json`. A screen-reader audit and a real signed-in session are still unverified. |
| A33 | verified | CS05: a verified LinkedIn post joins its draft (format `linkedin.post`, skill route qualified) with metric definition version, window and provider. A mismatched observation never joins. |
| A34 | verified | Unavailable, stale and not-reported metrics stay `value: null` with their state. Nothing is summed across providers. Paid promotion stays `unknown`. |
| A35 | verified | `learning_summary` keeps preferences, observations and hypotheses separate. Hypotheses stay `causal: false` (existing database check). |
| A36 | verified | An owner can undo a hypothesis decision; an editor gets 403 (CS05). `overlays/preview` changes nothing. Existing accept, reject, disable and reset are unchanged. |
| A37 | verified | No approval, egress, budget, HistoryImport or privacy defaults changed. The new flags default off. No new paid call path. The benchmark refuses paid runs without budget and authorization. |
| A38 | verified | Every `tests/phase2/postgres_*.py` group passed on disposable PostgreSQL 16 (`87br6f0pln`), including the new CS01–CS05. |
| A39 | blocked | Fixed benchmark `scripts/content_skills_benchmark.py`: 67 cases covering 33 platforms, every Instagram and Facebook format, four Chinese registers on six Chinese platforms, and one injection negative. The deterministic route passes fidelity, structure and script with 0 critical violations. The paid model route needs an explicit budget and authorization. |
| A40 | blocked | No release authority: no push, merge, deploy, production flags or production verification. Rollback is flag-off, which hides the new platforms; drafts and assets are kept. |

## Rollout and rollback

1. Enable `RAFII_CREATION_PROJECTION_ENABLED` (Facebook) on a preview.
2. Repeat A32 and the paid A39 there.
3. Only then consider `RAFII_CREATION_ALL_PLATFORMS_ENABLED`.

Turning a flag off removes the platforms from the facet and validation. Saved drafts, exports and campaigns stay untouched; their re-validation fails closed with stable codes.
