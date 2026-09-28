# WP13–18 pure API coordination

All production modules are under `src/postriff_phase2/growth/trends`. Public entry
points take one JSON dictionary and return a fresh JSON dictionary. No I/O, model,
database, publisher, downloads, credentials or runtime provider dependencies.

Common evidence input: `scope_key`, timezone-aware ISO `decision_cutoff`, `sources`
(at most 10,000). Each source has `source_id`, `scope_key`, `platform`, `event_at`,
`available_at`, explicit `original`, and `rights` with explicit boolean `analysis`,
`creative`, `display`, and modality grants when applicable. Optional `expires_at`,
`revoked`, `deleted`, `canonical_id`, `creator_key`, `text`. Missing grants deny.
Availability and event time must precede the cutoff; current revocation overrides
historical visibility. Source IDs are scope-local; creators remain platform-scoped.
Assignments and derived evidence need `available_at` and `evidence_refs`.

Implemented entry points (coordinator integration may import these directly):

- `context.build_context_bundle`, `narratives.build_narrative`, `narratives.link_episodes`
- `graph.project_graph` (edges, dependent claims and list/table projection)
- `genome.build_genome`, `copy_density.measure_saturation`, `whitespace.find_whitespace`
- `opportunity_lab.freeze_run`, `opportunity_lab.evaluate_run`,
  `opportunity_lab.project_run`, `opportunity_lab.select_patches`
- `exposures.build_lineage`, `exposures.creator_baseline`
- `media_extraction.check_media_eligibility`, `creative_patterns.build_creative_pattern`
- `platform_priors.resolve_prior`, `spread.project_spread_hypotheses`
- `forecast.predict_baselines`, `forecast.evaluate_forecasts`,
  `forecast.rolling_origin_evaluate`, `forecast.qualify_forecast`

Lab selection returns proposed patches and revision/approval-invalidating metadata;
it never applies edits. Storage/authentication, atomic revision checks, adoption,
existing approval/publish integrations, API routing and jobs belong to other owners.
Forecast qualification requires explicit independently supplied preregistered,
non-fixture cohort evidence; deterministic fixture passes never qualify a method.
The competitor CLI is research-only and offline; missing product observations are
`NOT_RUN`, never invented provider rows. No production handler imports that harness.

Tests: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_trend_advanced.py'`
and the analogous `opportunity_lab`, `forecast`, and `competitor` suites.

## Store and canonical API adapters

`genome`, `graph`, `copy_density`, `opportunity_lab`, `forecast`, `whitespace` each
export `to_stored_projection(result)`. This takes an already computed pure result;
it performs no retrieval or recomputation. It returns the fragment
`{kind, method_id, method_version, payload}` for the persistence owner to bind to
the complete input manifest, receipt, object/revision, available_at and retention.
Kinds are `genome`, `graph`, `saturation`, `lab_run`, `forecast`, `whitespace`.
Method IDs are `trend_<kind>_pure`; method version is `"1"`. These are candidate
identifiers, not registered or qualified methods. Registration is another owner.

The first four payloads match canonical `genomeSchema`, `propagationSchema`,
`saturationSchema`, and `labRunSchema`. The complete frozen Lab result must also be
retained privately with its digests for `project_run`; the thin wire payload alone
is deliberately insufficient for stale checking. The canonical document currently
does not define forecast or whitespace schemas. Their adapters return explicit
internal payloads: forecast is unavailable with no predictive values; whitespace
contains admitted gap candidates, not fabricated workspace Opportunity objects.
Service maps admitted gaps through its own Opportunity creation contract.

Lab calls require `workspace_id`, common evidence inputs, `target_platform`,
`idempotency_key`, and server-resolved `draft`, `opportunity`, `context`, `receipt`.
Draft has `id`, integer `revision`, `workspace_id`, `saved=true`, `text`, and
`allowed_platforms`. Opportunity has matching `draft_id`, `context_revision`,
`trust_receipt_id`, integer `revision`, `workspace_id`, `allowed_platforms`,
`available_at`, `expires_at`, `verification_state=verified`, `evidence_refs`.
Receipt has `id`, `scope_key`, availability/expiry/verification/evidence fields.
Context has `revision` (opaque string or server digest), `workspace_id`, approved
facts/context. `freeze_run` returns `kind=lab_run`, `schema_version=1` and
`state=unavailable`, `failure_reason=evaluation_not_executed`. `evaluate_run` takes
these inputs plus `run` and optional evidence-linked `findings`, returning the
real deterministic evaluation as `completed`, `execution_state=pure_deterministic`.
No pure function represents job enqueueing or paid capability. Missing durable
handler remains a service 503. `project_run` requires fresh server objects and
suppresses diagnostics on changed digests, linkage, methods, rights or expiry.
The wire field `context_revision` preserves the server digest unchanged.
