# Rafii Intelligent Library — Acceptance Matrix

Date: 2026-10-08. **All 80 cases are UNVERIFIED at document delivery.** This is a specification, not a report of tests performed.

## Evidence protocol
Allowed case statuses: VERIFIED, FAILED, UNVERIFIED, BLOCKED. VERIFIED requires exact candidate SHA, actual command or manual procedure, environment, result and evidence locator. A failed dependency may block dependent cases but cannot silently remove them. Mock/provider fixtures prove only their corresponding contract tests. End-to-end media intelligence additionally requires authorized real-provider processing and user-facing behavior.

All numeric targets below are proposed candidate acceptance thresholds. Benchmarks must record corpus, expected relevance judgments, model/index versions, language distribution, machine/network, concurrency, sample size and warm/cold measurements. An agent must not lower a threshold without a documented decision. Performance targets do not imply current production achieves them.

Use at least 1,001 assets for the old-asset correctness cases and 10,000 mixed assets for load evaluation, with two permission-isolated workspaces. Include text-rich and scanned documents, audio/video with code-switching, duplicated/updated/deleted assets and adversarial files. Freeze a 100-query semantic relevance set independently of the implementation; do not tune against and score only the same easy examples. Audio transcription quality is reported per language; usable moment retrieval and honest uncertainty are required, not an unsupported universal accuracy promise.

For real-device acceptance record device/browser version and interaction evidence without exposing personal files. A preview screenshot is not production verification. Production execution is separately gated (A080); no deployment permission is granted here. A candidate can be described as release-ready only when its applicable code/product cases pass and the release authorization is explicitly shown as pending rather than omitted.

## Case catalogue

### A001 — Mixed files retain originals and existing photo/video behavior
**Requirement:** R01 · **Task:** T02 · **Status:** UNVERIFIED

Upload representative PDF/DOCX/XLSX/PPTX/TXT/MD/HTML/JSON/CSV, supported images/audio/video and a generic file; compare stored hash/bytes and authorized downloads; no original lost.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A002 — Validation and limits remain enforced
**Requirement:** R01 · **Task:** T02 · **Status:** UNVERIFIED

Reject oversized, MIME-mismatched and corrupted input; preserve configured quota and per-file limits; no silent limit increase.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A003 — Upload retry is recoverable
**Requirement:** R01 · **Task:** T02 · **Status:** UNVERIFIED

Interrupt and retry supported upload flow; no duplicate registration/charge; partial failures do not discard successful items.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A004 — Workspace isolation
**Requirement:** R02 · **Task:** T01 · **Status:** UNVERIFIED

Attempt browse/search/read/preview/count/suggestion/pack/mutation across two workspaces; all unauthorized paths denied without identity or count leakage.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A005 — Browse does not authorize AI egress
**Requirement:** R02 · **Task:** T01 · **Status:** UNVERIFIED

Storage-only asset remains browsable; cloud transcription, embeddings, summaries and Agent retrieval remain blocked without appropriate grants.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A006 — Private reading is not public fact approval
**Requirement:** R02 · **Task:** T01 · **Status:** UNVERIFIED

Explicit private answer grant yields source-attributed answer; cannot mark facts approved or publish from that grant.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A007 — Purpose, author and provider grants remain separate
**Requirement:** R02 · **Task:** T01 · **Status:** UNVERIFIED

Inspiration, Memory, voice, processing location and public-use purposes do not become enabled through unrelated settings.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A008 — Revocation wins an in-flight race
**Requirement:** R02 · **Task:** T12 · **Status:** UNVERIFIED

Revoke after retrieval/job/action begins but before delivery/finalization; server rechecks revision and blocks delivery/write.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A009 — Cached views and references are revoked
**Requirement:** R02 · **Task:** T12 · **Status:** UNVERIFIED

Invalidate authorized app caches, pack actions and future voice retrieval; document any residual signed-URL expiry rather than claiming instant recall.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A010 — Understanding has evidence and provenance
**Requirement:** R03 · **Task:** T03 · **Status:** UNVERIFIED

Every summary/annotation/segment suggestion can be traced to a source/version; AI suggestions and human confirmations remain distinct.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A011 — Manual correction survives reprocessing
**Requirement:** R03 · **Task:** T03 · **Status:** UNVERIFIED

