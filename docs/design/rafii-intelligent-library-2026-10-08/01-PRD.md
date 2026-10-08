# Rafii Intelligent Library — Product Requirements

Date: 2026-10-08 · Status: approved feature direction, implementation not yet verified.

## 1. Outcome and product decision
Make Library the private, source-grounded content memory for Rafii: capture material, understand it, find the exact relevant passage or moment, select appropriate sources and voice samples, create with them, and retain the result with its provenance. This is a complete product upgrade, not a gallery reskin, chatbot demo or a new general-purpose DAM business.

All functionality discussed in the preceding review is included below. P0/P1/P2 means sequencing, not scope reduction. An implementation agent must not finish after P0 or describe disabled placeholders as finished P1/P2. Existing working Universal Library behavior must be extended rather than reimplemented.

The primary user is an individual creator or a permitted workspace collaborator preparing content. The initial design assumes Rafii remains connected to its existing Agent, Memory/voice, Ideas/Drafts, Queue/publishing and usage systems. No new paid service subscription or platform-wide product redesign is authorized by this package.

## 2. Five jobs users must be able to complete
**Capture without filing chores.** Drop a supported document, photo, audio or video, paste an allowed public link, or add a quick note. Keep the original safely even when analysis is unsupported. See what has actually finished processing.

**Find the right evidence.** Search by exact name, phrase, dimensions, semantic description, image similarity, topic, approved usage or a spoken passage. Results can be files, pages or timed segments, and show why they matched.

**Understand and verify.** Ask a question across an explicitly selected scope. Open every meaningful citation at its original version and locator. See conflicts, incomplete extraction and unsupported answers instead of plausible invention.

**Create in the user's own voice.** Distinguish personal writing, verified brand facts, inspirational references and storage-only files. Transfer a selected source pack into a real draft without repeating context or falsely treating third-party writing as the user's voice.

**Reuse without losing control.** Find approved/current versions, retain generated final assets, see where material has been used, and receive useful, dismissible suggestions rather than constant notifications.

## 3. Complete requirement catalogue

| ID | Priority | Required outcome |
|---|---|---|
| R01 | P0 | Preserve private universal ingest, existing photo/video paths, file metadata, full originals, collection membership, signed access, quotas and retryable processing. Add resumable/retry-safe user flows where required by the existing transport. |
| R02 | P0 | Separate storage, private indexing, AI retrieval, cloud processing, long-term Memory, voice learning and public-use approval. Every derived result respects tenant, actor, source version and purpose. |
| R03 | P1 | An understanding card shows original facts, AI suggestions, human confirmations, useful segments, likely use cases, source provenance and per-capability status. Manual corrections survive reprocessing. |
| R04 | P1 | Documents retain structural locators: PDF page and section, Office slide/sheet/cell or paragraph, text offsets and source hashes. Detect missing text layers; add bounded, explicitly labelled OCR where no reliable text exists. |
| R05 | P1 | Audio has automatic transcription through an authorized provider, timestamps, language segments, editable speaker labels, real waveform peaks, searchable moments and transcript correction history. Do not infer a speaker's real identity. |
| R06 | P1 | Video adds transcript, poster, duration, selected scene/frame understanding, on-screen text when necessary, clips/moments and visual search. Preserve original aspect ratio and distinguish suggested crops from approved outputs. |
| R07 | P0/P1 | One permission-aware service powers full-scope lexical, semantic and image-similarity search for UI and Agent. Remove the global newest-200 blind spot; retain bounded page sizes and truthful coverage. |
| R08 | P1 | Grounded multi-source answers with source/version/page/time citations, explicit scope, conflict presentation, source selection and honest abstention. Do not conflate a source's assertion with an approved public fact. |
| R09 | P1 | Smart Collections save understandable criteria and update when relevant assets change. Include manual membership, inclusion/exclusion overrides, previews, explanations and undo; no duplicate physical files. |
| R10 | P1/P2 | Versions, near duplicates, canonical originals and derived outputs form explicit relationships. Compare versions, show approvals and usage, and notify affected drafts of source changes without silent replacements. |
| R11 | P1 | Voice-aware source roles and span-level approvals. Learn only permitted author-attributed samples; isolate brands/personas/languages. Show supporting examples and withdraw revoked samples from future use. |
| R12 | P1 | Task-aware recommendations and source packs flow between Library, Agent and existing Ideas/Drafts. Include rationale, evidence, voice samples, rights warnings and missing information. |
| R13 | P1 | Final agent-generated deliverables automatically re-enter Library with job/run identity and source lineage. Deduplicate retries; exclude scratch files, tool logs, intermediate tokens and recursive ingestion. |
| R14 | P2 | A proactive librarian surfaces outdated sources, relevant unused material, missing campaign inputs, failed processing and useful organization proposals. In-app by default; reasons, dismiss/snooze/disable controls and deduplication are mandatory. |
| R15 | P2 | Usage and outcome views connect asset/version/segment to drafts, posts, channels and available metrics. Distinguish correlation from causation; missing metrics remain unknown. Diversify suggestions rather than always ranking the highest-like image first. |
| R16 | P0 | Keep Rafii's current visual identity, but compress the control stack: one Add entry, prominent search, compact filters, collection/saved-view navigation and a quiet storage indicator. Used/Unused remains a filter. |
| R17 | P0/P1 | Type-aware previews, density control, selection and batch actions, a useful desktop detail panel/mobile drawer, source jumping, preserved navigation state, mobile player clearance and keyboard/accessibility support. |
| R18 | P1/P2 | OpenUI powers task-result interfaces: comparisons, selection cards, classification preview, source packs and drafting workspaces. The Library navigation shell stays stable; actions route through server-validated Rafii tools. |
| R19 | P0/P2 | Durable job state, cancellation, retries, cost admission, health metrics, lifecycle cleanup, security tests and deletion/revocation propagation across derived assets and indexes. |
| R20 | P0/P2 | Reconcile the actual latest implementation, test at realistic scale, dry-run migration and rollback, verify authenticated UI paths, and produce a candidate-SHA-specific acceptance/release receipt. |

