# Active Scout v1.2 — local implementation ledger

Baseline: `claude/growth-phase0`, `0ba0c60406dc2613208e617f43ccf74441ce353c`.
Authority: superseding Claude Cloud handoff dated 2026-09-27 in
`docs/design/rafii-growth-loop/`. Local implementation/testing only; no push,
PR, merge, deploy, production migration, paid calls or real social actions.

## Slice 0: reconciled capabilities

| Capability | Verified local implementation / integration decision |
|---|---|
| JEV | `growth/jev.py`, `questions.py`, `judgments.py`, `router.py`, `usage.py`; reuse typed judgments, abstention, personal cache and attempt receipts. |
| Listening | `coworker/listening.py`; bounded workspace watchlists/opportunities, consent checks, ResearchBroker, existing notification event. Extend this path. |
| Creation | `coworker/service.py`, `ideas.py`; existing sources, policy review, Ideas writer, draft/source IDs, campaigns and queue. Carry a structured plan into these paths. |
| Outcomes | `insights.py`, `growth/metric_schedule.py`, `coworker/performance.py`; append-only observations and 1h/24h/7d windows. Keep measured outcomes separate from judgments. |
| Learning | Existing strategy hypotheses and explicit acceptance; no new memory product or automatic voice mutation. |
| Goals | No separately implemented Growth Goal/Lab domain found in this checkout. Add bounded objective selection to existing watchlists, without inventing a second product. |
| Storage | Existing tenant workspace JSON plus metric tables; migrations currently end at 032. Bounded summaries only; no raw media storage. No new SQL migration planned. |
| Media | FactPack/source provenance exists. Watch-It design, strict schema, report parser and frames-only/native-caption/Whisper tests inspected as reference only. No Rafii Watch-It service or hosted See/Listen/Read adapters verified. |
| Providers | ResearchBroker public search exists; no new platform retrieval capability verified. Provider expansion remains a separate verification step. |
| UI | Weekly → Opportunities exists. Legacy act currently links to empty Ideas capture; replace only under the Flipper flag with context-preserving creation. |

The canonical spec already contains both locked sentences verbatim; no wording edit needed.

## Preserved unrelated work

Pre-existing `.claude/skills/`, old handoff, official collector/docs/tests, plus
earlier local edits to `growth/outcomes.py`, `growth_collect_common.py`, their
tests and Phase 0 contracts are preserved outside this implementation's commit.
No conflicting external action occurred before supersession. The old collector
is unfinished (Instagram cursor pagination still needs separate review).
Existing `status-draft` stash remains untouched.

## Implemented boundaries (v1.2)

- Existing Listening owns capped signals (120), trends (30), opportunities (50),
  and media cache (24). Each surface shows at most three current candidates.
- One workspace lease reserves at most one retrieval and eight typed judgments
  per run; daily limits are ten retrieval passes and 32 judgment units. Each
  judgment has a two-second total router deadline, no strong-model fallback.
  Retrieval uses the existing two-request public-search pass. Media has two
  passes per run, four units per stage per day, 600-second input limit, sixty
  frames, five-second adapter deadline, one request, zero retries. These are
  conservative work-unit limits, not claims about dollar spend.
- Separate acquisition/frame/transcription/multimodal reservations happen before
  egress. Cache is personal and content/adapter/rights addressed; failures and
  expired rights are explicit. No media provider is installed automatically.
- `SuppliedWatchAdapter` imports already supplied typed local artifacts only;
  no commands, file discovery, download or Watch-It execution. Production mode
  refuses local-only adapters even if their local flag is on.
- Four versioned sets reuse JudgmentService → AIModelRouter → JevService, with
  per-attempt usage records in the existing ledger. Search text is untrusted.
- One declared objective is selected on the existing watchlist form. Legacy
  watchlists without an objective are left unscouted; following the same topic
  with an objective updates it. No fabricated Growth Goal/Lab product.
