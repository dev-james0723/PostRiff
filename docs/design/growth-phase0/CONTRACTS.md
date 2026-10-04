# Growth intelligence Phase 0: contracts

Approved plan: v3 design doc (https://claude.ai/artifact/Rh24Gowc3Ni3xnVX9cGXcq), decisions D1–D12 approved by James on 2026-09-25. Branch `claude/growth-phase0`, worktree `James-Au-Studio-growth`, base `origin/consumer-saas` 677d49c. No deploy, no production database change, no merge; every new behaviour is behind a flag that defaults off.

Package: `src/postriff_phase2/growth/`. Pure-Python standard library only (no new dependencies). All network calls go through an injectable `transport` so unit tests never touch the network.

## Already built (do not rewrite)

- `growth/calibration.py`: quadratic weighted kappa, ECE, isotonic fit/apply, Spearman, ridge fit, `to_level`, `fit_thresholds`. Tests: `tests/test_growth_calibration.py`.
- `growth/questions.py`: question-set parsing/validation, registry (`get(id, version=None)`), `QuestionSet.payload_questions()`, `digest`, `estimate_tokens`. Tests: `tests/test_growth_questions.py`.
- `growth/question_sets/postdoctor.v1.json`: 28 boolean questions, 9 dimensions, 4 risks, levels `[0.35, 0.55, 0.75]`.

## JevService (`growth/jev.py`)

```python
EVALUATE_ENDPOINT = "https://ai-gateway.vercel.sh/v1/evaluate"   # env AI_GATEWAY_EVALUATE_ENDPOINT overrides
DEFAULT_MODEL = "typesafe-ai/jev"                                  # env POSTRIFF_JEV_MODEL overrides

class JevError(Exception): code: str; status: int | None; retry_after: float | None
# subclasses (code): JevAuthError("auth") 401/403 · JevBudgetExceeded("budget") 402 ·
# JevBadRequest("bad_request") 400/413/422 · JevRateLimited("rate_limited") 429 ·
# JevUpstream("upstream") 5xx/connection · JevTimeout("timeout") · JevMalformed("malformed")

@dataclass(frozen=True)
class RawEvaluation:
    model: str; answers: dict; input_tokens: int | None; output_tokens: int | None
    cost_usd: float | None          # providerMetadata.gateway.cost, parsed from string
    cost_source: str                # "gateway" | "unknown"
    generation_id: str | None; final_provider: str | None; latency_ms: int

class JevService:
    def __init__(self, api_key, *, endpoint=EVALUATE_ENDPOINT, model=DEFAULT_MODEL,
                 transport=None, clock=time.monotonic, zero_data_retention=True): ...
    def evaluate(self, state, questions: dict, *, timeout_s: float) -> RawEvaluation: ...
```

Rules: one POST per call, no internal retries (callers decide), `Authorization: Bearer <key>` never logged or included in exceptions, `providerOptions.gateway.zeroDataRetention = true`, reject a request whose `estimate_tokens(state) + largest question` exceeds 32,000 before sending (`JevBadRequest`), parse `retry-after` on 429, validate the response is a JSON object with `answers` (dict) else `JevMalformed`. Answer contents are validated by JudgmentService, not here.

## AIModelRouter and usage ledger (`growth/router.py`, `growth/usage.py`)

```python
@dataclass(frozen=True)
class UsageEvent:
    task: str; stage: str | None; model: str; route: str   # "primary" | "fallback"
    provider: str | None; generation_id: str | None
    input_tokens: int | None; output_tokens: int | None
    cost_usd: float | None; cost_source: str                 # "gateway" | "table:<version>" | "unknown"
    latency_ms: int; status: str                             # "ok" | error code
    workspace_id: str | None; subject: str | None            # opaque ids only, never text

class UsageSink(Protocol):
    def record(self, event: UsageEvent) -> None: ...
class MemoryUsageSink:  ...        # tests
class PostgresUsageSink:  ...      # INSERT into pr_model_usage_events, cursor supplied by caller

TASKS = {  # task -> (kind, default model, fallback chain, timeout seconds)
  "postdoctor.judge": ("evaluate", "typesafe-ai/jev", ["google/gemini-2.5-flash-lite"], 3.0),
  "genome.label":     ("evaluate", "typesafe-ai/jev", ["google/gemini-2.5-flash-lite"], 8.0),
  "postdoctor.rewrite": ("chat", "anthropic/claude-sonnet-5", ["anthropic/claude-haiku-4.5"], 45.0),
}

class AIModelRouter:
    def __init__(self, *, jev: JevService | None, chat_runtime, usage: UsageSink, tasks=TASKS): ...
    def evaluate(self, task, state, question_set, *, names=None, workspace_id=None, subject=None) -> Evaluation
    def complete_json(self, task, messages, *, schema: dict, workspace_id=None, subject=None) -> dict
```

As built (Phase 0, supersedes the sketch above where they differ): `AIModelRouter(*, jev=None, chat=None, usage=None, tasks=None, sleep, clock)` where `chat(messages, model, max_tokens) -> (content, usage)`; `chat_from_runtime(ServerModelRuntime)` adapts the existing runtime and converts its private 429/bad-shape exceptions to `AlphaError` so each fallback attempt is still recorded (`rate_limited` / `upstream`). Task tuples are `(kind, primary, fallbacks, budget_s, max_output_tokens)`; Phase 0 tasks are `postdoctor.judge`, `genome.label`, `golden.compare` (no fallback, so comparisons never mix models). `evaluate(...)` returns `RouterEvaluation`; `router.evaluator(task)` plugs into `JudgmentService`. `complete_json` and `postdoctor.rewrite` are deferred to Phase 1 rewrites.

Deadline (decided by James, 2026-09-26): the task budget is one end-to-end monotonic deadline covering Jev attempts, the retry pause and every fallback. Each adapter receives only the remaining time (`jev.evaluate(timeout_s=remaining)`, `chat(..., timeout_s=remaining)`); no attempt starts with less than `MIN_ATTEMPT_S` (0.05 s) left, and no fallback starts after expiry. When the deadline passes unanswered the router raises `RouterTimeout` (code `timeout`); every `RouterError` carries `.attempts`, the UsageEvents actually recorded for that call. The budget is not a hard latency bound: `chat_from_runtime(...).enforces_timeout` is False when the runtime transport takes no timeout, and an answer that arrives after the deadline is kept (it was paid for) and marked `RouterEvaluation.late=True`. `ServerModelRuntime._call` gained an optional `timeout` (default unchanged). `JudgmentService.judge` turns `timeout`/`rate_limited`/`upstream`/`unavailable`/`malformed` into an uncached `Judgment(status=<code>, answers={}, route="none", attempts=...)` so scoring stays available with every question abstained; `auth`/`budget`/`bad_request` still raise.

`Evaluation` carries `raw` answers, `route`, `model`, cost fields and latency. On `JevRateLimited`/`JevUpstream`/`JevTimeout` the router retries once after `retry_after` or a bounded backoff (≤ 2 s total in the request path), then tries the fallback chain via `chat_runtime` using the question set compiled to a JSON-schema prompt (fallback answers are marked `route="fallback"`, `calibrated=False`). `JevAuthError`, `JevBudgetExceeded`, `JevBadRequest` never retry or fall back automatically. Every attempt writes exactly one `UsageEvent`, including failures (cost `None`, source `unknown` when not reported). `chat_runtime` is the existing `ServerModelRuntime` transport; reuse its gateway cost parsing.

## JudgmentService (`growth/judgments.py`)

```python
@dataclass(frozen=True)
class Answer:
    name: str; type: str; value: object       # bool-probability float | choice str | score float
    probabilities: dict | None; top: float     # highest probability (boolean: max(p, 1-p))
    abstained: bool

@dataclass(frozen=True)
class Judgment:
    question_set: str; digest: str; model: str; route: str
    answers: dict                              # name -> Answer
    invalid: tuple                             # names whose answers failed validation
    cost_usd: float | None; cost_source: str; generation_id: str | None; latency_ms: int
    cache_key: str; cached: bool

class JudgmentCache(Protocol):
    def get(self, key) -> Judgment | None: ...
    def put(self, key, judgment) -> None: ...

def cache_key(scope: str, subject_hash: str, qs: QuestionSet, model: str) -> str
# scope: "personal:<workspace_id>" (own posts, drafts, comments; never shared) or "shared" (public content)

class JudgmentService:
    def __init__(self, router: AIModelRouter, cache: JudgmentCache): ...
    def judge(self, question_set, state, *, subject_hash, scope, workspace_id=None) -> Judgment
def validate_answers(qs, raw_answers) -> tuple[dict, tuple]   # (valid Answers, invalid names)
```

Validation: every asked question answered with the same `type`; choice value in criteria and the argmax; probabilities cover all options and sum to 1 ± 0.02; boolean probability in [0, 1]; score within [0, n−1] with rung probabilities keyed "0".."n−1". Abstain when boolean probability falls in `abstain.boolean_band`, or when the top probability of a choice/score is below `choice_min`/`score_min`. Invalid answers are never treated as "no"; they are reported in `invalid` and excluded from levels.

## Post Doctor (`growth/post_doctor.py`)

```python
FLAG = "POSTRIFF_POST_DOCTOR"   # "1" enables; default off

@dataclass(frozen=True)
class DimensionResult:
    id: str; level: int | None      # 0..3, None = not enough answered weight
    score: float | None; fixes: tuple   # localized fix hints for the lowest-contributing questions (max 2)
    answered_weight: float

@dataclass(frozen=True)
class PostDoctorResult:
    question_set: str; dimensions: tuple; risks: tuple        # risk ids whose probability >= 0.65
    computed: dict        # similarity_recent (0..1 | None), fit_winners (level | None), length_fit (dict)
    confidence: str       # "low" | "medium" | "high"
    confidence_reasons: tuple; judgment: Judgment

def levels_from_judgment(qs, judgment, *, thresholds=None, lang="en") -> tuple[DimensionResult, ...]
def similarity_recent(text, recent_texts) -> float | None     # character 3-gram Jaccard max, CJK-safe
def confidence(qs, judgment, *, calibrated: bool, posts_with_metrics: int) -> tuple[str, tuple]
class PostDoctorService:
    def check(self, *, workspace_id, draft_text, platform, lang, creator: dict, recent_texts=(),
              posts_with_metrics=0, calibrated=False) -> PostDoctorResult
```

Score per dimension = Σ wᵢ·pᵢ′ / Σ wᵢ over answered items, where pᵢ′ = p for normal items and 1 − p for `invert` items; level via `calibration.to_level(score, thresholds)`. When answered weight < `levels.min_answered_weight` of the total, level is `None`. Confidence: `low` when uncalibrated for the language; `medium` when calibrated but fewer than 10 posts with metrics; `high` otherwise; drop one step when more than a third of asked questions abstained. `fit_winners` stays `None` below `computed.fit_winners.min_posts_with_metrics`. Length fit uses `text_measure.measure`. The service never rewrites text; rewrites are Phase 1 and may only use creator-supplied facts.

As built (`growth/post_doctor.py`, reversible assumptions): `PostDoctorService(judgments, *, question_set=None, model, thresholds={lang: [t1,t2,t3]}, env=None)`; `check` raises `PostDoctorDisabled` unless `POSTRIFF_POST_DOCTOR == "1"`. Judgments use scope `personal:<workspace_id>` and subject `subject_hash("postdoctor", platform, lang, draft, canonical(creator))`; `creator` is reduced to plain string/number/string-list facts before it reaches the model. Abstained, invalid and unanswered questions carry no weight (never "no"). `answered_weight` is the answered fraction of the dimension's total weight; `score` is reported only when a level is. Fix hints: answered items with adjusted p′ < 0.5, ordered by lost weight w·(1−p′), max 2; `zh*` languages use `zh-HK` copy, others `en`. Fitted thresholds apply only to their own language and only when `calibrated=True`; otherwise the question-set defaults. The abstention confidence drop counts abstained + invalid + unanswered. A judgment with `status != "ok"` (router timeout/unavailable) yields all levels `None`, no risks, confidence `low` with reason `judge_<status>`, while computed fields remain. `fit_winners` stays `None` throughout Phase 0 (winners comparison ships with Creator Genome, Phase 1). `length_fit` = `text_measure.measure` plus `status` (`ok`/`over`/`unknown`) and `over_by`.

## Golden set and comparison (`growth/golden.py`, `growth/compare.py`)

CSV columns as in `docs/design/growth-phase0/golden-template.csv`. `python -m postriff_phase2.growth.golden validate FILE` prints problems with row numbers and exits non-zero on any; `load(FILE)` returns rows with levels 0..3 (CSV 1..4) or None. `evaluate(rows, judgments_by_id, qs)` returns per-dimension kappa (overall and per language), ECE for "level ≥ strong", threshold fit via `calibration.fit_thresholds` with 5-fold cross-validation, abstention rates, latency p50/p95 and total cost.

`python -m postriff_phase2.growth.compare --labels FILE --models jev,gemini-2.5-flash-lite,claude-haiku-4.5,claude-sonnet-5 --max-usd 20 --confirm-live --out REPORT.json` runs live judgments. Without `--confirm-live` it prints the cost estimate and exits 0 without any network call. It aborts before the first call if the estimate exceeds `--max-usd`, and stops mid-run as soon as recorded cost reaches the cap. The API key comes from `AI_GATEWAY_API_KEY` in the environment and is never printed.

As built: `golden.parse(FILE) -> (rows, problems, warnings)`; `validate` prints problems as `line N: …` (exit 1), warnings for fewer than 200 rows or a missing zh-Hant/en group (exit 0 when no problems). Language groups: zh-HK/zh-TW/zh-MO/zh-Hant* → `zh-Hant`, en* → `en`, other tags stand alone; every metric is reported per group so Traditional Chinese and English are validated separately. `evaluate` reports per dimension `labelled`, `scored`, `abstained`, `missing_judgment`, `kappa`, `ece_strong` (forecast = dimension score, outcome = label ≥ strong) and per language `kappa` plus `fit` = `{thresholds, kappa_fit, kappa_cv, reason}` (5-fold, folds by sha256(id); `too_few` below 2×folds rows or one label class), plus question abstain rate, latency p50/p95 over non-cached judgments and cost (known USD + unknown-cost calls). `compare`: models without a `DEFAULT_PRICES` entry (Jev, flash-lite today) need `--price MODEL=IN,OUT` (USD / 1M tokens) or the tool refuses; the estimate counts state + questions (+ fallback system prompt for chat models) and 24 output tokens per answer. Mid-run it stops before a call that would take spend past the cap, counting unknown-cost calls at their estimate. Chat models are judged through the router's fallback prompt (uncalibrated by construction). Golden judgments use scope `personal:golden`. Tests run on SYNTHETIC fixtures only; no labels are manufactured and no live call is made.

## Readings and history (`growth/metric_schedule.py`, `growth/backfill.py`, `growth/history_import.py`)

### Migration 035 (`migrations/postriff/035_growth_metric_reads.sql`)

026–031 are reserved elsewhere, so growth takes 032 (recorded in `docs/postriff-migration-numbering.md`). Additive and idempotent, referencing only 004/007 objects, so it applies after 025 in `tests/phase2/rls.sql` and in the full ledger chain. Tables: `pr_metric_reads` (one row per post × offset `t0|1h|24h|7d|backfill`, unique per post, lease columns); `pr_owned_posts` (metadata only, `caption_chars` only, no caption text or hash); `pr_history_imports` (one active run per connection); `pr_model_usage_events` (service-only; `cost_usd_micro` NULL when unknown, CHECK forbids a value labelled unknown). `pr_metric_observations` gains nullable `read_offset`. The first three are `tenant_read` + `trusted_write`. The production apply needs separate approval.

### Metric schedule (`growth/metric_schedule.py`), flag `POSTRIFF_METRIC_READS` (default off)

`MetricScheduler(connection_factory, oauth, *, transport, clock, monotonic, worker_id)`. `on_post_verified(cur, ws, job)` is SQL-only, runs inside the worker's verification transaction in its own savepoint and never raises: for a Threads/Instagram adapter that is `production_reviewed` and a connection whose `analytics` capability is `Direct`, it inserts t0/+1h/+24h/+7d rows anchored at `job.verification.at` (ON CONFLICT DO NOTHING). `then_schedule(existing_hook, scheduler)` chains it like `with_time_back`. `tick(max_reads=10, max_seconds=15)` claims due rows (SKIP LOCKED, 120 s lease) and commits, re-checks `accountDeletion` and Direct analytics with plain SELECTs, fetches one grant per connection per tick and reads insights outside any transaction, then completes fenced on the lease: 200 → `done` plus observations tagged `read_offset` and `period_start = anchor`; 429/5xx/transport → retry with bounded backoff, `dead` after `max_attempts`; 400/401/403/404 or a revoked credential → `unavailable`; lost eligibility → `cancelled`. Failed reads never write `unavailable` observation rows (they would hide earlier real values in `latest_observations`). Rows not reached before the step budget are released without spending an attempt. Wiring (`hosted_app.py`): with the flag on, `service.metric_reads` is attached and the worker hook becomes `with_time_back(then_schedule(audience.on_post_verified, metric_reads), time_savings)`; the cron handler runs `metric_reads.tick()` right after `worker.tick()` via `getattr`. `insights.ingest_post_insights` keeps its signature and now delegates to `fetch_post_insights` + `record_observations`. Preview pins `POSTRIFF_METRIC_READS`, `POSTRIFF_HISTORY_IMPORT` and `POSTRIFF_POST_DOCTOR` off (`deployment.isolated_environment`). PG proof: `tests/phase2/postgres_growth_metric_reads.py`.

Readers: `insights.latest_observations` now returns, per post and metric, the latest *available* reading and falls back to the latest reading only when none was ever available, so a later reading that lacks a metric never hides a real value. `summary` adds `readOffset` (t0/1h/24h/7d/backfill, or None for legacy rows; read via `to_jsonb` so pre-032 databases work) and `observedAt` to each metric; existing callers read `value` only and are unchanged. Still open for Phase 2 postmortems: cohorts do not include read age, so like-for-like comparisons should filter on `readOffset`. Operations: the cron snapshot adds `metricReadsOverdue` (pending/claimed > 10 min past due), `metricReadsDead24h` and `historyImportsFailed24h` (zero when 032 is absent); any non-zero count sets status `attention`.

### Stage 3A admission hardening (2026-10-03, supersedes the metric schedule admission above)

`MetricScheduler(..., workspace_allowlist=())` denies all work by default. Hosted production reads require both
`POSTRIFF_METRIC_READS=1` and an explicit UUID list in `POSTRIFF_METRIC_WORKSPACE_ALLOWLIST`. An empty, wildcard,
malformed or partially malformed list admits nobody. Claims filter at SQL level before consuming an attempt;
verified-post scheduling and authenticated Beta/tracking responses use the same workspace admission.

Scheduling, token acquisition, native insights GET and completion require a mounted, enabled,
`production_reviewed` Threads/Instagram adapter, a non-revoked credential bound to that provider, exact native
analytics scopes and `analytics=Direct`. Threads requires `threads_basic` and `threads_manage_insights`;
Instagram Login requires `instagram_business_basic` and `instagram_business_manage_insights`. A generic identity
or read-post scope is insufficient. Live introspection may reduce rights; cached grants never substitute for
current credential/capability checks. Completion takes the workspace/credential/capability locks that serialize
with disconnect/deletion, and retains the unexpired lease and attempt-generation fence. A purge appearing during
grant acquisition or completion retries owned-post reads and never appends data meanwhile.

Each bounded tick returns and logs content-free `providerReads`, `providerErrors` and `costUnknownReads` counters.
These count attempted native insights GETs, including transport failures, independently of committed observations;
OAuth introspection is a separate request. Native responses have no invoice, so logs retain `costUsd=null` and
`costSource=unknown`. The existing read/attempt/time bounds remain in force. This does not create a provider invoice
or assert zero cost. Unknown rights, scopes, adapter review, workspace admission or account deletion fail closed.

The `Growth metrics acceptance` CI gate exercises disposable PostgreSQL and actual browser/API/DB paths with
synthetic identities, publications and transports. It proves implementation behavior, never real provider review,
account ownership, live publication, elapsed +1h/+24h/+7d reads or creator lift. History import retains its separate
consent-copy and UI acceptance gate and stays off in production.

### History import (`growth/history_import.py`), flags `POSTRIFF_HISTORY_IMPORT` + `POSTRIFF_METRIC_READS` (both required, default off)

`HistoryImporter(connection_factory, oauth, *, transport, clock, monotonic, worker_id)`. Routes (only when attached): `POST /api/workspaces/{ws}/channels/{conn}/history-import` with `{"confirmed": true}` → 202 run status (interactive session only, `manage_connections`, throttle 5/hour, live Threads/Instagram credential, Direct analytics else 409 `analytics_required`; one active run per connection); `GET` same path → latest run status (`read`). Disabled → 404 `feature_disabled`. Cron: `history_import.tick(max_runs=2, max_seconds=20)` runs before the metric step. Listing uses the analytics grant (`threads_basic` / `instagram_business_basic` already in it) — no new scope: Threads `GET graph.threads.net/{v}/me/threads` (token in query, as insights), Instagram `GET graph.instagram.com/{v}/me/media` (Bearer header, as social_history). Up to 3 pages per tick, 12 pages (300 posts) per run, stop at 90 days before the request. Each page's `pr_owned_posts` upserts (metadata, caption length, https permalinks only — never caption text or hashes), one `backfill` reading per post (anchor = publish time, due immediately) and the cursor commit together, fenced on the run lease. 429/5xx/transport keep the cursor and back off (failed after 5 attempts); 400/401/403/404 or a revoked credential fail the run; lost eligibility cancels it. `oauth.disconnect` records a durable purge marker inside its transaction, then purges in a separate transaction after commit. Imported metadata, job-less observations and import readings are deleted; pending runs/readings are cancelled. Delayed purges fence new imports and retry independently of growth flags (see Review hardening below). Stage 3B supplies consent and review/request/status UX; production remains OFF until separately approved activation.

### Stage 3B customer contract (2026-10-03)

Channels exposes “Past analytics” only after the gated GET confirms availability. Opening or reading status never requests an import. Each request needs an unchecked, explicit metadata/analytics consent checkbox; retries of an uncertain POST reconcile with GET and never automatically repeat POST. Owner/admin `manage_connections`, interactive sign-in, live Threads/Instagram credentials, verified Direct analytics, and no pending purge are server requirements. Five requests/hour are scoped to workspace and actor; duplicate active requests return the existing run. A newly queued run audits `history_import.requested` with consent version `history-import.v1` and bounds, without captions, cursors or credentials.

The API returns fixed `windowDays=90`, `maxPosts=300`, `maxPages=12`, `pageLimit=25`, `purgePending`, latest run state/progress/failure/attempts/timestamps, and separate imported `metricReads` counts. A retrying run includes `retryAt`. Those read counts cover the connection’s retained imported history across requests, not only the latest run. Metadata completion does not imply analytics completion. Historical backfill readings are current platform readings, never reconstructed 1-hour/24-hour readings. Missing metrics stay unavailable. Provider overdelivery cannot exceed 25 processed entries/page, 12 pages/run or 300 processed posts/run. The request-time 90-day window also rejects future-dated posts. Pagination cursors remain opaque; malformed announced next pages produce incomplete coverage.

Consent/capability/purge copy follows the saved display preference: English (including en-GB), Traditional Chinese (Hong Kong/Taiwan), Simplified Chinese, Japanese, Korean, French, German, Spanish, and Brazilian Portuguese. Other content-language locales explicitly fall back to English. The status panel supports queued/running/retrying/done/failed/cancelled, purge, permission, throttling, unavailable status and mobile/keyboard states. Repeating a run requires another review and unchecked consent. Browser proof uses a disposable DB and synthetic provider/state fixtures; it does not prove live provider access or activate production.

Production gate for this release: `POSTRIFF_HISTORY_IMPORT=0`. Keep the Stage 3A metric-read setting unchanged. A separate [activation checklist](../../releases/rafii-history-import-stage3b-20261003/ACTIVATION_CHECKLIST.md) governs a later approved canary; this release performs no production import or schema migration.

### Backfill (`growth/backfill.py`)

`backfill_verified_jobs(connection_factory, *, now, window_days=90, max_workspaces=200, apply=False)` scans `state.phase2.jobs` (plain SELECT, no workspace row locks, skips `accountDeletion`) for verified Threads/Instagram jobs inside the window on Direct-analytics connections that have no reading yet, and schedules one `backfill` reading anchored at the verification time. Operator CLI `python -m postriff_phase2.growth.backfill [--apply]` (dry run by default, `POSTRIFF_DATABASE_URL` never printed). Running it against production is a separate approved operation. PG proof for both: `tests/phase2/postgres_growth_history.py`.

### Calibration profile (supersedes the `thresholds` / `calibrated=` arguments described above)

Targets (plan v3): weighted kappa ≥ 0.6 per language, calibrated ECE ≤ 0.08, Post Doctor p95 ≤ 1.5 s. Language groups live in `growth/lang.py` (`zh-HK`/`zh-TW`/`zh-MO`/`zh-Hant*` → `zh-Hant`, `en*` → `en`) and are shared by golden and Post Doctor, so a Cantonese fit applies to `zh-HK` drafts and never to English. `golden.evaluate` fits per dimension and per language: `fit = {thresholds, kappa_fit, kappa_cv, ece_cv, n, reason}`, where `ece_cv` is the *calibrated* ECE (isotonic score → P(label ≥ strong) fitted on training folds, applied to the held-out fold); the raw-score ECE is `ece_strong_raw`. `golden.calibration_profile(result, *, model, acceptance=None)` marks each language × dimension `accepted` only with ≥ 30 scored rows, `kappa_cv ≥ 0.6` and `ece_cv ≤ 0.08` (reasons `too_few`, `kappa_below_target`, `ece_above_target`) and records `latency = {p50, p95, target_p95_ms: 1500, met}`. CLI: `python -m postriff_phase2.growth.golden profile REPORT.json --model typesafe-ai/jev --out PROFILE.json`; `golden.load_profile(path, qs)` refuses another rubric's digest or malformed thresholds. `PostDoctorService(judgments, *, profile=None, ...)`; `check(...)` no longer takes `calibrated`. Accepted thresholds apply per dimension, only in their own language group, only to primary judgments from the profiled model; `DimensionResult.calibrated` says which. Overall confidence counts as calibrated only when all nine dimensions are accepted; otherwise it stays `low` (`uncalibrated_language`, plus `partly_calibrated` when some are). `compare` stops on auth/budget/bad-request errors too and still writes the report (`stopped = {model, row, reason, spent_usd}`, reason `cap` or the error code).

### Review hardening (2026-09-26, supersedes earlier text where they differ)

- **Like-for-like readers.** `insights.COMPARISON_BASIS = "24h"`, `insights.TRIGGER_BASIS = "1h"`. `latest_observations(cur, ws, basis=None)` / `summary(..., basis=None)`: display (analytics) keeps the latest available values. Comparisons read every post at one age, legacy rows without an offset keeping today's behaviour: coworker hypotheses and anomalies, the evergreen pick and `learning_service.latest_metrics_by_job` (performance notes) at +24h; the campaign strong-post trigger at +1h, so `withinDays=1` can still fire. Coworker counts (weekly notification, view) use basis None so recent and backfilled posts are still counted. The offset is read from the column once 032 exists (`insights.read_offset_column`: presence cached per process, absence re-checked at most every 5 minutes via `pg_attribute`), else NULL. Coworker `refresh` makes two indexed per-workspace reads (like-for-like and counts); that is deliberate and bounded by `performance_cron`'s batch. Only an entry whose `accepted` is exactly `true` is validated and applied.
- **Claim order.** `MetricScheduler.claim` takes, in turn, expired leases, due fresh verification readings, then due import/backfill readings — each an index range scan on its own partial index (`pr_metric_reads_lease`, `_due_fresh`, `_due_backfill`) that stops at the remaining LIMIT and never scans rows not yet due, so imports and backfills (anchored weeks back) never delay fresh t0/1h/24h/7d readings. `schedule()` revives `cancelled` rows (fresh attempts, new due time) and leaves every other state alone; `backfill` treats cancelled rows as absent. Fences use the uuid key (`id=%s::uuid`).
- **Operations.** Growth counts appear only while `POSTRIFF_METRIC_READS=1`: `metricReadsOverdue` counts fresh verification readings > 10 min past due; `metricBackfillStale` counts import/backfill readings still pending a day after `scheduled_at` (reset when a cancelled row is revived).
- **Purge.** Nothing is purged inside `oauth.disconnect`'s transaction: it holds the workspace row FOR UPDATE, while the import and metric steps lock their own rows first and then key-share-lock the workspace row for their inserts, so any purge there could deadlock. Instead the disconnect calls `mark_for_purge` (one insert into the service-only `pr_growth_purges`, own savepoint, logged, never raises; `requested_at` keeps when the purge was first owed) and, after its transaction commits, `purge_after_disconnect` purges in a fresh transaction (lock timeout 2 s, statement timeout 5 s; on failure the marker stays with backoff). While a marker exists nothing new happens for the connection: `request` → 409 `history_purge_pending`, a claimed or storing import run stops, and `MetricScheduler` cancels the connection's import readings while readings of Rafii's own posts wait and retry (`failure_class='purge_pending'`) — the purge never touches them and a cancelled t0/1h/24h reading could never be taken again. `purge_connection(cur, ws, conn, imports_only=False)` locks in the import step's order (runs, owned posts, readings), deletes the import's job-less reading rows (their locks fence an in-flight completion), cancels import runs, deletes job-less observations of imported posts and the owned posts; without `imports_only` it also cancels every pending reading of the connection. Readings of Rafii's own posts (job_id set) are never deleted, and reviving a cancelled row never relabels a job's reading as import data. The cron retries owed purges via `sweep_pending_purges` whatever the growth flags say (one connection when idle, one transaction per marker, 10 s step deadline, bounded exponential backoff with the error class recorded). The operations snapshot counts `historyPurgesPending` (owed for more than 10 min) whatever the flags say.
- **No caption hash.** `pr_owned_posts` keeps `caption_chars` only; `caption_sha256` was removed from 032 (unapplied anywhere) because a hash of a short caption can be guessed. The `read_offset` check is added only when missing, so re-running 032 never re-validates observations.
- **Paging.** `list_page` returns `incomplete=True` when `paging.next` has no usable `cursors.after`; that page's posts are stored and the run then fails with `incomplete_paging` (a malformed `paging` without `next` is a normal last page).
- **Chat rejections.** `ServerModelRuntime._call` keeps the provider status on `_Rejected.http_status` (additive). `chat_from_runtime` maps 401/403 → `auth`, 402 → `budget`, 400/413/422 → `bad_request`; the router records the attempt and raises `RouterError` with that code without trying further models, and `JudgmentService` does not degrade them. Thinking models keep `output_cap(model)` headroom (reasoning counts inside `max_tokens`).
- **Latency.** `RouterEvaluation.elapsed_ms` / `RouterError.elapsed_ms` / `Judgment.elapsed_ms` measure the whole wait (attempts, pause, fallbacks, timeouts); golden p50/p95 use it.
- **Calibration profile.** Each accepted entry ships `isotonic` (fitted on all rows; `ece_cv` is its cross-validated ECE), so the gated calibrator is the deployed one; `DimensionResult.p_strong` is that calibrated P(rated ≥ strong) for calibrated dimensions only — internal, never displayed as a score. Profile format version 2. The profile's `model` is the single model that served the golden run (`served_models`); mixed or none is refused. `post_doctor.validate_profile` (also used by `golden.load_profile`) checks digest, types, finite ascending thresholds and a finite non-decreasing calibrator on [0, 1], raising only ValueError.
- **Comparison money.** `--max-usd` must be finite and > 0 and prices finite; unknown-cost attempts are charged at the *requested* model's estimate (per-model ledgers), reported as `spend.counted_usd`; the Jev model is pinned (`POSTRIFF_JEV_MODEL` cannot change it); estimates add `TYPICAL_REASONING_TOKENS` output per call for thinking models.
- **Backfill.** `backfill_verified_jobs(..., batch_size=200)` walks all workspaces by keyset pagination (`--batch-size`), one transaction per batch.


### Outcome validation replaces hand labels as the Phase 0 ground truth (decided by James, 2026-09-26)

James chose to validate Post Doctor against how public posts actually perform instead of labelling ~200 posts himself. `growth/outcomes.py` evaluates judgments against **within-creator relative engagement**: outcome = log1p(likes + reposts + quotes + replies) − that creator's median, so audience size, niche and posting habits cancel out; each creator's top and bottom thirds are the "top" and "bottom" classes. Rules and pass criteria were fixed **before any data was collected** (`outcomes.PREREGISTERED`), per language group (Traditional Chinese and English separately):

- at least 15 creators, each with at least 20 eligible posts;
- Spearman ρ between Post Doctor's overall score (mean of the dimension scores it could compute) and the within-creator outcome ≥ 0.10, with the lower bound of its 95% interval above 0 (2,000 bootstrap resamples over creators, fixed seed);
- AUC separating each creator's top third from their bottom third ≥ 0.56.

The report also gives per-dimension ρ and ρ on text-only posts (media is recorded as `has_media`), for diagnosis only. What it does not show: which dimension caused a post's performance; dimension levels stay uncalibrated (confidence stays low) until hand labels or Rafii's own measured posts exist. It shows association, never causation.

Data: `scripts/growth_collect_bluesky.py` reads Bluesky's public, open AppView (no login, no writes, rate limited) on James's Mac and writes outside the public repository (default `~/Documents/rafii-outcomes/`). Selection, fixed in advance: original posts only (no reposts or replies), 7–365 days old, ≥ 80 characters (English) or ≥ 30 (Cantonese: at least one Cantonese particle, no simplified-only characters), creators with ≥ 20 such posts, their 60 most recent; creators are stored as a hash of their DID. Meta (Threads/Instagram) and X data are not collected: their terms forbid automated collection outside official APIs; Threads can be added through the official Threads API once Meta's review grants keyword search / profile discovery. `compare --outcomes FILE` runs the same capped, dry-run-by-default comparison and writes the pre-registered report (`groups.<lang>.passes` / `reasons`).

**Widened by James the same day** ("more platforms, users and languages; Web APIs and scripting approved"). Collectors: `scripts/growth_collect_bluesky.py run-all` (public AppView; en, zh-HK, zh-TW, ja, ko, es, pt, de, fr) and `scripts/growth_collect_mastodon.py run-all` (public REST API of 16 large servers; only accounts listed in their server's opt-in profile directory, skipping `noindex` / non-`indexable` accounts, bots, groups, non-public or content-warned posts; counts read from the home server). Shared, pre-fixed rules live in `scripts/growth_collect_common.py`: language is read from the text (CJK by script, Cantonese by particles, simplified-only characters excluded from Traditional; Latin-script languages also need the platform's language tag), and every file is refused inside a git checkout. Each **language group** is gated separately with the same pre-registered criteria (`groups`); `platforms` and `platform_languages` apply them as diagnostics. A creator's baseline never mixes platforms. `compare --outcomes FILE [FILE ...] --max-creators N --max-posts M` takes a seeded, deterministic sample per platform and language to fit the approved budget (`--max-posts` ≥ 20). Still excluded: Threads, Instagram, Facebook, X and Xiaohongshu (their terms forbid automated collection outside official APIs; logged-in scraping would put James's accounts at risk), and Reddit (no compliant anonymous route).

**Link feeds excluded (fixed before any scoring, 2026-09-26).** A creator is left out when at least 80% of their posts are "mostly a link" (a URL with fewer than 60 characters of their own words once URLs, hashtags and mentions are removed): automated news or aggregator accounts are not the writers Post Doctor serves. Recorded in `outcomes.PREREGISTERED["exclude_link_feeds"]`; `summarize` reports how many were excluded per cell.
