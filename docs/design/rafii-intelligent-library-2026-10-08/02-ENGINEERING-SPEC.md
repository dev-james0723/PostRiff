# Rafii Intelligent Library — Engineering Specification

Date: 2026-10-08 · Implementation authority: full approved scope R01–R20.
This document defines proposed contracts and new module names; it does not assert that those APIs already exist.

## 1. Baseline and compatibility
The preceding conversation inspected remote `consumer-saas` Library components and the merged Universal Library PR #116. It found private normalized assets, search chunks, collections, source-policy gates and a separate image/video path. The inspected Agent search used at most 200 newest admitted assets and Python word matching. Audio playback existed while automatic transcription was described as unavailable. Thumbnail code generated decorative waveform bars from a hash and used text covers for some document types.

These are dated, path-specific observations, not a claim about every current deployment. Current local file reads verified the repository identity but not its freshness. Existing branches named for Library production fixes and document previews are present in Git config. Before implementing, inspect latest base and relevant open/merged work so current fixes are reused rather than regressed. Evidence details are in `06-EVIDENCE-AND-DELIVERY.md`.

### Existing integration points to reconcile, not blindly replace
`web/src/features/library/{library-view,use-library,asset-card,asset-list-row,asset-detail,asset-thumbnail,library-organizer,use-upload-queue}`; `web/src/lib/api/{client,types}`; `web/src/lib/media/{asset-kinds,now-playing}`; `web/src/features/now-playing/now-playing-bar.tsx`.

Backend paths inspected earlier: `src/postriff_phase2/{library_assets,library_extract,hosted_app,hosted_storage}.py`; `src/postriff_phase2/site_agent/{library_reads,tools}.py`; `src/postriff_phase2/agent_runtime_v2/{specialists,tool_adapter}.py`; `source_policy` and existing Memory/voice routes. Existing migration IDs 093–096 belong to the Universal Library work. Never reuse those IDs or rewrite already-applied migrations.

Inspect `AGENTS.md`, `CLAUDE.md`, current Token Pilot policy, test scripts, API conventions, model routing, cost accounting and the parallel OpenUI integration before creating new infrastructure. Package paths absent in the current checkout must be resolved against current Git state, not recreated from a stale copy.

## 2. Architecture decision
Extend the existing private asset lifecycle. Use a shared permission-aware Library intelligence service under proposed package `src/postriff_phase2/library_intelligence/`. UI, Agent tools, task source packs and background suggestions call the same service; they must not each maintain their own SQL or source-policy interpretation.

Keep Postgres as the authority for assets, versions, consent, jobs and relationships. Use its existing lexical indexes plus a versioned vector-index adapter for multilingual text and visual similarity. Reuse a deployed vector facility if present; otherwise evaluate Postgres/pgvector in a disposable database and record extension compatibility. Do not introduce an independent vector service without a recorded need and authorization. Official Supabase hybrid-search documentation is a reference for combining lexical and semantic candidates, not proof of the user's current configuration [E6].

Store bytes and rendition objects privately in the existing object store. Durable asynchronous workers run bounded extraction, ASR, visual analysis and embedding through the existing provider/cost abstraction. Keep basic file browsing independent of model availability. No always-running local Mac media farm; default heavyweight processing and CI to the established cloud build/worker system, with local controls and permitted browser verification retained.

## 3. Invariants
- Workspace and actor identity come from authenticated server context, never trusted from generated UI or client parameters.
- Every original has a stable asset identity and immutable content-version identity. Title, original filename, summary and extracted content remain separate fields.
- Storage access, AI egress, retrieval purpose, memory admission, style learning and public-use approval are separate checks. A new grant is explicit, scoped, revocable and auditable.
- Every derivative references asset version, content hash, extractor/model version, creation time and status. Human corrections are layered and not erased by re-analysis.
- A match is not a fact approval, and a fact approval is not an ownership determination. Unknown rights must not render as cleared.
- No cross-tenant deduplication leak, embedding leak, count leak, suggestion leak or action replay. Storage-only files are not sent for remote embedding.
- No infinite model correction, retry, re-ingest or notification loops. All jobs and mutation actions have idempotency identities and bounded retry policies.
- An old citation continues to identify the old source version; a source update flags dependent work rather than silently rewriting it.
- Preserve existing upload quotas and MIME/byte validation. Prior normalized limits were 50 MiB/file and 1 GiB/workspace; re-read configured limits and do not silently raise them. Long media needs an explicitly designed resumable/size policy, not bypasses.

