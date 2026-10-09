# Rafii Intelligent Library release

Execution state: **AWAITING AUTHORIZATION.** Nothing in this release has been pushed, merged, deployed or applied to a shared database. Every Library intelligence flag defaults to off. No paid model call has been made.

| | |
|---|---|
| Package | `docs/design/rafii-intelligent-library-2026-10-08/` (R01–R20, A001–A080) |
| Worktree | `/Users/ouxianxing/Documents/.agent-worktrees/rafii-intelligent-library-20261008` |
| Branch | `claude/rafii-intelligent-library-20261008` (local only) |
| Base | `origin/consumer-saas` `3da806f0` |
| Candidate | see "Candidate and validation" below |
| Acceptance ledger | `docs/design/rafii-intelligent-library-2026-10-08/evidence/acceptance-status.json` |
| Remote run log | `docs/design/rafii-intelligent-library-2026-10-08/evidence/runs.md` |

## What ships

One server-side retrieval and policy service (`src/postriff_phase2/library_intelligence/`). The Library UI, Ask Library, the site agent's Library reads, OpenUI task surfaces and draft source packs all go through it. It covers:

- **Policy (R02).** Purpose grants and processing (egress) grants are separate. Grants are pinned to the content version they were given for. Revocation is checked again at commit time, without a lock, and wins an in-flight race.
- **Understanding (R03–R06).** Jobs with leases, retries and truthful capability states. Digital extraction runs before OCR, and document locators are real. ASR, video and vision run through the AI Gateway only when their flags are on and a processing grant allows it. Waveforms are computed from decoded samples by streamed, bounded ffmpeg.
- **Retrieval and answers (R07–R08).** Lexical plus optional pgvector hybrid search with signed cursors and server totals. Answers carry verified quotes and citation deep links, and abstain honestly. Retrieved text cannot drive tools.
- **Organization (R09–R10).** Smart Collections store an allowlisted rule AST and keep manual overrides and undo. Version lineage is acyclic, duplicate handling is conservative, and a source update warns instead of overwriting.
- **Voice, creation, suggestions (R11–R15).** Voice samples are admitted per span, and revocation rebuilds the profile. Source packs flow into drafts. Final artifacts are registered exactly once; scratch work and loops are excluded. Suggestions are quiet, capped per person, and can be dismissed or snoozed. Usage events come from real schedule and publish hooks.
- **UI (R16–R18).** One Add entry, type-aware previews, URL-restored state, and batch actions that report partial failures. OpenUI task descriptors use strict zod schemas, server-issued action envelopes and a fallback that preserves the user's work.
- **Operations (R19).** Deletion reaches every derivative and leaves the duplicate's bytes alone. Metrics and route latency are recorded. Backfill can be paused, and cost is reserved and settled through the existing ledger.

## Database migration

Only one migration: `migrations/postriff/104_library_intelligence.sql`. It is additive, idempotent and wrapped in a single transaction.

- It adds four columns to `pr_library_assets` (`lineage_id`, `version_no` default 1, `source_kind` default `'upload'`, `media` default `{}`), all with safe defaults, so no backfill is needed.
- It extends collections (`kind` default `'manual'`, rule, revision) and collection items (`origin` default `'manual'`).
- It creates 18 new server-only tables. Each has RLS enabled and forced, and is revoked from `public`, `anon` and `authenticated`. Each gets a `service_only` policy.
- If the `vector` extension is available, it adds the embedding column and two HNSW indexes (1024-dimension text, 256-dimension visual). Without pgvector the column is absent and search runs lexical-only, reporting that honestly.

Preconditions on the target project, checked read-only before applying:

1. Migrations 093–096 are applied. Production had 093–095 on 2026-10-08, and 096 was in validation per `rafii-library-20261007.md`; re-check this.
2. pgvector: on Supabase, enable `vector` in the `extensions` schema from the dashboard first. Otherwise 104's `create extension if not exists vector` creates it in `public`, which the security advisor flags. Once it is enabled in `extensions`, that statement is a no-op and the type resolves through the search path.
3. Run the security and performance advisors before and after. Expect no new Library findings.

Rehearsal evidence: `tests/phase2/postgres_library_intelligence_migration.py` (A078) builds a pre-104 workspace (normalized assets, chunks, labels, manual collection, a legacy photo id in workspace JSON), applies 104 twice, and checks that:

- every existing row is unchanged;
- defaults are safe;
- no grants are invented;
- list, detail, download and search keep working with every flag off;
- new retrieval refuses honestly while its flag is off;
- deleting a canonical original keeps the surviving duplicate's bytes.

It runs remotely on disposable PostgreSQL 16, both without and with pgvector. The run IDs are below.

## Flags and configuration

All flags default to off, and each one is enabled on its own.