Correct title/annotation, rerun processor with new version; original filename and user override persist, new suggestion is not silently accepted.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A012 — Capability status is truthful
**Requirement:** R03 · **Task:** T02 · **Status:** UNVERIFIED

Exercise queued/processing/ready/partial/unsupported/failed/cancelled/permission/budget states separately; stored/playable is not mislabelled understood.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A013 — Digital extraction precedes OCR
**Requirement:** R04 · **Task:** T03 · **Status:** UNVERIFIED

Digital text fixture is parsed without unnecessary OCR; scanned pages use bounded labelled OCR; blank/garbled text is not silently accepted.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A014 — Document locators are real
**Requirement:** R04 · **Task:** T03 · **Status:** UNVERIFIED

Known paragraph/slide/sheet/cell is retrieved; locator opens correct source and version; unknown pagination never creates fake page numbers.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A015 — Conversion is sandboxed
**Requirement:** R04 · **Task:** T03 · **Status:** UNVERIFIED

Malformed archive, macro-bearing Office and hostile HTML cannot execute scripts, fetch private resources or exhaust unbounded resources.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A016 — Preview naming matches rendering
**Requirement:** R04 · **Task:** T09 · **Status:** UNVERIFIED

Text cover says Extracted text preview; genuine page/slide rendition can say first page/slide; unsupported formats remain honest.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A017 — ASR works on real permitted audio
**Requirement:** R05 · **Task:** T03 · **Status:** UNVERIFIED

Run at least one authorized real-provider transcription and retain timestamped evidence; mocks alone cannot pass automatic transcription.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A018 — Mixed-language transcription is evaluated
**Requirement:** R05 · **Task:** T03 · **Status:** UNVERIFIED

Use labelled Cantonese/Traditional Chinese/English code-switch clips; report CER/WER per language and segment, errors and processor identity; confirm usable retrieval moments.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A019 — Waveform comes from samples
**Requirement:** R05 · **Task:** T03 · **Status:** UNVERIFIED

Different decoded signals produce corresponding different peaks; no hash-derived bars presented as a real analysis timeline.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A020 — Corrections and speakers are handled honestly
**Requirement:** R05 · **Task:** T03 · **Status:** UNVERIFIED

Correct a timed segment and an anonymous speaker label; preserve history/alignment; no inferred real-world identity.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A021 — Playback and Save moment work
**Requirement:** R05 · **Task:** T09 · **Status:** UNVERIFIED

Play/pause/seek and save an in-bounds interval; reopen same version and interval; no autoplay on detail open.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A022 — Video understanding is bounded and useful
**Requirement:** R06 · **Task:** T03 · **Status:** UNVERIFIED

Real permitted video produces poster, duration, timed transcript and bounded scene/frame evidence; missing capabilities displayed accurately.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A023 — Visual similarity is not caption-only
**Requirement:** R06 · **Task:** T04 · **Status:** UNVERIFIED

Labelled image/frame query exercises a compatible visual index and finds expected visual candidates; report applied modality and fallback.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A024 — Visual annotation does not infer identity
**Requirement:** R06 · **Task:** T03 · **Status:** UNVERIFIED

No automatic person identification/sensitive trait inference; scene suggestions and crops remain separate from approved outputs.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A025 — Old assets remain findable
**Requirement:** R07 · **Task:** T04 · **Status:** UNVERIFIED

With at least 1,001 assets find known assets at positions 201 and 1,001 and an old segment by exact query; no newest-200/global age cutoff.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A026 — Lexical and semantic strengths coexist
**Requirement:** R07 · **Task:** T04 · **Status:** UNVERIFIED

Exact filename/id/phrase/dimension tests pass; independently labelled semantic queries reach Recall@10 >= 0.90 on the agreed 100-query set.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A027 — Multilingual query behavior is tested
**Requirement:** R07 · **Task:** T04 · **Status:** UNVERIFIED

Traditional/Simplified Chinese, Cantonese expressions, English and mixed queries evaluated; language normalization cannot erase meaningful content.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A028 — UI and Agent share retrieval policy
**Requirement:** R07 · **Task:** T04 · **Status:** UNVERIFIED

Same user/scope/purpose query yields consistent eligibility and coverage through both routes; any presentation difference is documented.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A029 — Pagination and totals are trustworthy
**Requirement:** R07 · **Task:** T04 · **Status:** UNVERIFIED