- Public leads retain unavailable metrics. Authorized official-shaped evidence
  can supply creator-normalized comparisons; no new provider adapter is claimed.
- Make post creates a verified, idempotent Ideas source with a native execution
  plan. The existing writer opens with its destination and language; user review,
  credit authorization, campaign linking, Queue and publish approval remain the
  existing flows. Source/plan bindings are validated at write completion/apply.
- Verified job → draft → execution → opportunity lineage reads the existing
  append-only metric observations at 1h/24h/7d. Five earlier comparable posts
  are required. A 24h/7d lift of 1.5× can propose a sequel; the server rechecks
  observed data before creating a new idempotent sequel source. One-hour results
  never become durable strategy. Repeated two-arm evidence uses existing
  Performance Learning hypotheses and owner experiment/rejection decisions.
- Autonomous strong-model synthesis remains unavailable: its flag is reserved,
  and final writing uses the existing user-triggered Ideas writer and ledger.
  No new model, provider or media credential was installed or used.
- Explicit repeated-evidence acceptance is now wired through the existing
  Strategy Hypothesis UI/API (`accepted` → existing `supported` status plus
  `experiment.planningAccepted`). Only the owner can accept a Scout hypothesis
  with at least five posts per arm. It is read into later same-account,
  same-language, same-objective plans; dismissal withdraws it. No voice mutation.
- The existing retention cron physically removes expired media summaries in
  batches of at most twenty workspaces; expiry also redacts UI views immediately.

## Slice and file receipt

All slices started at the exact baseline HEAD above and are delivered together
in the local commit containing this file. The final response supplies that commit
hash. No migration is added: **NOT_NEEDED**. Existing workspace JSON, RLS,
strategy hypotheses and append-only observations provide persistence.

| Slice | Implementation and changed files (paths relative to repository) |
|---|---|
| 0 / M0 | This capability ledger; existing Watch-It reference inspected, not executed. Superseding specs are preserved in their existing ignored directory. |
| 1 | `src/postriff_phase2/growth/scout.py`: normalization, dedupe, creator/source diversity, lifecycle, normalized official-shaped evidence, bounded ranking and storage. A new official reading refreshes an unchanged caption; supplied media identity is retained. |
| 2 | `growth/question_sets/scout_{signal,cluster,workspace_fit,execution}.v1.json`, `growth/router.py`, `growth/scout.py`: typed abstaining gates and bounded model routes. |
| 3 | `growth/scout_runtime.py`, `coworker/listening.py`: reserved budgets, consent, deadline, claim/commit/external work/fenced completion; reuse ResearchBroker. |
| 4 | `growth/scout.py`, `coworker/listening.py`, `web/src/features/coworker/weekly/opportunities-panel.tsx`: single explicit objective, forwarding utility, no filler. |
| M1–M5 | `growth/scout_evidence.py`: typed evidence/moments, supplied-artifact adapter contract, rights, modality validation, bounded cache/budgets, execution hypotheses. No hosted media adapter provisioned. |
| M6 | `growth/scout.py`: distinct platform-native plans and moment references, original asset requirements, explicit unmeasured outcomes. |
| 5 | `web/src/features/coworker/weekly/opportunity-flipper.tsx`, `web/src/lib/coworker/{api,hooks,types}.ts`: max-three primary opportunities, evidence/limitations, watch/skip, observed results and sequel action. |
| 6 | `coworker/{service,http}.py`, `ideas.py`, `web/src/features/ideas/use-draft.ts`, `web/src/lib/api/types.ts`: idempotent Make post source, selected destination/language, server-owned lineage validation through existing creation/campaign/Queue. |
| 7 / M7 | `growth/scout_outcomes.py`, `coworker/performance.py`, `coworker/service.py`, `web/src/features/coworker/personalization/personalization-view.tsx`: observed objective rates, 1h/24h/7d comparisons, verified sequel, repeated-evidence owner acceptance and withdrawal. Also fixes PostgreSQL Decimal timestamps in performance JSON. |
| Flags/isolation | `coworker/flags.py`, `deployment.py`: new defaults and preview egress isolation. |
| Verification | `tests/test_growth_scout.py`, `tests/phase2/postgres_growth_scout.py`, `tests/scout_browser_seed.py`, `web/tests/{coworker-api.test,scout-browser}.cjs`. |
| 8 | **NOT_RUN**: provider expansion requires separate capability verification and authorization; no new platform adapter. |