| Flag | Enables | Needs |
|---|---|---|
| `RAFII_LIBRARY_ENRICHMENT_ENABLED` | Understanding jobs (extraction, structure, OCR, media analysis) | none |
| `RAFII_LIBRARY_RETRIEVAL_ENABLED` | Search, Ask Library, Library reads for agents | `RAFII_LIBRARY_CURSOR_SECRET` |
| `RAFII_LIBRARY_EMBEDDINGS_ENABLED` | Semantic and visual vectors | pgvector, AI Gateway, `RAFII_LIBRARY_EMBEDDING_MODEL` |
| `RAFII_LIBRARY_ASR_ENABLED` | Transcription | AI Gateway / OpenAI, `RAFII_LIBRARY_ASR_MODEL` |
| `RAFII_LIBRARY_VISION_ENABLED` | Visual annotation, no identity inference | AI Gateway, `RAFII_LIBRARY_VISION_MODEL` |
| `RAFII_LIBRARY_VOICE_ENABLED` | Consented voice samples | none |
| `RAFII_LIBRARY_SUGGESTIONS_ENABLED` | Proactive suggestions | none |
| `RAFII_LIBRARY_TASK_UI_ENABLED` | OpenUI task surfaces | OpenUI runtime merged first |
| `RAFII_LIBRARY_ARTIFACTS_ENABLED` | Auto-registration of final artifacts | none |
| `RAFII_LIBRARY_BACKFILL_PAUSED` | Kill switch for backfill | none |

Paid calls use `RAFII_LIBRARY_PRICES` and the existing `billing.Ledger` reserve/settle with `ai_call_events`. A call is refused when the budget cannot be reserved.

## Canary and rollback plan (requires authorization at each step)

1. Merge the OpenUI production branch first (owned by the "Rafii × OpenUI 正式版發佈" session). Then rebase this branch and send them the descriptor-registration patch. Re-run `jcb ci` on the rebased head.
2. Apply 104 to staging. Run the advisors and a read-only check (table count, RLS, `service_only` policies, pgvector presence).
3. Deploy with all flags off. Smoke-test the existing Library (upload, list, detail, download, delete) to confirm no regression.
4. Turn on `ENRICHMENT` and `RETRIEVAL` for the founder workspace only. Check search latency against A031, the job error rate and costs.
5. Turn on the paid capabilities (`EMBEDDINGS`, `ASR`, `VISION`) only after the real-provider evaluation, within an approved spend cap.
6. Turn on `VOICE`, `SUGGESTIONS`, `ARTIFACTS` and `TASK_UI` one at a time.

To roll back, turn the flags off. That stops every new code path immediately. To go further, promote the previous Vercel deployment. **Do not drop the 104 tables**; they hold derived data and consent records. Originals, chunks, labels and legacy media are never modified by 104.

## Candidate and validation

Filled in from observed remote runs only. See `evidence/runs.md`.

**Candidate `757e127d`** (branch `claude/rafii-intelligent-library-20261008`): full remote release validation **PASS**, JCB → Depot run [psn1gp78lq](https://depot.dev/orgs/jf34f85hr0/workflows/psn1gp78lq), receipt `sourceHead=757e127d`, base `origin/consumer-saas` `65b1ea83` (#134 and #135 merged in). Commits after the candidate on this branch change only evidence documents.

| Stage | Result |
|---|---|
| Dependency audit | 0 vulnerabilities |
| Python unit + full discovery | pass (4,062 tests, 371 skipped) |
| Disposable PostgreSQL 16 | all 12 intelligence suites pass without and with pgvector; lifecycle, agent runtime/style pass |
| Web node tests | pass |
| Web type check / lint / production build | pass / 0 errors (4 pre-existing warnings) / pass |
| Offline secret scan | pass (synthetic test values marked inline) |
| Library browser acceptance | pass in Chromium and WebKit, 1440 and 390 px |
| Intelligence browser harness | pass in Chromium at 390×844, 768×1024, 1440×900, 844×390, 200% zoom |
| A031 search latency (10,000 assets, 8 concurrent) | lexical p95 1,981 ms ≤ 2,000; hybrid p95 2,273 ms ≤ 3,000; cold 185 ms |

Acceptance ledger against `757e127d`: 24 VERIFIED, 49 UNVERIFIED, 7 BLOCKED, 0 FAILED (`scripts/library-intelligence-acceptance.py check --sha 757e127d` passes). The BLOCKED cases need the real-provider evaluation (A017, A018, A022, A023, A026, A032) or a real iPhone (A066). The run history, including every failed attempt and its fix, is in `evidence/runs.md`.

`origin/consumer-saas` has since gained #136 (YouTube public launch), which touches no Library file; merging it is part of the merge step and needs one more validation run.

## Remaining gates

- **Authorization (James):** push the branch, open the PR, merge, apply 104 to staging and production, deploy, and enable each flag.
- **Real-provider evaluation:** A017, A018, A022, A023, A026 and A032. This needs `~/.config/rafii-library-eval/provider.env` with `AI_GATEWAY_API_KEY` and `OPENAI_API_KEY`, within the approved US$10 cap.
- **Local authenticated preview and visual evidence:** this needs the one approved local `npm ci` in the worktree's `web/`.
- **A066 iPhone Safari smoke test:** needs James's device; see `evidence/iphone-smoke.md`.
- **OpenUI:** the runtime merges first, then descriptor registration.