Page through deterministic fixtures without skips/duplicates; counts are server scoped, not loaded-card length; stale cursor prompts safe refresh.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A030 — Degraded search is explicit
**Requirement:** R07 · **Task:** T04 · **Status:** UNVERIFIED

Vector/provider outage retains labelled lexical results, modesApplied and coverage; no false semantic-complete badge.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A031 — Search latency meets candidate budget
**Requirement:** R07 · **Task:** T13 · **Status:** UNVERIFIED

At 10,000 mixed assets/8 concurrent scoped searches, 100 warm measured requests: lexical p95 <= 2 s, hybrid p95 <= 3 s; report hardware/network/cold results separately.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A032 — Answers are grounded
**Requirement:** R08 · **Task:** T05 · **Status:** UNVERIFIED

On agreed benchmark, >=95% of evaluated factual claims are supported by cited passages; report denominator and human review, not just model self-scoring.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A033 — Unanswerable questions abstain
**Requirement:** R08 · **Task:** T05 · **Status:** UNVERIFIED

All deliberately unanswerable/security trap cases abstain or state insufficient source support; no invented asset, fact or locator.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A034 — Citations deep-link accurately
**Requirement:** R08 · **Task:** T05 · **Status:** UNVERIFIED

100% of deterministic page/time/slide/cell fixtures open exact referenced version and location; signed-link expiry refresh respects grants.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A035 — Conflicts and scope are visible
**Requirement:** R08 · **Task:** T05 · **Status:** UNVERIFIED

Two contradictory sources are attributed and contrasted; selected scope and partial indexing are shown, not silently broadened.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A036 — Prompt injection cannot control tools
**Requirement:** R08 · **Task:** T05 · **Status:** UNVERIFIED

Malicious source instructions cannot authorize retrieval of other sources, exfiltration, mutation or override system/tool boundaries.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A037 — Smart Collections save criteria, not SQL
**Requirement:** R09 · **Task:** T06 · **Status:** UNVERIFIED

Allowlisted rule AST preview and save succeed; arbitrary SQL/code/prompt-as-execution is rejected.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A038 — Membership updates without file copies
**Requirement:** R09 · **Task:** T06 · **Status:** UNVERIFIED

New matching asset joins after processing; collection adds no duplicate blob; missed event reconciliation repairs membership.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A039 — Overrides and undo remain safe
**Requirement:** R09 · **Task:** T06 · **Status:** UNVERIFIED

Exclude beats automatic inclusion; manual includes respect access; undo restores prior organization revision but never revoked consent.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A040 — Version lineage is explicit and acyclic
**Requirement:** R10 · **Task:** T06 · **Status:** UNVERIFIED

Original -> excerpt -> rendition -> draft/post relations resolve; a cycle insertion fails; bounded explorer does not recurse forever.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A041 — Duplicates are handled conservatively
**Requirement:** R10 · **Task:** T06 · **Status:** UNVERIFIED

Exact duplicates preserve reference-count deletion safety; near duplicates are suggestions, never auto-merged/deleted.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A042 — Comparison and approvals are clear
**Requirement:** R10 · **Task:** T06 · **Status:** UNVERIFIED

Text/metadata/image/media appropriate comparison displays version identity and approval status; unsupported compare says so.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A043 — Source update warns rather than overwrites
**Requirement:** R10 · **Task:** T06 · **Status:** UNVERIFIED

Dependent draft flagged on new version; old citation remains old; applying replacement checks revision and requires intended user action.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A044 — Voice admission is explicit
**Requirement:** R11 · **Task:** T07 · **Status:** UNVERIFIED

Third-party inspiration, quoted guest, generated draft and storage-only document do not become voice examples automatically.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A045 — Span-level and negative examples work
**Requirement:** R11 · **Task:** T07 · **Status:** UNVERIFIED

Approve one passage and a negative example; only permitted spans influence the specified persona/style, not the whole file.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A046 — Persona/brand/language isolation
**Requirement:** R11 · **Task:** T07 · **Status:** UNVERIFIED

Two distinct voice sets cannot leak across selected persona/brand or unpermitted language contexts; adopted examples are explainable.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A047 — Revocation rebuilds derived profile
**Requirement:** R11 · **Task:** T07 · **Status:** UNVERIFIED

Remove a voice sample; future retrieval and persistent derived profile summary cease using it; show evidence of rebuild/invalidation.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A048 — No misleading voice score
**Requirement:** R11 · **Task:** T09 · **Status:** UNVERIFIED

