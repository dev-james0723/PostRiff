# Growth Trends release, lane A: Bluesky ingestion recovery to verified projections

Branch `claude/trends-ingestion-recovery-20261009`, based on `a522482e` (production at the time),
draft PR [#139](https://github.com/dev-james0723/PostRiff/pull/139) against `consumer-saas`.
Backend only. No production database, cursor, flag or Vercel environment change was made.
The integrator merges and deploys.

## 1. Root causes

| # | Cause | Status | Evidence |
|---|---|---|---|
| R1 | **Poison-pill cursor stall since 2026-10-04T01:25Z.** A record-level contract failure on the frame after Jetstream seq 26613419375 was quarantined and `fold_frames` stopped (`break`) without advancing. v2 cursors are inclusive, so every later batch was "re-sent seq 26613419375 + the same poison at index 1". | Verified (offline repro + production shape) | `providers/bluesky.py:89-95,103` (pre-fix); production 3h buckets 72 batches / 72 items / 72 quarantines at index 1, 0 new observations; both cursor partitions at 26613419375 (gen 439/440) |
| R2 | Receipts hid the poison's real cause: codes outside `quarantine.REASONS` collapsed to `invalid_record`. Most likely `timestamp_must_be_utc` (a valid atproto `createdAt` with a non-UTC offset), which `contracts.instant` rejects. | Likely (raw code not recoverable) | `contracts.py:68-69`, `quarantine.py:17-21,53` |
| R3 | **CursorTooOld since 2026-10-05T13:50Z.** About 36.5h after the stuck event, the cursor fell below Jetstream's 36h live window. The server answers HTTP 400 `{"error":"CursorTooOld"}` before the upgrade; websockets 16.1.1 raises `InvalidStatus`, which the worker could not classify (status read only from `urllib.error.HTTPError`), so it retried as transient and ended `provider_attempts_exhausted` every slot. | Verified (live probe of the stuck cursor, official lexicon); the 13:50Z exception class itself was never logged | `worker.py:283-285` (pre-fix); lexicon `subscribeEvents.json` errors; production 576 jobs / 1728 failed connections per 24h |
| R4 | **No circuit breaker.** Terminal decisions wrote `next_allowed_at=NULL`; planner, frontier, worker and claim gate only on `next_allowed_at`/revoked, so jobs were recreated every 5 minutes forever. | Verified | `retry.py:114-117`, `source_health.py:14-18` (pre-fix). Read-only check 2026-10-09T01:17Z: 2002 terminal failures since the last batch (2026-10-05T13:45:24Z), max gap 6 minutes |
| R5 | **v2 `#account` markers read flat.** The lexicon nests `active/status` under `account`; `marker['active']` was always `None`, so `revoke_author` never fired. The test fixture encoded the wrong flat shape. | Verified from code + official lexicon | `bluesky.py:38-41`, `tests/test_trend_providers.py:37-39` (pre-fix) |
| R6 | **Contract renewal never reached materialization.** Observations stored `provider_contract_version` = the runtime protocol (`jetstream-v2-json@3fa54fdb...`) while the only live policy points at the renewed review row `stage2-full-20261003-v2`. `pipeline._sources` requires `pc.version = o.provider_contract_version` (never true), so all 879 `trend.ingested` events returned `suppressed/no_current_sources`. `trend_node_valid` (migration 040) and `store._storage_current/_statuses` judged rows against the protocol-named row, which expired 2026-10-05 (0/344 valid). | Verified | `store.py:237-239`, `pipeline.py:195-197`, `040:303`; production evaluation 0/335 vs 335/335 under protocol equivalence |
| R7 | Pipeline outcomes were invisible: `outbox.consume` discarded the effect result; suppression and success both looked like consumer state `done`. | Verified | `outbox.py:121-130` (pre-fix) |
| R8 | Expired legacy rows inside the 28-day window would mark every new receipt `truncated` (until 2026-10-11 retention). | Verified from code | `pipeline.py:215` (pre-fix) |

**Correction to the critic's "process root cause".** The seven `POSTRIFF_TEST_DSN`-gated trend modules are skipped in
`ci-python`, but they are **not** silently skipped in CI: the `tests/phase2/postgres_trend_*.py` wrappers load all 21
DSN-gated trend modules under the disposable database and fail on any skip. Run 37854718767 (PR #136) `ci-postgres.log`:
`postgres_trend_pipeline` ran 16 tests OK, `postgres_trend_planner` 53, `postgres_trend_advanced` 43, and so on, with no
skips. The real gap was fixture shape: every Postgres fixture registered contracts with an empty manifest, so the runtime
version always equalled the review-row id and a renewal was never exercised.

## 2. Fixes

| Fix | Files | Behaviour |
|---|---|---|
| F1 poison pill | `providers/bluesky.py`, `quarantine.py` | Record-level failures on a valid commit create/update (record shape, `createdAt`, text, size) are quarantined with the precise code and the cursor advances past them. Envelope failures (no valid seq/DID/kind, unusable `#account`, malformed delete identity, unknown operation) and policy-wide contract failures (e.g. `invalid_knowledge_or_retention_time`) still stop before advancing. `createdAt` with an RFC3339 offset is converted to UTC (already-UTC values keep their exact string); naive/garbage values are quarantined. `langs` null/non-list/non-str gives `und`. An undecodable frame is quarantined as an envelope failure instead of failing the job. `quarantine.REASONS` now keeps every code the fold can emit (`bluesky.QUARANTINE_CODES`, asserted by a test). |
| F2 CursorTooOld | `providers/bluesky.py`, `providers/base.py`, `worker.py` | `InvalidStatus` with HTTP 400 and allowlisted JSON `error=CursorTooOld` (body read bounded to 4 KiB, never logged or chained) re-anchors **once** without a cursor inside the same time budget and returns a leading marker `{kind:gap, reason_code:cursor_too_old, previous_sequence}`, completeness `gap`, health reason `stream_cursor_reanchored`. `#info OutdatedCursor/FutureCursor` become explicit gap reasons. Other non-101 statuses, handshake/connection errors and closes before any frame raise `ProviderTransportError(status, close_code)`; a close after frames keeps the partial sample. The worker passes the status to `retry.fail_attempt` (4xx terminal, 5xx/None transient) and logs only `code`, exception class and status. `maxMessageSizeBytes=65536` (lexicon name verified at the pinned commit) matches the client `max_size`. `trend.ingested` keeps the reason as `marker_counts.gap_cursor_too_old` (no raw marker). |
| F3 circuit breaker | `retry.py`, `source_health.py`, `planner.py`, `worker.py` | A terminal failure of a *dispatched* provider attempt sets `next_allowed_at = now + 15m / 1h / 6h / 24h cap`, escalated by consecutive breaker openings since the last committed batch (bounded query over `pr_trend_jobs` + `pr_trend_ingestion_batches`; failures less than 14 minutes apart are one opening, so the pre-fix every-5-minute loop counts once). One `trend.circuit_open provider=.. reason=.. cooldown_seconds=..` line per opening. `source_health.record` never replaces a later `next_allowed_at` with NULL/earlier (`greatest`), except the explicit success path `clear_pause=True` after a committed batch (still `observed_at`-ordered). Half-open: after a lapsed, uncleared pause, planner/frontier/replay admission allows at most one in-flight ingest job (`source_probe_in_flight`). Stall detector: 3 consecutive committed batches with an unchanged non-empty cursor and the same first quarantine index record `gap/cursor_stalled` plus the escalating cooldown; the counter lives in worker-owned `cursor_value._stall`, stripped before the adapter sees the cursor. |
| F4 nested markers | `providers/bluesky.py`, tests | `#account` reads `data.account.active/status` (status allowlisted to lexicon known values), `#identity` reads `data.identity.handle`; a missing/invalid `account` object stops before advancing (deactivation decision unknown). `#identity/#sync` are never filtered. The fixture is now nested; the flat shape is tested to produce no revocation decision. |
| F5 contract binding (no DDL) | `store.py` | `put_observation` keeps the runtime-protocol check, then stores `provider_contract_version` = the authorizing policy's reviewed contract row and `provenance.runtime_protocol` = the protocol (only when they differ). `observation_id` (uuid5 of scope/provider/source/revision), `payload_digest` and dedup identity include neither. `pipeline._sources`, `trend_node_valid`, `_storage_current`, `_statuses`, `forecast_admission.py:298` and `forecast_evaluation.py:192` therefore bind to the renewed row with no code or SQL change. The 344 stale rows are left for retention (2026-10-11T01:19Z). |
| F6 observability | `outbox.py`, `worker.py` | `consume` returns `effect: {state, reason}` from allowlisted enums (`complete/ignored/suppressed/replayed/unknown`; `different_event_type/no_current_sources/no_eligible_posts/no_eligible_membership/event_node_invalid`). `tick` returns `pipeline: {consumed, outcomes}` and logs one `trend.pipeline state=.. reason=.. count=..` line per outcome class (WARNING for suppressed/unknown so it is visible at the default level; INFO otherwise). |
| F7 truncation hygiene | `pipeline.py` | Purged, retention-expired and expired-but-not-revoked-contract rows are excluded from both candidate CTEs. Rights, revocation and deletion denials remain candidates and still mark the receipt `truncated`. |
| F8 CI coverage | `tests/phase2/postgres_trend_unittests.py` | Auto-discovered by `scripts/postriff_pg_suite.py` (runner sets `POSTRIFF_TEST_DSN`). Maps every DSN-gated `tests/test_trend_*.py` module/class to the wrapper that loads it, fails if a wrapper loading gated tests does not fail on skips, and runs any uncovered gated module/class under the disposable DSN, failing on failure or skip. Today: 21 gated modules, all covered, so it runs 0 extra tests rather than duplicating ~5 minutes of suites. |

Throughput (from code and a read-only check): `TrendWorker.tick` consumes the outbox **before** planning and ingest
(`worker.py`), so the pipeline is not starved by ingestion; ingest is the step that yields when the 20s budget is used.
Production at 2026-10-09T01:17Z: unconsumed `trend.pipeline.v1` backlog 0; 864 `trend.frontier.decision` events per 24h
(~0.6/min) against a capacity of 2 events/minute. Healthy ingestion adds about 0.4 `trend.ingested`/min. No scheduling
change was made. Watch item: a large `trend.ingested` event can take most of one tick, which then skips that tick's ingest;
this is self-limiting (no ingest means no new events).

## 3. Tests

Added or changed (all offline unless marked PG; PG cases run only in CI under the disposable database):

- `tests/test_trend_providers.py` (BlueskyV2): inclusive-cursor redelivery + poison advances to the last seq (production
  seq 26613419375); record-level codes advance; systemic failures and envelope failures stop; offset `createdAt` normalized;
  `langs` guards; nested `#account/#identity/#sync`; flat account shape refused; `#info` names; `maxMessageSizeBytes`;
  CursorTooOld re-anchor (websockets 16.1.1 `InvalidStatus(Response(...))` constructed to pin the API) with explicit gap,
  empty live tip, second rejection; typed errors without body or chained cause; connection close codes; partial sample on
  late close; undecodable frame. The `marker()` fixture is now the nested lexicon shape.
- `tests/test_trend_retry.py`: record-level codes survive receipt sanitization; fold codes subset of `REASONS`; escalating
  cooldown 900/3600/21600/86400 and the single log line; transient and pre-dispatch failures do not open the breaker.
  PG: terminal failures escalate, NULL/earlier writes cannot shorten the pause, half-open blocks a second job, only a
  committed batch clears and resets escalation.
- `tests/test_trend_planner.py`: planner skips slots during cooldown and admits a single probe after; fakes extended.
- `tests/test_trend_worker.py`: nested inactive account from a real fold revokes the author; typed status reaches retry
  classification and logs class/status only; success clears the breaker; stall detector (3 batches, cooldown,
  escalation, reset, adapter never sees `_stall`); pipeline outcome aggregation with bounded labels.
- `tests/test_trend_pipeline.py`: offline gap-reason counts and bounded outbox effect summary. PG `RenewedContractPipeline`
  (production shape: protocol-named row expiring, renewed row valid, completeness `gap`, `scheduled:<64hex>` epoch):
  with `marker_counts` gives manifests, memberships, a `trend` projection and `verified` receipts, observations bound to the
  renewed row with the protocol in provenance, still valid after the protocol row expires, and `revoked/policy_revoked` once
  the renewed row is revoked; without `marker_counts` and with expired legacy rows present, the receipt is not truncated and
  legacy rows are excluded; no eligible sources gives `suppressed/no_current_sources` and zero artifacts.
- `tests/phase2/postgres_trend_unittests.py` (new guard).

Local runs (Python 3.14 venv; the pinned websockets wheel added to `PYTHONPATH` only for the local run):
`test_trend_providers` 52 OK, `test_trend_retry` 36 OK (10 PG skipped locally), `test_trend_worker` 65 OK,
`test_trend_planner` 23 OK (3 PG skipped), `test_trend_pipeline` 21 OK (14 PG skipped). `test_trend_providers` also passes on
Python 3.12. Postgres and full regression ran only in GitHub Actions.

## 4. CI evidence

Code head `48e92503bc31c9e4052bd75b16699c15d6db0dd0` (PR merge ref `c301632f`), pull_request event, 2026-10-09:

| Workflow | Run | Conclusion |
|---|---|---|
| Rafii local release gates (consumer-ready.yml) | 37868963206 | success |
| Growth metrics acceptance | 37868963202 | success |
| Growth Studio browser acceptance | 37868963250 | success |
| Universal Library release validation | 37868963232 | success |
| Rafii Generative UI | 37868963360 | success |
| Rafii browser scenes | 37868963187 | success |
| Founder admin browser | 37868963210 | success |

consumer-ready gates (artifact `local-gates-c301632f...`, every record `sourceUnchanged=true`): ci-python PASS (335s),
ci-postgres PASS (690s; 105 suites, 0 non-zero exits), ci-web, ci-trend-schema, ci-types, ci-lint, ci-build, ci-copy,
ci-python-artifact, ci-secrets, ci-session-cache, ci-browser, ci-performance, ci-history-import all PASS.
Inside ci-postgres: `postgres_trend_pipeline` 21 tests OK including the 3 `RenewedContractPipeline` cases;
`postgres_trend_planner` 59 tests OK including the breaker escalation/half-open PG case; `postgres_trend_unittests`
reported 21 gated modules, 0 uncovered, 0 wrappers without skip failure; all other `postgres_trend_*` suites exit 0.

The final head's run (after this document commit) is reported on the PR and in the lane report.

## 5. Remaining risks

- The poison frame's original code is unrecoverable; F1 handles every record-level code. If the real cause were systemic
  (policy/clock-wide), the fold now stops and the stall detector opens the breaker with `cursor_stalled`, visible in
  `pr_trend_source_health.notes_code`, instead of looping.
- A record-level failure that hits *every* record (for example a future Jetstream record-format change) would quarantine
  and advance through all of them. The precise quarantine codes and `accepted_count` make this visible, but it is not
  automatically paused.
- `#account` events without the nested object now stop the fold (fail-closed for deletion compliance). If live Jetstream
  ever sends the flat shape, ingestion stalls and the breaker opens (`cursor_stalled`) rather than silently skipping
  revocations. Live `#account` frames were not observed (the probe saw 15 commits).
- The uncovered interval from seq 26613419375 to the new live tip is permanently a gap (recorded as `gap_cursor_too_old`).
  Deletes in that window were never applied to the 344 stale rows; they are already invalid and purge on 2026-10-11T01:19Z.
  An earlier purge is a destructive decision for the integrator.
- Breaker escalation counts openings since the last committed batch. If the first post-deploy probe still fails, it gets
  15 minutes (the 2002 legacy failures form one opening); later failed probes escalate to 1h, 6h, then 24h.
  `next_allowed_at` is only cleared by a committed batch, so after a fixed redeploy a 6h/24h pause would need either the
  wait or an authorized production write.
- Receipts read the 3 completed hours before the cutoff: expect non-empty current windows only after 1-3 completed hours of
  fresh ingestion. `put_method` still forces `shadow`, so lifecycle stages stay unqualified (lane C/product decision).
- Both planner (`frontier:`) and discovery (`discovery:`) partitions sample the same live stream; each re-anchors once.
- The source policy and contract expire 2026-11-03; observation retention is capped by policy expiry. A renewal must add a
  new reviewed contract row with `manifest.protocol` equal to the pinned protocol; F5 then binds new rows to it, and
  `RenewedContractPipeline` guards that path.

## 6. Post-deploy acceptance (read-only)

Run on project `buoyhkbodnhzngaotoel` inside `BEGIN TRANSACTION READ ONLY; ... ROLLBACK;`. Replace `<DEPLOY_AT>` with the
production deployment `READY` time (UTC) of the merge SHA. Aggregates only; no post text, DIDs or tokens.

A1. Cursor moved past the stuck sequence (both partitions, within 1-2 cron cycles):

```sql
SELECT partition_key, generation, (cursor_value->>'sequence')::bigint AS seq, cursor_value ? '_stall' AS stalled,
       coverage_state, updated_at
FROM public.pr_trend_provider_cursors WHERE provider_id='bluesky' ORDER BY updated_at DESC;
-- expect: updated_at > <DEPLOY_AT>, seq > 26613419375, stalled = false
```

A2. Explicit re-anchor gap recorded (expect one per partition):

```sql
SELECT count(*) AS reanchored_events, min(created_at), max(created_at)
FROM public.pr_trend_outbox
WHERE event_type='trend.ingested' AND created_at > '<DEPLOY_AT>'::timestamptz
  AND coalesce((payload->'marker_counts'->>'gap_cursor_too_old')::int,0) > 0;
```

A3. New observations bound to the renewed contract row and currently valid:

```sql
SELECT provider_contract_version, provenance->>'runtime_protocol' AS runtime_protocol, count(*),
       min(available_at), max(available_at)
FROM public.pr_trend_observations
WHERE provider_id='bluesky' AND available_at > '<DEPLOY_AT>'::timestamptz GROUP BY 1,2;
-- expect only ('stage2-full-20261003-v2', 'jetstream-v2-json@3fa54fdbb0f47ad3aa43de78a6fbbd8dc362f81d')
SELECT count(*) AS sampled, count(*) FILTER (WHERE postriff_private.trend_node_valid(scope_key,observation_id)) AS valid
FROM (SELECT scope_key,observation_id FROM public.pr_trend_observations
      WHERE provider_id='bluesky' AND available_at > '<DEPLOY_AT>'::timestamptz
      ORDER BY available_at DESC LIMIT 200) s;
-- expect valid = sampled
```

A4. Quarantine codes are precise and the cursor still advances:

```sql
SELECT e->>'reason_code' AS reason_code, count(*)
FROM public.pr_trend_outbox o CROSS JOIN LATERAL jsonb_array_elements(o.payload->'entries') e
WHERE o.event_type='trend.quarantined' AND o.created_at > '<DEPLOY_AT>'::timestamptz GROUP BY 1 ORDER BY 2 DESC;
SELECT count(*) AS batches, sum(item_count) AS items FROM public.pr_trend_ingestion_batches
WHERE provider_id='bluesky' AND committed_at > '<DEPLOY_AT>'::timestamptz;
-- expect items > 0 and growing; invalid_record should no longer dominate
```

A5. Breaker not looping, no repeated failed_terminal (check over at least 6 slots = 30 minutes, then again after 3h):

```sql
SELECT state, error_code, count(*) FROM public.pr_trend_jobs
WHERE provider_id='bluesky' AND kind='trend.ingest' AND created_at > '<DEPLOY_AT>'::timestamptz GROUP BY 1,2 ORDER BY 3 DESC;
SELECT date_trunc('hour',created_at) AS hour, count(*) AS jobs,
       count(*) FILTER (WHERE state IN ('failed_terminal','outcome_unknown')) AS failed
FROM public.pr_trend_jobs WHERE provider_id='bluesky' AND created_at > '<DEPLOY_AT>'::timestamptz GROUP BY 1 ORDER BY 1;
SELECT status, notes_code, next_allowed_at, observed_at FROM public.pr_trend_source_health WHERE provider_id='bluesky';
SELECT status, count(*) FROM public.pr_model_usage_events
WHERE task='trend.ingest' AND created_at > '<DEPLOY_AT>'::timestamptz GROUP BY 1;
-- expect: mostly succeeded (about 24 jobs/hour across both partitions), failed small and not recurring;
-- source health partial/gap with next_allowed_at NULL; usage status mostly 'ok'.
-- If notes_code = 'cursor_stalled' or a provider_* terminal code with a future next_allowed_at: the breaker opened;
-- Vercel logs carry one 'trend.circuit_open ...' line and 'trend.job_failed ... exception=<Class> status=<n>'.
```

A6. Materialization after at least 1-3 completed hours of fresh ingestion:

```sql
SELECT kind, count(*) FROM public.pr_trend_projections
WHERE available_at > '<DEPLOY_AT>'::timestamptz GROUP BY 1 ORDER BY 1;
-- expect membership > 0, trend > 0, receipt > 0, metric_snapshot > 0
SELECT verification_state, payload->'coverage'->>'completeness' AS completeness, count(*)
FROM public.pr_trend_trust_receipts WHERE decision_cutoff > '<DEPLOY_AT>'::timestamptz GROUP BY 1,2;
-- expect verified; completeness gap/partial, not truncated
SELECT count(*) AS manifests FROM public.pr_trend_input_manifests WHERE decision_cutoff > '<DEPLOY_AT>'::timestamptz;
SELECT method_id, count(*) FROM public.pr_trend_method_versions GROUP BY 1 ORDER BY 1;
-- expect trend.pipeline and the trend.* implementation methods to appear
SELECT c.state, count(*) FROM public.pr_trend_outbox_consumers c JOIN public.pr_trend_outbox e USING(scope_key,event_id)
WHERE c.consumer='trend.pipeline.v1' AND e.event_type='trend.ingested' AND e.created_at > '<DEPLOY_AT>'::timestamptz GROUP BY 1;
-- and Vercel logs: no recurring 'trend.pipeline state=suppressed reason=no_current_sources'
```

## 7. Needs from other lanes / integrator

- None blocking for lane A's code. No change was needed in `trends/service.py`, `http.py`, `beta.py`, `config.py`,
  migrations or `web/*`.
- Integrator: deploy lane A early (production burns about 576 failing jobs/day until then), capture same-SHA evidence, then run
  section 6. Do not reset `pr_trend_provider_cursors` by hand; F2 re-anchors automatically.
- Lane C/UI: `pr_trend_source_health.notes_code` can now be `cursor_stalled`, `stream_cursor_reanchored` or a terminal
  provider code with a future `next_allowed_at`; show it as "source paused" rather than empty data. `trend.ingested`
  `marker_counts.gap_cursor_too_old` marks the uncovered interval.
- Retention (`trends/retention.py`, not lane A): its scrubber allowlist of `trend.ingested` keys is unchanged and still
  matches (new counts live inside `marker_counts`).
