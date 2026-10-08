# Rafii Intelligent Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Read the PRD and engineering/UI specifications first. Preserve the user's full scope and authority boundary.

**Goal:** Deliver the complete private, intelligent, voice-aware and task-connected Library, including all P0/P1/P2 work, without replacing working Rafii infrastructure.

**Architecture:** Extend the existing asset lifecycle with one permission-aware intelligence service, durable per-capability workers and shared retrieval. Integrate existing Memory/voice, Agent, Drafts and OpenUI systems rather than duplicate them.

**Tech stack:** Existing Python/Postgres private backend; existing Next.js/React/TypeScript frontend and native test tooling. Local package.json was observed with Node 24.x and npm 11.12.1; verify the implementation base's lockfile/runtime before running commands. New providers/versions are not preselected or provisioned by this plan.

**Spec:** `01-PRD.md`, `02-ENGINEERING-SPEC.md`, `03-UI-OPENUI-SPEC.md`, `05-ACCEPTANCE-MATRIX.md` in this package.

## Global constraints
Full R01–R20 scope. No prototype-only closure. No new consent from upload alone. No unbounded newest-N candidate cap. Immutable citations. Truthful processing/preview states. Original bytes and working media paths preserved. No autonomous public operations. No paid/provider activation without authorization. No blind reset/clean/stash/overwrite. New migrations have one owner. Stop this ChatGPT task at saved documents and handoff; implementation begins when James gives the execution prompt to the coding agent.

## Review focus
1. Access revoked while processing, streaming, cached retrieval or a generated action is already in flight: server must deny final delivery and derived writes (T01/T12).
2. Cantonese/English mixed speech, Traditional/Simplified text and old sources outside newest-200: results and locators must remain useful and truthful (T03/T04).
3. Corrected transcript or replaced document version: keep old citations and preserve human edits instead of shifting them silently (T03/T05/T06).
4. Retried completion event and replayed generated UI: exactly one final asset or authorized mutation, never repeat charges or auto-publish (T08/T10/T12).
5. iPhone keyboard, safe areas, player, drawer and reduced motion: no inaccessible or obscured selection/confirmation (T09/T13).

## Parallel execution policy
Use one coordinator, up to four active implementation workers, and at most one shared reviewer at a time. A–F below are logical workstreams, not a demand to launch six simultaneous expensive sessions. QA can prepare independent fixtures early; do not duplicate implementation audits per worker. Use a persistent task ledger and scoped evidence updates instead of repeatedly rereading the whole repository.

Only the coordinator merges cross-cutting changes to `hosted_app.py`, `web/src/lib/api/client.ts`, `web/src/lib/api/types.ts`, shared Agent dispatch, shared OpenUI registry, package lockfiles and migration numbering. A worker proposes interface changes in OWNER-MAP.md and waits for contract agreement before editing another owner's files. Each worker gets a separate worktree/branch and explicit allowed paths. Do not have multiple workers patch the same shared file or run production migrations independently.

Wave 0: T00 and T01. Wave 1: A runs T02, B builds media fixtures/adapters, C builds retrieval against contracts, F builds the stable shell against clearly labelled test fixtures. Wave 2: integrate real media/index, D runs T06, C runs T05, E runs T07; F continues API integration. Wave 3: E runs T08, D runs T11, F runs T10, A runs T12. Wave 4: T13 then T14. Dependencies in each task are authoritative. Stubs are temporary development aids, not acceptance evidence.

If the separate site-wide OpenUI project is active, share its existing contract and runtime. Library task components can be developed against that agreed interface while the runtime owner lands integration. Do not fork a competing OpenUI rollout. Work independent of a real provider blocker should continue; provider-dependent cases remain BLOCKED until a permitted live run succeeds.

## Time and cost discipline
Do not promise a next-day production result without measuring the starting state. The critical path is policy/contracts -> real ingestion/index -> grounded source packs -> integrated UI -> acceptance. Report progress by verified milestones and blockers, not a guessed percentage. Prefer cloud build/worker resources already configured; do not consume the Mac with unnecessary parallel builds, converters or duplicate reviewer sessions.

