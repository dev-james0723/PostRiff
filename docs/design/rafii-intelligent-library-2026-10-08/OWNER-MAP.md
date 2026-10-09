# OWNER-MAP — Rafii Intelligent Library

One coordinator, at most four active implementation workers, one shared reviewer at a time. Each worker has its own worktree and branch, branched from the coordinator commit that froze the contracts. Only the coordinator merges into `claude/rafii-intelligent-library-20261008`. A worker that needs a change in another owner's file writes the request in its final report. It does not edit that file.

## Coordinator-only files (contract freeze; workers read, never edit)
- `src/postriff_phase2/library_intelligence/{__init__,contracts,policy,policy_http,versions,http,actions,api,providers,textnorm}.py`
  - Exception: `textnorm.py` may be extended by **C** (S/T table, tests). The interface `search_terms/query_terms/tsquery/NORMALIZER_VERSION` is frozen.
- `migrations/postriff/104_library_intelligence.sql` (renumbered from 097 on 2026-10-09; request schema changes from the coordinator), `tests/phase2/rls.sql`
- `src/postriff_phase2/hosted.py`, `src/postriff_phase2/hosted_app.py`, `src/postriff_phase2/site_agent/tools.py` (catalog text), `agent_runtime_v2/*`
- `web/src/lib/api/client.ts`, `web/src/lib/api/library-intelligence-types.ts`, `web/src/lib/api/types.ts`
- `scripts/library-cloud-validation.sh`, `scripts/library-intelligence-validation.sh`, and every lockfile/package/CI/vercel file. `vercel.json`, `web/package.json`, the lockfile, `.james-cloud-build.json` and `agent_runtime_v2/http.py` belong to the OpenUI coordinator; this team sends patches and does not edit them.
- `docs/design/rafii-intelligent-library-2026-10-08/{BASELINE,OWNER-MAP,TEST-COMMANDS}.md`, `evidence/**`

## Workstreams, owned paths and interfaces

### A — Data/Policy (T02, T12)
Owns `library_intelligence/{jobs,capabilities,intake,lifecycle,telemetry}.py`, `tests/test_library_intelligence_{jobs,lifecycle}.py`, `tests/phase2/postgres_library_intelligence_jobs.py`. Also owns the **minimal hook** in `library_assets.py`: enqueue intelligence capabilities after commit/process and on delete. Keep it a few lines; PR #134 edits this file too.
- `capabilities.PROCESSORS: dict[capability, list[Processor]]`. Processor = `{"capability", "version", "location", "category", "applies(version)->bool", "estimate(job)->int usd_micro|None", "run(job)->Outcome"}`. B and C register processors by calling `capabilities.register(processor)` at import of their modules.
- `JobContext`: `workspace_id, actor, version (versions.* dict), raw() -> bytes` (bounded private-storage read with hash check), `providers`, `now`, `processor`, `consent_revision`.
- `Outcome`: `{"state": "ready"|"partial"|"unsupported"|"failed", "segments": [..], "annotations": [..], "embeddings": [..], "media": {..}, "provider": receipt|None, "errorCode", "detail", "retryable": bool}`.
- `jobs.enqueue_capability(ctx, ref, capability, processor_version) -> job` (idempotency key = workspace/version/capability/processor/consent revision); `jobs.complete_capability(ctx, job_id, result, expected_grant_revision) -> state` (rechecks the grant via `policy.recheck` before writing derivatives); `jobs.tick(intel, connect, *, max_jobs, max_seconds)`.
- Handlers referenced by `http.ROUTES`: `capabilities.capabilities_http`, `jobs.request_http`, `jobs.cancel_http`, `intake.link_http`, `intake.note_http`, `telemetry.status_http`.
- `lifecycle.propagate_revocation` exists (coordinator v1); A extends it with `revoke_or_delete_source(ctx, ref) -> receipt` (segments, embeddings, annotations, relations, packs, suggestions, voice spans, previews; preserving sibling duplicate refs).

### B — Media/Extraction (T03)
Owns `library_intelligence/{segments,media,understanding,ocr}.py`, `tests/test_library_intelligence_media.py`, `tests/fixtures/library_intelligence/media/**`, `tests/phase2/postgres_library_intelligence_media.py`.
- `segments.write_segments(cur, workspace_id, version, items, *, extractor, extractor_version) -> int`. It fills `search_terms` with `textnorm.search_terms`, never overwrites `origin='user'` corrections, and supersedes instead of deleting. `segments.correct(ctx, segment_id, text, speaker_label)` keeps history.
- `extract_segments(ctx, ref) -> SegmentBatch`, `build_waveform(samples) -> peaks`, `transcribe_asset(ctx, ref) -> TimedSegments`, `analyze_visual(ctx, ref) -> FrameAnnotations`, `build_understanding(ctx, ref) -> UnderstandingCard` (implementation plan T03).
- Registers processors: `extract` (structural PDF page/section, DOCX paragraph, XLSX sheet/cell, PPTX slide locators; OCR only for image-only pages), `preview` (duration/dimensions/real waveform peaks), `transcribe` (cloud ASR via `providers.transcribe`), `visual` (local perceptual features + cloud scene description), `understand`.
- Handlers: `understanding.card_http`, `segments.segments_http`, `media.waveform_http`; actions `media.save_moment_action`, `understanding.correct_action`, `understanding.metadata_action`. `understanding.card(ctx, ref)` is used by `api.read`.

