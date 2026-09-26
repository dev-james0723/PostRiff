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

Integration details (existing functions, cron order, table columns) are appended below once the code map is complete.