## Test-first task contract
The paths below are proposed destinations, except those explicitly described as existing integration points. T00 must reconcile them to current code once and record any necessary equivalent mapping. Backend tests can use Python unittest to avoid an unapproved dependency; align with the current repository's test conventions where required and register the exact equivalent command. Each task is independently reviewable and follows RED -> minimal implementation -> GREEN -> focused review -> scoped local commit when implementation authorization permits. Do not stage unrelated files with `git add .`.


## T00 — Reconcile current implementation and establish isolated ownership

**Owner:** Coordinator · **Depends on:** none · **Requirements:** R01,R16,R20

**Existing seams:** Inspect existing AGENTS.md/CLAUDE.md, Token Pilot instructions, git status/worktrees, current origin/consumer-saas, relevant Library and OpenUI branches, migration history and current authenticated Library. No shared-checkout edits.

**Create/update:** Create candidate-owned docs/design/rafii-intelligent-library-2026-10-08/BASELINE.md, OWNER-MAP.md and TEST-COMMANDS.md; copy this package into that worktree.

**Interfaces:** Consumes this saved package; produces exact base SHA, candidate worktree, exclusive file owners, current capability diff, lease status, resolved test commands and unchanged-source manifest.

- [ ] **1. Specify failing evidence:** baseline identifies whether the 200-candidate search, ASR and preview limitations still exist; records existing implemented equivalents instead of recreating them; captures current UI and test baseline without production writes.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `Run read-only git identity/status/worktree checks and inspect the existing CI scripts. Register exact backend/browser commands in TEST-COMMANDS.md. Verify no product files changed during discovery.`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T01 — Define contracts, versions and purpose-aware access

**Owner:** A — Data/Policy · **Depends on:** T00 · **Requirements:** R01,R02,R19

**Existing seams:** Modify existing asset/source-policy integration and reserve fresh migrations under migrations/postriff/. Coordinator alone edits shared hosted_app.py and API dispatch after contract review.

**Create/update:** Create src/postriff_phase2/library_intelligence/{__init__,contracts,policy,versions}.py and tests/test_library_intelligence_policy.py.

**Interfaces:** Produces AssetRef, Locator, Purpose, SearchRequest/Response, SourcePack, ActionEnvelope and authorize_source(ctx, ref, purpose, processing=None) -> decision, including grant/source revisions.

- [ ] **1. Specify failing evidence:** test_cross_workspace_denied, test_browse_does_not_grant_cloud, test_unapproved_fact_can_only_be_attributed_in_private_answer, test_revocation_before_delivery, test_locator_bounds, test_legacy_denials_preserved.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_policy.py' -v`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T02 — Build durable progressive processing and safe intake

**Owner:** A — Data/Policy · **Depends on:** T01 · **Requirements:** R01,R03,R04,R05,R06,R19

**Existing seams:** Extend current library_assets.py/library_extract.py through the shared service; preserve existing image/video uploads, validation and quotas. Use the deployed queue abstraction.

**Create/update:** Create library_intelligence/{jobs,intake,capabilities}.py and tests/test_library_intelligence_jobs.py.

**Interfaces:** Consumes AssetRef and SourceGrant; produces enqueue_capability(ctx, ref, capability, processor_version) -> job and complete_capability(ctx, job_id, result, expected_grant_revision) -> state.

- [ ] **1. Specify failing evidence:** test_duplicate_event_one_job, test_capability_partial_independent, test_restart_recovers_lease, test_retry_ceiling_three, test_cancel_before_finalization, test_budget_denial_no_call, test_link_ssrf_redirect_blocked, test_oversized_archive_rejected.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_jobs.py' -v`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T03 — Implement real document/audio/video understanding

**Owner:** B — Media/Extraction · **Depends on:** T01,T02 · **Requirements:** R03,R04,R05,R06,R17

**Existing seams:** Extend existing extraction/conversion/provider adapters; retain original bytes. Select existing authorized ASR/vision providers and record capability/model compatibility.

**Create/update:** Create library_intelligence/{segments,media,understanding}.py and tests/test_library_intelligence_media.py.

**Interfaces:** Produces extract_segments(ctx, ref) -> SegmentBatch, build_waveform(samples) -> peaks, transcribe_asset(ctx, ref) -> TimedSegments, analyze_visual(ctx, ref) -> FrameAnnotations, build_understanding(ctx, ref) -> UnderstandingCard.