Python short paths in this table are under `src/postriff_phase2/`.

## Flags

All seven are **OFF by default**, with legacy Listening preserved when off:

- `RAFII_ACTIVE_SCOUT_ENABLED`
- `RAFII_TREND_OBJECTS_ENABLED`
- `RAFII_JEV_SCOUT_ENABLED`
- `RAFII_OPPORTUNITY_FLIPPER_ENABLED`
- `RAFII_SCOUT_STRONG_MODEL_ESCALATION_ENABLED` (reserved; no autonomous route)
- `RAFII_MULTIMODAL_ENRICHMENT_ENABLED`
- `RAFII_WATCH_IT_LOCAL_ADAPTER_ENABLED` (local artifact import only)

The first two extend the existing Listening runner. Its existing Listening,
ResearchBroker and research-consent gates still apply. JEV additionally needs its
own flag and configured credential. Repeated-evidence review uses the existing
Performance Learning flag. No provider-specific flag is needed without a new
provider adapter. Preview isolation refuses enabled egress flags.

## Validation

Execution state: **local application + disposable local PostgreSQL; synthetic
signals, channels, writer, metrics and media**. The API/browser checks did not
perform real OAuth, social publishing or provider/model/media requests.

Environment: Python 3.12.13 in ignored `.token-pilot/validation-venv`, PostgreSQL
17 from `/opt/homebrew/opt/postgresql@17/bin`, Node 24 via
`PATH=/opt/homebrew/opt/node@24/bin:$PATH`. No dependency files changed.

Commands below run from repository root except the web commands, which run from
`web/`. `PYTHONPATH=src:tests` was used for Python commands; broad tests additionally
set `POSTRIFF_RESEARCH=0 POSTRIFF_LOCAL_CLI=0`. `python` below means
`.token-pilot/validation-venv/bin/python`.

| Check | Exact command after the environment above | Result |
|---|---|---|
| Focused core/regressions | `python -m unittest test_growth_scout test_growth_questions test_growth_judgments test_growth_router test_postriff_learning_performance` | 77 passed |
| Broader Python | `python -m unittest discover -s tests -p 'test_*.py'` | 1,342 passed in 114.369s |
| PostgreSQL Scout | `python scripts/postriff_pg_suite.py postgres_growth_scout` | 19 passed |
| PostgreSQL existing coworker | `python scripts/postriff_pg_suite.py postgres_coworker postgres_growth_scout` | Existing coworker 35 passed; later Scout rerun above supersedes its earlier 18 checks |
| PostgreSQL metric scheduling | `python scripts/postriff_pg_suite.py postgres_coworker postgres_growth_metric_reads postgres_growth_scout` | Metric scheduling 16 passed; first Scout fixture failed, fixed and superseded by the 19-pass rerun |
| TypeScript | `npm run typecheck` | Passed |
| Lint | `npm run lint` | 0 errors, 0 warnings; 756 files |
| API/presentation | `node --test tests/coworker-api.test.cjs tests/coworker-present.test.cjs` | 7 passed |
| Production build | `NEXT_PUBLIC_SENTRY_DISABLED=1 npm run build` | Passed; Next.js 16.3.5, 97 static pages generated |
| Browser | `node web/tests/scout-browser.cjs` (repository root) | 44 passed |
| Whitespace/hygiene | `git diff --check` | Passed |

