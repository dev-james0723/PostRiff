# WP13–18 pure implementation handoff

State: implemented offline candidate behavior, **unqualified**. No commits,
network/model calls, media downloads, DB migrations, publisher mutation or edits
to another worker's files. Worktree:
`/Users/ouxianxing/.codex/worktrees/social-trend-intelligence/James-Au-Studio`.

## APIs and integration

See [ADVANCED_API.md](ADVANCED_API.md) for input contracts, pure entry points,
server-resolved Lab bindings, and stored projection adapters. All functions consume
JSON dictionaries and return fresh dictionaries. Source rights and availability
are explicit; current revocation overrides historical replay.

`to_stored_projection(result)` is implemented in genome, graph, copy_density,
opportunity_lab, forecast and whitespace. Kinds: `genome`, `graph`, `saturation`,
`lab_run`, `forecast`, `whitespace`. Method IDs: `trend_<kind>_pure`, version `1`.
The fragment is `{kind, method_id, method_version, payload}`; the persistence owner
must attach the full manifest/dependencies, receipt, revision and retention fields.
Registration/qualification of these candidate method IDs was not performed.

Lab wire diagnostics match UI Zod: dimension, assessment, claim, evidence_refs,
comparison_frame, uncertainty, requires_user_fact and nullable suggested_edit
`{id,before,after,reason}`. Runs carry expires_at, context_revision and
trust_receipt_id. Preserve the complete frozen result/digests privately for
project_run. Server context_revision is an opaque value and can be the existing
context digest. Map server platform_targets to the explicit allowed_platforms
inputs on both the saved draft and opportunity. Snapshot creation is unavailable /
evaluation_not_executed, not an invented queue event; actual pure evaluation uses
completed / pure_deterministic. Missing durable handler remains service 503.
Selected patches are proposals for existing variant_edit with revision/digest
checks and approval invalidation; they never apply or publish anything themselves.

## Verified results

Executed separately from the worktree root with socket.socket,
socket.create_connection and urllib.request.urlopen blocked within each suite:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_trend_advanced.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_trend_opportunity_lab.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_trend_forecast.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_trend_competitor.py'
```

Results: **28 + 16 + 14 + 12 = 70 passing tests**. These include exact 100/80/20
coverage/occupancy and 19/80 redundancy, transitive graph source-loss invalidation,
provider-scoped creator identity, future cutoffs, partial/overlapping context,
opposing stances, missing modalities, real supplied keyframe/timecode references,
weak-demand rejection, saved/context/receipt Lab races, user-fact rejection,
published-only lineage, changed treatment, creator-relative baseline exclusions,
embargo/seasonal alignment, censoring, quantile loss/calibration, paired episode
qualification failures, frozen imports, detector arithmetic and non-identifiability.

```sh
node scripts/competitor_bench/check_projection_contracts.cjs
```

PASS: four generated projections against the actual UI Zod schemas and competitor
manifest against its JSON Schema. Python AST/JSON parsing and whitespace checks
also passed for all code/fixtures present at validation.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/competitor_bench/report.py \
  tests/fixtures/trends/advanced/competitor.json \
  --output-dir /private/tmp/trend-advanced-wp13-18/tests/fixtures/trends/advanced/offline_report
```

PASS: offline report generated. A copy is under
`tests/fixtures/trends/advanced/offline_report/`: manifest.json, observations.json,
candidate-results.json, matched-comparison.json and report.md. Product observations
are **NOT_RUN**; validated user outcomes and production qualification are NOT_RUN.
All detector inputs are explicitly synthetic. The grid has 30 frozen synthetic
topics and language/query/window/geography perturbations; it is not field research.

## Changed paths

Under `src/postriff_phase2/growth/trends/` only:
context.py, narratives.py, graph.py, genome.py, copy_density.py, whitespace.py,
opportunity_lab.py, exposures.py, creative_patterns.py, media_extraction.py,
forecast.py, platform_priors.py, spread.py.

Under `scripts/competitor_bench/`: ADVANCED_API.md, HANDOFF.md,
manifest.schema.json, import_observations.py, run_candidates.py, report.py,
check_projection_contracts.cjs.

Tests: tests/test_trend_advanced.py, tests/test_trend_opportunity_lab.py,
tests/test_trend_forecast.py, tests/test_trend_competitor.py.

Fixtures: tests/fixtures/trends/advanced/{saturation,lab,forecast,competitor,projections}.json
and tests/fixtures/trends/advanced/offline_report/{manifest,observations,candidate-results,matched-comparison}.json
plus its report.md.

## Remaining boundaries

- No claim of qualified semantic inference, originality, cultural interpretation,
  forecast quality, engagement lift or competitor replication from these fixtures.
  Narrative/genome/spread consume supplied evidence-linked assignments; semantic
  inference and independent native-language/human qualification are not executed.
- No ASR, OCR, video decoding or media-provider integration. The pure multimodal
  layer validates supplied extractions, references, rights, resource caps and
  timecodes; absent modalities remain unknown.
- Actual persistence/auth/job/budget/receipt adapters, source-deletion fan-out,
  existing approval/publishing hooks, UI/browser acceptance and PostgreSQL tests
  belong to the integrating owners. These pure tests do not establish those gates.
- The canonical API schema at inspection did not define forecast or whitespace.
  Their adapters are bounded internal contracts: forecast suppresses predictive
  values; whitespace returns grounded gap candidates for the service-owned
  Opportunity mapping. A qualified forecast wire projection remains gated.
- Contexts, raw evidence and frozen Lab inputs remain subject to store retention;
  hashes are identifiers, not permission to retain revoked content.

Token Pilot stayed stateless to preserve the explicit ownership restriction.
Provider/model calls: zero. Host token/cost totals and savings comparison: unknown.