## 4. Data model (proposed additions)
Map these entities onto existing normalized tables where compatible. Avoid duplicate truth stores.

| Entity | Required fields/behavior |
|---|---|
| AssetVersion | workspace_id, asset_id, version_id, sha256, source_kind, original_filename, display_title, mime, bytes, created_at, original object key, soft-deletion marker; immutable source bytes. |
| CapabilityState | version_id, capability (`preview`, `extract`, `transcribe`, `visual`, `embed_text`, `embed_visual`, `understand`), state, progress data when measurable, error_code, retryable, job_id, completed_at. |
| SourceGrant | actor/workspace, asset or collection scope, purpose, allowed processing location/provider category, consent revision, validity/revocation, author attestation where relevant. Collection changes cannot silently broaden a fixed-scope grant. |
| ContentSegment | segment_id, asset/version, text, language, locator, extractor version, text hash, speaker label if applicable; retain offset alignment through correction versions. |
| UnderstandingAnnotation | entity/segment, field, value, evidence refs, origin (`extracted`, `ai_suggested`, `user_confirmed`), optional calibrated model confidence, manual override, model/version, updated_at. |
| EmbeddingRecord | segment/frame/version, modality, model id, dimensions, index generation, consent revision, lifecycle status; never mix incompatible model vectors. |
| CollectionDefinition | manual/smart, schema version, normalized rule tree, display explanation, revision, owner, include/exclude overrides, last evaluated generation. |
| AssetRelation | from/to asset versions or permitted segments, relation (`derived_from`, `version_of`, `similar_to`, `used_in`, `supersedes`), evidence and author; derived/version lineage acyclic, similarity edges need not be. |
| VoiceSample | persona/brand/language, author attribution method, approved text spans/locators, status/revocation, consent revision, source hash; no third-party auto-admission. |
| SourcePack | pack_id, task/draft id, selected asset/version/segments, evidence purpose vs style purpose, selection rationale, gaps/warnings, creator, revision. |
| ArtifactRegistration | producing run/job, durable output id, source pack, final/scratch classification, content hash, ingestion idempotency key; one final output registration per version. |
| Suggestion | dedup key, workspace/recipient, trigger, candidate refs, reason, state, snooze/dismissal/suppression and expiry, consent revision. |
| UsageEvent | asset/version/segment, permitted draft/post/channel identity, event type/time, source attribution, available metrics with timestamps; missing data explicitly null. |
| IntelligenceJob | workspace/version/capability, idempotency key, input/consent/index revisions, lease/heartbeat, attempts, admission/budget reservation, timings, error category and cleanup outcome. |

Use existing asset UUID conventions. Public contract IDs are opaque strings; conversion between dashed/undashed forms belongs in one adapter with tests. Do not apply ad-hoc `replace('-','')` throughout new code.

## 5. Stable contracts (v1)
Implement these as typed, validated contracts in `library_intelligence/contracts.py` and matching frontend types. If the existing app already has equivalent canonical contracts, extend them rather than introduce competing types.

**AssetRef**: `{assetId, versionId, sha256}`.

**Locator**: discriminated union `{kind:'page', page:1-based, section?, textStart?, textEnd?}`, `{kind:'time', startMs, endMs}`, `{kind:'text', start, end}`, `{kind:'slide', slide:1-based}`, `{kind:'sheet', sheetName, cellRange}`, or `{kind:'imageRegion', frameTimeMs?, x,y,width,height}` with normalized coordinates. Validate nonnegative bounds and version consistency. Where the parser has no trustworthy page mapping, show section/paragraph/text locators rather than fabricate page numbers.

**Purpose**: `browse | answer | draft_evidence | voice | memory | public_use`. Processing permission is a separate `ProcessingGrant` covering local/cloud and capability/provider category.