### C — Retrieval (T04, T05)
Owns `library_intelligence/{index,search,cursors,answers,citations}.py`, `textnorm.py` (extend), `src/postriff_phase2/site_agent/library_reads.py` (adapter onto the shared search), `tests/test_library_intelligence_{search,answers}.py`, `tests/phase2/postgres_library_intelligence_search.py`, `tests/fixtures/library_intelligence/retrieval/**`.
- `search.search_library(ctx, request) -> SearchResponse`. UI, Agent and OpenUI share this one function.
- `index.write_embeddings(cur, …)` and processors `embed_text` (cloud gateway, grant-gated) and `embed_visual` (`local/visual-perceptual-v1` 256-d plus an optional cloud multimodal model).
- Cursors are signed and bound to scope, query, index generation and grant revision.
- `answers.answer_library(ctx, question, search_request) -> AnswerResult`; `citations.resolve_locator(ctx, ref, locator)`.
- Handlers: `search.search_http`, `answers.answer_http`, `citations.viewer_http`.

### D — Organization (T06, T11)
Owns `library_intelligence/{collections,relations,comparison,suggestions,usage}.py`, `tests/test_library_intelligence_{organization,suggestions}.py`, `tests/phase2/postgres_library_intelligence_organization.py`.
- Functions: `preview_collection`, `save_collection`, `link_versions`, `compare_versions`, `evaluate_suggestions`, `set_suggestion_state`, `asset_usage`, `reconcile_due(intel, connect)`, `evaluate_due(intel, connect)`.
- Handlers: `collections.preview_http`, `collections.collection_http`, `relations.related_http`, `comparison.versions_http`, `comparison.compare_http`, `usage.usage_http`, `suggestions.inbox_http`.
- Actions: `collections.{preview,save,override,undo}_action`, `relations.{link,accept_replacement}_action`, `suggestions.set_state_action`.

### E — Agent/Voice (T07, T08)
Owns `library_intelligence/{voice,source_packs,artifacts}.py`, `tests/test_library_intelligence_{voice,creation}.py`, `tests/phase2/postgres_library_intelligence_creation.py`.
- **Voice reuses the canonical system:** spans become `state.sources` `voice_sample` entries through the existing `voice_samples_import`, `voice_sample_grant` and `voice_sample_revoke` actions. `pr_library_voice_samples` indexes spans, polarity, persona and language only.
- Functions: `voice.withdraw_for_keys(ctx, keys) -> int` (called by `lifecycle`), `approve_voice_span`, `revoke_voice_sample`, `recommend_sources(ctx, task) -> SourcePack`, `attach_pack_to_draft`, `register_final_artifact(ctx, request) -> AssetRef`.
- Handlers: `voice.asset_voice_http`, `voice.summary_http`, `source_packs.recommend_http`, `source_packs.pack_http`.
- Actions: `voice.{approve_span,revoke}_action`, `source_packs.{select,create,attach}_action`.
- E sends the coordinator patch requests for Agent tool and creative/completion hooks. E does not edit them.

### F — UI (T09, T10)
Owns `web/src/features/library/**` except `document-viewer.tsx` and `gallery-media-preview.tsx` (PR #134), `web/tests/library-intelligence-*.test.cjs`, and `web/tests/library-intelligence-browser.cjs`.
- Consumes `client.ts` methods `library*` (coordinator) and the types in `@/lib/api/library-intelligence-types`.
- OpenUI: descriptors in `web/src/features/library/intelligence/openui/descriptors.ts` (zod v4, ordered keys, `actions: string[]`, writes only through injected `onAction`). No `@openuidev/*` import.
- Must keep `data-tour` hooks (`library-upload|library-filter|library-card|library-empty`) and the strings asserted by `web/tests/universal-library.test.cjs` and `library-consent.test.cjs`. If an assertion must change, report it rather than editing those tests.

## Waves (dependencies authoritative)
- **Wave 0:** T00 and T01 (coordinator). Contracts frozen at the commit that adds this file.
- **Wave 1:** A=T02, B=T03, C=T04, F=T09 (shell against contracts).
- **Wave 2:** C=T05, D=T06, E=T07, F continues.
- **Wave 3:** E=T08, D=T11, F=T10, A=T12.
- **Wave 4:** T13 then T14 (coordinator and reviewer).

## Local-resource rules for every worker
Allowed locally: focused Python unittest only (`PYTHONPATH=src:tests /Users/ouxianxing/Documents/James-Au-Studio/.venv/bin/python -m unittest test_library_intelligence_<area>`). Not allowed: `npm`, `node`, `npx`, `tsc`, `oxlint`, `next`, Playwright, Postgres clusters and `jcb` (the coordinator runs all cloud validation to avoid duplicate runs). Commit on your own branch by explicit path; never `git add .`; never push.