## 4. Required end-to-end demonstrations
**D1 — Mixed-language memory retrieval.** With more than 200 assets, find an old Cantonese/Traditional Chinese/English passage, distinguish private and approved use, answer with exact evidence and open the original locator.

**D2 — Interview to draft.** Ingest a permitted interview, inspect true processing states, search speech, select a moment, attach an approved personal voice sample, create an editable draft, and preserve source references when returning to Library.

**D3 — Old version protection.** Derive a draft from one source version. Add a revised source, compare it and show an affected-draft warning. Do not silently mutate the old citation or claim the new version was approved.

**D4 — Working intelligent organization.** Preview a smart collection, save its criteria, ingest another matching asset, observe it join, exclude it and undo a reversible change. No byte duplication.

**D5 — Output comes home.** Generate an actual final deliverable in a test workspace, register it once despite replayed completion events, retain lineage and avoid collecting temporary working files.

**D6 — Honest proactive creation.** While editing a campaign draft, surface an appropriate unused asset with a reason. Dismiss it and show suppression. With unavailable outcome metrics, display unknown rather than manufactured scores.

**D7 — Safe generative interface.** Ask to compare versions and select sources through OpenUI. Reject a forged cross-workspace asset, stale action revision and unauthorized mutation; the deterministic Library remains usable after a renderer failure.

## 5. UI decisions already made
Preserve soft/green/glass Rafii tokens and existing shell conventions. Do not redesign the rest of the app. Content should appear early in the viewport. Use compact, type-appropriate previews; no fake audio-analysis waveform, no text cover labelled as a faithful document page, no graph-centric homepage and no meaningless intelligence/voice-match percentage.

Keep direct browsing and search available alongside Ask Library. A user should not have to converse to upload, sort, select, play or download a file. An understanding card should answer: what is this, what can I use it for, what supports that interpretation and what can I do next?

## 6. Quality, scope and trade-offs
All numerical gates in the acceptance matrix are initial engineering acceptance targets, not observations of current production. Changes to these targets require a recorded reason and explicit scope agreement, not silent relaxation until tests pass.

Use progressive analysis: cheap deterministic metadata first; transcription/embedding/visual analysis only when allowed and admitted by budget. Reuse content hashes and derived versions. A storage-only source must remain useful as a file without being sent to a model.

The greatest risk is wrong or unauthorized source material being presented confidently. Prioritize access checks, grounded locators and honest capability states ahead of visually impressive demos. No promise of global-most-intelligent performance is made; prove task completion on the benchmark.

## 7. Not part of this request
No new competitor subscriptions, face recognition, identity inference from voices/images, autonomous public posting, legal determination of ownership, public sharing by default, production account changes, unrestricted web crawling, training a foundation model, unrelated Rafii screens or a new independent agent runtime. Existing permitted connectors may supply source links; new OAuth scopes/accounts require their own approval.

## 8. Definition of complete
All R01–R20 are implemented or explicitly re-scoped by James, with every corresponding acceptance case resolved. A blocked provider is not a working transcription feature. A mock or disabled component is not production acceptance. A release-ready candidate and a production deployment are different milestones; authority boundaries in the start file apply.