**SearchRequest**: `{query, scope:{kind:'workspace'|'collection'|'selection', collectionId?, assetRefs?}, purpose, filters, modes:['lexical'|'semantic'|'visual'], similarTo?:AssetRef, cursor?, limit}`. Default limit 30, max 100; the limit constrains returned pages, not the candidate universe. Filters include file type, tags, created/upload times, rights/approval, usage, aspect/orientation, duration, collection, language and capability status. Parse time zones explicitly for date boundaries.

**SearchResponse**: `{queryId, hits:[{assetRef, segmentId?, locator?, displayTitle, snippet, matchReasons, capabilities, sourceStatus}], nextCursor, coverage:{scopeDescription, accessibleAssetCount, indexedAssetCount, pendingAssetCount, failedAssetCount, modesApplied, partial, indexGeneration}, warnings}`. All counts are restricted to the same authenticated/purpose-admitted scope. Never reveal existence or counts of assets the caller cannot access.

**AnswerResult**: `{answer, claims:[{text, sourceRefs:[{assetRef,segmentId,locator,quoteHash}], support:'supported'|'conflicting'|'insufficient'}], coverage, warnings}`. Refuse unsupported answers, identify source assertions, expose contradictions. A source ref is resolved by the server to a short-lived authorized viewer link, not a persistent signed URL stored in model output.

**UnderstandingCard**: `{assetRef, summary, topics, usefulSegments, suggestedUses, annotations, sourceStatus, capabilityStates}`. Every model-created field is identified as suggested; confidence is omitted when uncalibrated.

**TaskContext**: `{taskId?, draftId?, userGoal, audience?, channels?, locale?, personaId?, selectedSourceRefs, scope, purpose}`. It is a bounded context object, not permission to ingest the entire chat.

**SourcePack**: `{packId, revision, taskContext, evidenceRefs, styleRefs, rationale, gaps, rightsWarnings}`. The two reference sets are separate. Snapshot relevant grant/source revisions and revalidate on use.

**ActionEnvelope**: `{actionId, uiInstanceId, actionType, targetRefs, expectedRevision, idempotencyKey, payload}`. Auth context is not supplied by the model. Return `{status:'applied'|'requires_confirmation'|'conflict'|'denied', revision?, result?, warnings?}`. Server reconstructs allowed intent and validates every target again.

**RegisterArtifact**: `{runId, outputId, sourcePackId?, contentSha256, storageRef, mime, displayTitle, originalFilename, artifactRole:'final', parentRefs, idempotencyKey}`. Only an authenticated successful completion event can register a final artifact; reject temporary/scratch/tool-output paths and arbitrary remote storage keys.

## 6. Purpose and permission behavior
Browse permission permits the user to see a stored item; it does not imply permission to export its text to a model. Introduce or reuse a purpose matrix in `policy.py`. Existing legacy denials remain denials until explicitly upgraded. A manual private file may be browsable but not eligible for cloud embeddings or Agent answers.

Reading to answer a private question may be separately allowed without marking every statement as an approved brand fact. The answer must then attribute assertions to the source. `draft_evidence` and `public_use` preserve the existing fact review and publication gates. Inspiration references can inform an explicitly requested comparison but cannot silently become approved voice samples. A persona selection alone never broadens source grants.

Revocation increments a grant revision and immediately blocks newly initiated and in-flight delivery at server/tool/download boundaries. Cancel queued work, invalidate retrieval caches, detach voice exemplars, tombstone indexes and suppress suggestions. Before returning a response or finalizing a derivative, recheck current revision to prevent a consent time-of-check/time-of-use race. Already exported material and external provider retention cannot be magically recalled; record those limits honestly.

For high-sensitivity derived previews use a revocable authenticated proxy. Existing short-lived signed URLs may remain valid until expiry; document the maximum residual window and do not claim instantaneous object-store revocation. Never put those URLs in logs, permanent source packs or model-readable fixtures.

## 7. Ingestion, understanding and media pipeline
Lifecycle: validate/store original -> deterministic metadata -> safe preview -> structural extraction/transcription/visual analysis -> normalized segments -> permission-gated embeddings -> understanding suggestions -> collection evaluation/task availability. Each capability has its own state; do not collapse everything into Ready.