Show examples/provenance and sample coverage; do not present an unvalidated match percentage or claim a trained model was erased.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A049 — Source packs carry context
**Requirement:** R12 · **Task:** T08 · **Status:** UNVERIFIED

Selection enters actual Agent/Ideas/Draft with asset/version/segments, evidence/style purposes, rationale, gaps and rights warnings.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A050 — Task recommendations respect intent and access
**Requirement:** R12 · **Task:** T08 · **Status:** UNVERIFIED

Rank permitted candidates by task/format/currency/diversity; unknown rights do not become cleared and missing evidence is named.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A051 — Navigation restores state
**Requirement:** R12 · **Task:** T09 · **Status:** UNVERIFIED

Return from draft/detail to same query/scope/filter/sort/density/selection/scroll; inaccessible refs are removed without leaking them.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A052 — Final artifacts auto-register exactly once
**Requirement:** R13 · **Task:** T08 · **Status:** UNVERIFIED

Successful final output with verified bytes appears once with producing run/output/source pack after duplicate completion events.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A053 — Scratch and loops are excluded
**Requirement:** R13 · **Task:** T08 · **Status:** UNVERIFIED

Temporary files, tool logs and ingestion-generated previews do not recursively register as final assets; failed registration remains retryable.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A054 — Suggestions are actionable and low noise
**Requirement:** R14 · **Task:** T11 · **Status:** UNVERIFIED

Trigger stale source, unused relevant asset, missing input and failed processing; show reason/affected work and max 3 noncritical suggestions per 24 h.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A055 — Dismiss/snooze/disable persist
**Requirement:** R14 · **Task:** T11 · **Status:** UNVERIFIED

Dedup replayed trigger; dismissed identity suppressed; editable 7-day default snooze and category disable survive refresh/session.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A056 — No unsolicited external side effects
**Requirement:** R14 · **Task:** T11 · **Status:** UNVERIFIED

In-app default only; no email/push/schedules/publication without explicit corresponding opt-in and existing quiet-hour rules.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A057 — Usage traces are real
**Requirement:** R15 · **Task:** T11 · **Status:** UNVERIFIED

Link asset/version/segment to actual draft/post/channel events; show metric source time and distinguish available from unavailable values.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A058 — Recommendations are not causal or popularity-only
**Requirement:** R15 · **Task:** T11 · **Status:** UNVERIFIED

Missing metrics stay null/unknown; no claim an asset caused engagement; diversity/freshness prevents always repeating the top-like item.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A059 — One clear Add and prominent content
**Requirement:** R16 · **Task:** T09 · **Status:** UNVERIFIED

Overview has one Add entry, visible search/scope, compact filters/collections and quiet storage indicator; first asset meaningful at 390 x 844 target.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A060 — Existing visual identity remains intact
**Requirement:** R16 · **Task:** T09 · **Status:** UNVERIFIED

Before/after review shows same Rafii design tokens/global navigation; unrelated pages and styles are not redesigned.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A061 — Type-aware previews and density work
**Requirement:** R17 · **Task:** T09 · **Status:** UNVERIFIED

Image/video/audio/document/generic cases have useful honest previews at each density without eager full players/PDF frames in every grid card.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A062 — Detail organization and safe deletion
**Requirement:** R17 · **Task:** T09 · **Status:** UNVERIFIED

Overview/Content/Related/Usage accessible; technical details secondary; delete separated, permission checked, dependency impact and confirmation retained.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A063 — Batch actions report partial failures
**Requirement:** R17 · **Task:** T09 · **Status:** UNVERIFIED

Mixed permission/format selection gives per-item outcomes; idempotent retry does not repeat succeeded mutations.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A064 — Keyboard and accessibility verified
**Requirement:** R17 · **Task:** T13 · **Status:** UNVERIFIED

Keyboard operation/focus trap/restore/live regions/non-drag alternatives tested; automated scan plus manual WCAG 2.2 AA review, contrast and 200% reflow.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A065 — Responsive behavior verified
**Requirement:** R17 · **Task:** T13 · **Status:** UNVERIFIED

Capture 390x844, 768x1024, 1440x900, landscape and reduced-motion; no clipped controls, inaccessible content or misleading duplicate count names.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A066 — Actual iPhone Safari smoke passes
**Requirement:** R17 · **Task:** T13 · **Status:** UNVERIFIED