Logs and screenshots are local/ignored under `.token-pilot/reports/`:
`scout-focused.log`, `scout-python-final.log`, `scout-postgres-scout-final.log`,
`scout-postgres-final.log`, `scout-postgres.log`, `scout-typecheck-final.log`,
`scout-lint-final.log`, `scout-api-final.log`, `scout-web-build-final.log`,
`scout-browser.log`, and `scout-browser/results.json` plus four PNGs.
The broad suite emitted existing CLI-runtime `ResourceWarning` messages during
failure-path tests; its final result was `OK`, with no failures or errors.

Browser matrix: Chromium and WebKit, each at 1440×960 desktop and 390×844 phone.
Keyboard disclosure/Make post, phone touch, reduced-motion setting, horizontal
overflow, axe serious/critical violations, source/plan continuity and zero new
console errors all passed. Desktop flows additionally verified server-rechecked
7d sequel creation and explicit owner planning acceptance. These are synthetic
observed outcomes, not real creator success. The initial multi-engine acceptance
fixture retained Chromium's decision; resetting that local fixture fixed test
isolation. The performance API Decimal error found by browser QA was a real
application defect, now covered by a PostgreSQL JSON-serialization regression.
Only this task's API/Next servers were stopped after QA. Temporary Next-generated
`tsconfig.json` include entries were restored; unrelated local services and files
were left alone. The browser result applies to the unchanged frontend/API flow;
the subsequent source-hash/official-reading fix passed the focused, broad and
PostgreSQL checks above.

## Calls, capabilities and limits

For **every slice**, real JEV/model calls **NOT_RUN**, real provider calls
**NOT_RUN**, Watch-It execution **NOT_RUN**, acquisition/download/transcription/
multimodal calls **NOT_RUN**. Fake evaluators and supplied synthetic EvidencePack
imports ran in tests. Existing deterministic preview writing ran in local
integration checks. No claim of production validation or live model quality is
made. Host model/reasoning configuration was not changed.

Locally verified capabilities are the existing integration contracts, synthetic
application flows, actual local PostgreSQL behavior and browser behavior.
Instagram/Threads approval/scopes, LinkedIn analytics, live search quality and
third-party media rights were not verified through platform APIs. No credentials,
permissions, provider purchases or real social actions were added. Actual
external billing/host token cost is **unknown**; work-unit caps are not dollars.

Known limitations and release blockers:

- No real validation dataset or live JEV calibration; lexical preclustering and
  generic native templates need separately authorized quality evaluation.
- Autonomous strong-model synthesis/query expansion is unavailable. Final prose
  still uses existing user-triggered, budgeted Ideas writing. Make post creates
  context and opens that flow; it does not automatically spend generation credits.
- The local Watch-compatible adapter imports supplied packs; it does not run
  Watch-It, ffmpeg or download video. A permitted hosted media adapter remains
  external follow-up work. Read/See/Listen adapters remain conceptual.
- Current retrieval stays on existing public-search coverage; source metrics are
  unavailable there. Official-shaped normalization is tested synthetically, not
  evidence of a newly working Instagram/Reddit/social API integration.
- Comparisons currently use the latest 120 verified jobs with Scout lineage,
  requiring five earlier comparable posts. A creator can therefore receive
  `needs_more_data` despite having other non-Scout history. Video metric fields
  remain unavailable unless existing observations actually supply them.
- Authority and business return have no fabricated proxy; revenue/ROI remain
  unmeasured without downstream attribution. Accepted associations remain scoped
  experiments/preferences, never causal rules or automatic voice changes.
- The old official collector remains a separate unfinished work item. Its files
  and the existing stash are excluded from this commit.

Recommended next step: review this local commit and this evidence; obtain
explicit authorization for any push/PR and separately scoped staging/provider
validation. Keep flags off until rights, scopes, live quality, real budgets and
deployment-specific checks are verified. No push, PR, merge, deployment or
production migration was performed in this task, including before supersession.