States per capability: `not_requested`, `queued`, `processing`, `ready`, `partial`, `unsupported`, `failed`, `cancelled`, `blocked_permission`, `blocked_budget`. A failure in transcription does not hide the playable original. No fake percentage when only a queued/running state is known.

Jobs are keyed by workspace, asset version, capability, processor version and relevant consent revision. Lease workers with heartbeat and stale-lease recovery. Default max attempts 3 with backoff/jitter and provider Retry-After support. Retry only retryable failures; permission revocation and corrupted input require a state change, not repeated charges. Use the existing queue/cron system rather than launching another scheduler by default.

Documents: preserve digital text and structure first; select OCR only for image-only or demonstrably incomplete pages. Store OCR text with its provenance and uncertainty, never overwrite reliable embedded text. Office documents require genuine renditions for page/slide labels; otherwise show an honest extracted-text preview and a structural locator. Sandbox converters with no outbound network, macro execution or unbounded decompression.

Audio: extract waveform peaks from real decoded samples, independent of model analysis. ASR provider adapter must support the actual languages; evaluate Cantonese, Traditional Chinese, English and code-switching. Store timestamps and editable anonymous speaker labels. Do not infer known identities. Enable users to save a real moment with a valid interval and grant checks. Unsupported codecs are a clear state with original download, not invented transcript text.

Video: generate private posters, duration, real transcript segments and bounded scene/keyframe analysis. Index visual semantics and visible text where necessary; do not analyze every frame indiscriminately. Scene suggestions reference actual time spans. Image descriptions concern visible content, composition and text; do not infer sensitive traits or identify people from appearance.

Link/quick-note ingress shares the same validation, metadata and consent pipeline. Notes have explicit authorship. Link fetches must block local/private IPs and metadata endpoints, check redirects/DNS rebinding, allowlist protocols, cap bytes/time, preserve source URL/retrieval time and fail honestly for login-only or inaccessible links. Use existing authorized connector import paths rather than copying browser secrets or bypassing access controls.

## 8. Search and grounded answers
The candidate universe is all eligible indexed segments in the requested scope, not an in-memory list of the latest assets. SQL/vector permission filters run before ranking and before sending content to external rerankers. Bound each ranking operation while preserving access to older documents; record approximation/coverage rather than asserting exhaustive semantic recall.

Combine exact filename/title/id/hash/dimensions matches, language-appropriate lexical matching and semantic candidates. Implement a versioned multilingual normalization/tokenization strategy: do not rely on English stemming for Chinese. Keep visual embeddings in a compatible modality-specific index; textual captions are useful fallback but do not count as implemented visual similarity.

Default proposed fusion: exact identity matches first, then rank fusion with configurable constant 60 and equal lexical/semantic weights; apply hard filters before ranking. Persist ranking config/version and evaluate it instead of presenting scores as calibrated confidence. Optional reranking is permission/budget-gated and must not drop exact queries silently. If vector/model access fails, use labelled lexical-only results with honest `modesApplied`.

Use stable pagination with scope, query, index generation and permission revision binding. Expired cursors produce a recoverable refresh, not skipped/duplicated results disguised as completeness. Server computes totals/facets; the number of currently loaded cards is not total library size. Abort obsolete UI requests and isolate cache keys by workspace, actor permission revision, purpose and source/index version.

Answer generation retrieves bounded supporting segments from the eligible scope, never the entire library by default. Source text is untrusted data, not tool instructions. Sanitize snippets and viewer rendering; prevent document prompt injection from changing tools or exfiltrating files. Build citations from retrieved refs, check locators/hashes and distinguish contradictions. For an unanswerable query, state that the selected searchable material does not support an answer; expose pending/failed extraction without guessing.

## 9. Smart Collections, duplicates and lineage
Save a versioned, allowlisted rule AST rather than executable SQL or prompt text. UI shows an editable explanation and membership preview. Deterministic predicates and AI suggestions are distinct: model-suggested tags need clear provenance. Evaluate incrementally on relevant asset/annotation/usage changes and periodically reconcile missed events. Exclude overrides win over automatic membership; manual includes must still satisfy access rights. Undo creates a new revision and never restores revoked access.