Real device upload/playback/seek/drawer/selection/back navigation; safe-area/player/navigation never cover required actions. Desktop WebKit is separately labelled.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A067 — Reuse the existing OpenUI runtime
**Requirement:** R18 · **Task:** T10 · **Status:** UNVERIFIED

Compatible pinned integration and versioned Rafii registry; no duplicate site-wide renderer/framework or generated permanent navigation shell.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A068 — All task surfaces work with real data
**Requirement:** R18 · **Task:** T10 · **Status:** UNVERIFIED

Compare, candidate selection, classification preview, source-pack review and drafting workspace use actual server refs; fixtures alone insufficient.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A069 — Forged actions and replay are denied
**Requirement:** R18 · **Task:** T10 · **Status:** UNVERIFIED

Cross-tenant refs, arbitrary URLs/code/tools, stale revision, mutation during hydration and duplicate action replay are rejected server-side.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A070 — Streaming and fallback preserve work
**Requirement:** R18 · **Task:** T10 · **Status:** UNVERIFIED

Partial/invalid stream retains scope/selection; one repair maximum; component/depth/action caps enforced; deterministic fallback still works.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A071 — Operational resilience is measured
**Requirement:** R19 · **Task:** T12 · **Status:** UNVERIFIED

Worker restart, lease timeout, retry storm, model timeout and budget denial produce recoverable capability states without duplicate billing or silent failures.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A072 — Deletion reaches every derivative
**Requirement:** R19 · **Task:** T12 · **Status:** UNVERIFIED

Delete/revoke across segments, vectors, previews, sources, packs, suggestions and voice summaries; preserve sibling canonical references and document retention limits.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A073 — Observability and costs are truthful
**Requirement:** R19 · **Task:** T12 · **Status:** UNVERIFIED

Feature/provider/version/usage/latency/retry metrics emitted; actual vs estimated vs unknown cost distinguished; secrets/content absent from normal logs.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A074 — Model index/backfill can resume and roll back
**Requirement:** R19 · **Task:** T12 · **Status:** UNVERIFIED

Versioned index generations and bounded backfill survive interruption; pause/cost admission works; rollback preserves originals and honest fallback search.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A075 — Current branch is reconciled before code
**Requirement:** R20 · **Task:** T00 · **Status:** UNVERIFIED

Record real origin/base SHA/worktrees/lease/Library/OpenUI branches and baseline; no stale shared-root modifications or duplicate implementations.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A076 — Legacy and adjacent flows regressions pass
**Requirement:** R20 · **Task:** T13 · **Status:** UNVERIFIED

Existing photo/video/doc/audio ingest/delete/source consent plus Agent/Memory/Drafts/Queue/Now Playing regression commands pass on same candidate.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A077 — Quality gates bind to the candidate SHA
**Requirement:** R20 · **Task:** T13 · **Status:** UNVERIFIED

Typecheck, lint, build, focused tests, disposable Postgres lifecycle/RLS, dependency/security checks and browser evidence all name the same candidate.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A078 — Migration and rollback are rehearsed
**Requirement:** R20 · **Task:** T14 · **Status:** UNVERIFIED

New migration IDs reserved once; legacy fixtures migrate safely in disposable DB; backfill dry-run and rollback/canary playbook include actual environment requirements.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A079 — No fake complete status
**Requirement:** R20 · **Task:** T14 · **Status:** UNVERIFIED

Required cases remain UNVERIFIED/FAILED/BLOCKED until actual evidence; a disabled feature, fixture, PR merge or config file cannot pass a user-flow case.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

### A080 — Production authority is separate
**Requirement:** R20 · **Task:** T14 · **Status:** UNVERIFIED

Document explicit release authority, if supplied. Without it stop at release-ready candidate; production migration/push/merge/deploy/smoke stays awaiting authorization, never falsely PASS.

Evidence to record: candidate SHA; environment; command/manual steps; observed result; artifact/capture reference.

## Coverage and completion accounting
Every R01–R20 has at least one explicit case; the machine-readable acceptance-cases.json contains the same catalogue. Product functionality is not complete merely because some cases were marked not applicable. Any removal of required scope needs James's explicit decision and an updated requirement mapping. Report provider, credential, device or release-authority blockers individually and continue independent permitted work.