- [ ] **1. Specify failing evidence:** test_digital_text_preferred_to_ocr, test_office_no_fake_page, test_waveform_depends_on_samples, test_transcript_alignment_after_edit, test_cantonese_english_segments, test_speaker_identity_not_inferred, test_no_provider_honest_blocked_state, test_manual_annotation_survives_reprocessing.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_media.py' -v`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T04 — Unify complete-scope hybrid and visual search

**Owner:** C — Retrieval · **Depends on:** T01; full integration T03 · **Requirements:** R07,R19

**Existing seams:** Replace the actual limited Agent retrieval implementation only after baseline confirms it; integrate existing UI library endpoint rather than create competing semantics.

**Create/update:** Create library_intelligence/{index,search,cursors}.py, extend site_agent/library_reads.py through adapters, and create tests/test_library_intelligence_search.py.

**Interfaces:** Consumes normalized segments and policy; produces search_library(ctx, request: SearchRequest) -> SearchResponse. UI and Agent consume this same function; visual mode uses compatible visual embeddings.

- [ ] **1. Specify failing evidence:** test_asset_1001_exact_match, test_old_segment_retrieval, test_permission_filtered_before_rank, test_chinese_and_code_switch, test_visual_not_caption_only, test_cursor_revision_refresh, test_no_count_leak, test_vector_failure_lexical_label, test_loaded_count_not_total.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_search.py' -v`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T05 — Ground answers and source viewers in immutable references

**Owner:** C — Retrieval · **Depends on:** T04,T03 · **Requirements:** R08,R12

**Existing seams:** Integrate existing Agent response/citation transport and authorized viewer route via coordinator-owned adapters.

**Create/update:** Create library_intelligence/{answers,citations}.py and tests/test_library_intelligence_answers.py.

**Interfaces:** Produces answer_library(ctx, question, search_request) -> AnswerResult and resolve_locator(ctx, ref, locator) -> authorized viewer target; no durable signed URLs.

- [ ] **1. Specify failing evidence:** test_unsupported_answer_abstains, test_conflicting_sources_exposed, test_source_update_keeps_old_citation, test_prompt_injection_has_no_tool_effect, test_expired_link_refresh, test_deleted_source_refused, test_partial_scope_disclosed.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_answers.py' -v`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T06 — Ship Smart Collections, version comparison and lineage

**Owner:** D — Organization · **Depends on:** T01; search membership T04 · **Requirements:** R09,R10

**Existing seams:** Extend current collection/metadata services and library-organizer integration through coordinator/F-owned UI seams. Never auto-delete near duplicates.

**Create/update:** Create library_intelligence/{collections,relations,comparison}.py and tests/test_library_intelligence_organization.py.

**Interfaces:** Produces preview_collection(ctx, rule, overrides) -> membership, save_collection(ctx, rule, expected_revision) -> collection, link_versions(ctx, relation) -> relation, compare_versions(ctx, refs) -> ComparisonResult.

- [ ] **1. Specify failing evidence:** test_incremental_membership, test_exclude_override_wins, test_no_byte_copy, test_rule_sql_rejected, test_cycle_rejected, test_near_duplicate_not_auto_deleted, test_concurrent_revision_conflict, test_changed_source_impacts_draft.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_organization.py' -v`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T07 — Implement consented voice samples and profile revocation

**Owner:** E — Agent/Voice · **Depends on:** T01,T03 · **Requirements:** R02,R11

**Existing seams:** Find and reuse canonical Memory/voice/persona services. Do not create a second voice memory store or learn from all uploaded text.

**Create/update:** Create library_intelligence/voice.py and tests/test_library_intelligence_voice.py; extend the canonical profile module identified by T00.

**Interfaces:** Produces approve_voice_span(ctx, ref, locator, persona_id, author_attestation) -> VoiceSample and revoke_voice_sample(ctx, sample_id, expected_revision) -> rebuild/invalidation result.

- [ ] **1. Specify failing evidence:** test_reference_not_voice, test_span_not_whole_document, test_generated_text_requires_approval, test_brand_language_isolation, test_negative_example_preserved, test_revoked_sample_removed_from_persistent_summary, test_no_unvalidated_voice_score.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_voice.py' -v`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T08 — Connect task source packs, drafts and final-artifact return

**Owner:** E — Agent/Voice · **Depends on:** T05,T06,T07 · **Requirements:** R12,R13

**Existing seams:** Use existing Agent context transport, Ideas/Drafts composer, completion events and permitted storage registration. Coordinator merges shared agent/tool adapter changes.