Keep original/version/derived relations explicit and acyclic; cap traversal and guard cycles. `similar_to` is a suggestion, not a version identity. Exact hash deduplication remains within the workspace's authorized lifecycle. Near-duplicate recommendations never auto-delete or merge distinct edits. Version comparison supports text/metadata changes, image side-by-side and media segment references, with unsupported comparisons honestly labelled.

Record `used_in` on source-pack creation and actual draft/post transitions. Adding a version creates affected-source warnings for dependent drafts. User accepts a replacement through a revision-checked action; old citations remain bound to their original content.

## 10. Voice learning and task-aware creation
Implement source roles (user voice, brand facts, inspiration, storage only) as meaningful consent/purpose settings, not just tags. Sample admission requires user approval and explicit authorship/ownership assertion; an uploaded interview or generated text is not automatically the user's authentic voice. Allow span-level approval, negative examples and separate treatment of quoted speakers. Preserve raw originals.

Use the existing Rafii voice/profile system. Keep style exemplars separate from factual evidence, persona/brand/language scoped and versioned. Explain adopted style through examples, not an unvalidated percentage. A revoked/deleted sample is excluded from future retrieval and rebuilds any derived style summary that used it. Cache invalidation alone is not enough if a persistent profile summary still contains the sample.

Task-aware recommendation service accepts TaskContext and returns SourcePack candidates. Rank by task/audience/format relevance, permissions, currency, diversity and reuse freshness; rights are a constraint, not a score to trade away. Missing campaign evidence is a specific gap, not fabricated material. Never silently attach the entire Library to a prompt.

Library -> Agent/Ideas/Drafts passes actual selected asset/version/segment refs. Returning restores selection, query, filters and scroll. Agent-generated final output registration is idempotent and retains source-pack lineage. A failed upload remains retryable with the draft's source context intact; never claim a final asset was archived before the bytes and registration are verified.

## 11. Proactive librarian and outcome feedback
Use existing workspace event/automation infrastructure. Default delivery is an in-app suggestion list. Triggers include superseded sources in active drafts, failed processing, a relevant underused asset, missing approved inputs and reversible organization proposals. Debounce bursts and use a durable trigger/target/version deduplication key.

Default in-app digest: at most 3 new noncritical suggestions per recipient in 24 hours; urgent permission/source-integrity warnings may bypass that cap but remain deduplicated. Dismiss suppresses that suggestion identity; snooze defaults to 7 days and is editable; category disable persists. External email/push or schedules require explicit opt-in and existing quiet-hour controls. This specification does not turn any notifications on now.

Usage outcomes are descriptive: show channel/post/time and available metrics, with source timestamp and unknown values preserved. Do not assign causality to an asset from a post's success. Ranking can consume evidence of relevance and user acceptance, but should include diversity and recency controls. Expose why a recommendation appeared and allow correction.

## 12. Operations, costs, migration and rollback
Each inference job reserves against existing workspace budgets; missing budget authorization blocks paid work rather than inventing a cap or opening a new account. Record model/provider/configuration, input units, output units, latency, retries, actual cost if returned, estimated cost if calculated and unknown when unavailable. No synthetic price claims. Keep content/PII out of telemetry by default.

Monitor per-capability success/partial/failure, queue age, stale leases, retries, bytes processed, coverage/index lag, query latency, citation locator failures, authorization denials, source-pack-to-draft success, duplicate registration suppression, suggestion dismissals and cost by feature. Include workspace/trace/version identifiers that do not expose content.

Migrations are additive and use newly reserved unique IDs under a single migration owner. Test legacy photo/video plus normalized document/audio rows together. Backfill in bounded, resumable, cost-admitted batches with dry-run counts. No production backfill or egress without approval. Preserve canonical deletion/reference-count invariants, including sibling duplicate refs. A failed migration or partially indexed model generation must not break original downloads or current searches.

Feature flags separately guard enrichment, new retrieval, voice admission, recommendations and OpenUI task surfaces. Shadow retrieval may compare results only for eligible sources and authorized processing. Rollback disables new readers/workers and returns to working behavior while retaining original data and a recoverable migration state; do not silently reintroduce unsupported completeness claims. Production readiness is assessed on candidate SHA plus actual environment. A production release, if separately authorized, requires canary, authenticated smoke paths, regression evidence, a rollback point and a release receipt.