**Create/update:** Create library_intelligence/{source_packs,artifacts}.py and tests/test_library_intelligence_creation.py.

**Interfaces:** Produces recommend_sources(ctx, task: TaskContext) -> SourcePack, attach_pack_to_draft(ctx, pack_id, draft_id, expected_revision) -> result and register_final_artifact(ctx, request: RegisterArtifact) -> AssetRef.

- [ ] **1. Specify failing evidence:** test_evidence_style_separate, test_no_whole_library_prompt, test_source_pack_survives_navigation, test_missing_inputs_named, test_replayed_output_registered_once, test_scratch_not_ingested, test_ingest_loop_guard, test_changed_grant_blocks_draft_attach.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_creation.py' -v`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T09 — Upgrade Library shell, previews and accessible interactions

**Owner:** F — UI · **Depends on:** T01; live APIs T03,T04,T06,T08 · **Requirements:** R03,R05,R07,R09,R10,R11,R12,R16,R17

**Existing seams:** Own web/src/features/library/* and coordinated Now Playing changes. Do not modify global Rafii tokens or unrelated app pages.

**Create/update:** Create focused components under web/src/features/library/intelligence/ and web/tests/library-intelligence-ui.test.cjs plus library-intelligence-browser.cjs.

**Interfaces:** Consumes contract types and existing app API provider; produces stable overview/search/detail/source-pack/collection/version/suggestion surfaces with preserved route state.

- [ ] **1. Specify failing evidence:** test_single_add_entry, test_scope_visible, test_honest_document_preview, test_audio_no_autoplay, test_batch_partial_failure, test_drawer_focus_restore, test_bottom_bars_no_overlap, test_mobile_first_asset_visible, test_animated_counts_single_accessible_name.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `node --test web/tests/library-intelligence-ui.test.cjs; run the candidate library-intelligence-browser.cjs harness with its documented synthetic test identity; npm --prefix web run typecheck; npm --prefix web run lint`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T10 — Integrate safe task-specific OpenUI components

**Owner:** F — UI + Coordinator for runtime seam · **Depends on:** T09,T08; coordinate existing OpenUI owner · **Requirements:** R18,R02

**Existing seams:** Reuse existing site-wide OpenUI runtime/registry; F owns Library components, runtime owner alone changes shared registry/transport. Do not install competing versions.

**Create/update:** Create web/src/features/library/intelligence/openui/{registry,action-adapter,error-boundary}.tsx or align with existing conventions; create web/tests/library-intelligence-openui.test.cjs.

**Interfaces:** Consumes validated source data and ActionEnvelope; produces allowlisted task surfaces and a host dispatchLibraryAction(envelope) -> server action result with replay safety.

- [ ] **1. Specify failing evidence:** test_unknown_component_rejected, test_forged_target_denied, test_hydration_no_mutation, test_stale_revision_conflict, test_one_repair_only, test_component_depth_cap, test_partial_stream_preserves_selection, test_fallback_browsing_works.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `node --test web/tests/library-intelligence-openui.test.cjs; npm --prefix web run typecheck; npm --prefix web run lint`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T11 — Deliver quiet suggestions and descriptive usage feedback

**Owner:** D — Organization · **Depends on:** T06,T08 · **Requirements:** R14,R15

**Existing seams:** Reuse existing events/notifications/usage sources. Do not activate external notifications or autonomous publishing.

**Create/update:** Create library_intelligence/{suggestions,usage}.py and tests/test_library_intelligence_suggestions.py.

**Interfaces:** Produces evaluate_suggestions(ctx, event) -> Suggestion[], set_suggestion_state(ctx, id, action) -> state and asset_usage(ctx, ref) -> descriptive usage data.

- [ ] **1. Specify failing evidence:** test_digest_three_noncritical_per_day, test_event_replay_dedup, test_dismiss_and_snooze_persist, test_category_disable, test_external_opt_in_required, test_metrics_unknown_not_zero, test_no_causal_claim, test_diversity_avoids_repeated_winner.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_suggestions.py' -v`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T12 — Close lifecycle, cost and operational readiness

**Owner:** A — Data/Policy · **Depends on:** T02,T04,T07,T08,T11 · **Requirements:** R02,R19

**Existing seams:** Integrate existing deletion, budget, telemetry and worker operations. Coordinator alone lands migrations and shared hosting wiring.

**Create/update:** Create library_intelligence/{lifecycle,telemetry}.py and tests/test_library_intelligence_lifecycle.py; add feature-specific metrics to current observability system.

**Interfaces:** Produces revoke_or_delete_source(ctx, ref) -> lifecycle receipt and cost/job events with measured/estimated/unknown classifications; pause/resume and model-generation rollback controls.

- [ ] **1. Specify failing evidence:** test_delete_cascades_segments_vectors_previews, test_duplicate_sibling_survives, test_grant_revocation_during_job, test_no_secret_log, test_backfill_resumable, test_cost_not_double_charged, test_flag_rollback_preserves_original.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_lifecycle.py' -v`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T13 — Run full acceptance and cross-feature regressions

**Owner:** QA with Coordinator · **Depends on:** T03–T12 · **Requirements:** R01–R20

**Existing seams:** Use existing cloud CI entrypoint, disposable PostgreSQL/storage and authenticated preview. Own only QA fixtures/reports; do not rewrite failing implementation to hide failures.

**Create/update:** Create tests/fixtures/library_intelligence/, scripts/library-intelligence-validation.sh, web/tests/library-intelligence-browser.cjs as coordinated with F, and candidate evidence/acceptance-report.json.

**Interfaces:** Consumes immutable candidate SHA, TEST-COMMANDS.md and acceptance cases; produces per-case evidence and benchmark report plus desktop/mobile captures and real-device receipt.

- [ ] **1. Specify failing evidence:** all A001–A080 cases; the same SHA must pass policy/media/retrieval/voice/creation/UI/OpenUI/lifecycle integration, scale and existing Library/Agent/Memory/Drafts/Queue regressions.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `python -m unittest discover -s tests -p 'test_library_intelligence_*.py' -v; node --test web/tests/library-intelligence-*.test.cjs; npm --prefix web run typecheck; npm --prefix web run lint; npm --prefix web run build; execute registered PostgreSQL, browser and existing regression commands on the same candidate`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## T14 — Prepare release-ready evidence and stop at the correct boundary

**Owner:** Coordinator + one shared reviewer · **Depends on:** T13 · **Requirements:** R20

**Existing seams:** No production actions under document-only authority. Prepare migration order, dry-run evidence, canary plan, rollback identity and exact remaining approval needs.

**Create/update:** Create candidate docs/releases/rafii-intelligent-library-2026-10-08.md and final acceptance report, without claiming deployment.

**Interfaces:** Produces candidate SHA/branch, changed files, passed/failed/unverified/blocked cases, environment matrix, migration dry-run, preview reference, risks and authorized next step.

- [ ] **1. Specify failing evidence:** no unresolved required acceptance row hidden; no CI/candidate SHA mismatch; no mock labelled live; rollback preserves private original access; source/cost/security gates are included.
- [ ] **2. Run RED:** run the focused command below before implementation; record the expected missing/new-behavior failure separately from unrelated baseline failures. For T00/T14 use documented inspection/receipt checks rather than inventing a unit-test failure.
- [ ] **3. Implement:** deliver this task's interface and behavior from the engineering specification, in its owned files only; retain explicit failure and permission states.
- [ ] **4. Run GREEN and integration:** `Compare the candidate SHA across all receipts, verify every requirement mapping and have one final security/UX-integrity review. Production smoke tests run only when separately authorized; otherwise label that deployment gate NOT RUN / AWAITING AUTHORIZATION, not PASS.`. Expected result is successful exit and assertions satisfied; a skipped required test, missing dependency or mock-only provider is not a pass.
- [ ] **5. Close the task:** record changed files, SHA, actual commands, output/evidence, satisfied acceptance IDs and blockers. Under implementation authority make a focused local commit using explicit paths; no push/merge/deploy is implied. Coordinator accepts interfaces before dependent tasks consume them.


## Final handoff expectations

Execute the existing plan rather than write another proposal. Ask James only for genuinely missing credentials/consent, unavoidable manual actions, material conflicts or release authority. Continue independent approved tasks while a dependency is blocked, without hiding its acceptance gap. After T14 report the exact readiness state and next gated action. All required product features must be implemented and verified before saying the full upgrade is complete; deployment checks may separately remain awaiting release authorization.
