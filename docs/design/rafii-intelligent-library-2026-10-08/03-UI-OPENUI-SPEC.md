# Rafii Library — UI and OpenUI Specification

Date: 2026-10-08 · Scope: R03–R18, with R02/R19 security and lifecycle constraints.
This is an interaction/design specification, not a new live prototype or an assertion that screenshots were captured in this packaging turn.

## 1. Design direction and stable shell
Keep existing Rafii green/soft neutral/glass tokens, typography, spacing system, icons, motion language and shell integration. Do not introduce a separate visual system. Use the current library components and desktop Sheet/mobile Drawer where possible. Important content and actions must remain legible without blur effects or motion.

Desktop layout: existing application navigation -> collapsible Library collection/saved-view rail -> main search/results canvas -> contextual detail panel only when an asset is open. Do not add a second permanent global sidebar. Tablet collapses the local rail. Mobile uses a scope/collection switcher and one results column or two compact cards according to available width.

One primary Add control opens upload, paste link and quick note choices. Do not show Add assets and Upload images as equal competing actions. Preserve drag/drop and existing image compatibility conversion internally. Always show scope beside search. Used/Unused is a filter rather than the whole information architecture. Storage stays a compact indicator unless approaching configured quota; warnings must be based on server values.

Place query, scope and compact filters above results. Collection management is reachable in its navigation context, not a large management accordion consuming the first screen. Keep Gallery/List and density controls persistent. At 390 x 844 viewport, after stable load and with no banners, at least one meaningful asset preview/title should be visible without scrolling. This is a proposed layout target, not a measurement of the current app.

## 2. Screens and state inventory
| Surface | Required states and actions |
|---|---|
| Library overview | Loading, empty, populated, partial index, offline/degraded, quota warning, denied; Add, query, scope, filters, gallery/list, density, collection selection. |
| Results | Exact/semantic/visual modes applied, stale request cancellation, source count and processing coverage, no results vs unavailable mode, match reason, segments and deep links. |
| Upload/ingestion | Per-file transfer and per-capability progress, queued/running/partial/failed states, cancel/retry, duplicates, rejected size/type, budget/permission gate. |
| Asset detail | Overview / Content / Related / Usage sections, source purposes, current version, understanding card, original metadata and technical details. |
| Ask Library | Explicit selected sources and purpose, citations, conflicts/insufficient evidence, pending analysis, follow-on selection without losing search state. |
| Smart collection | Rule explanation and edit controls, membership preview, save revision, include/exclude override, reevaluation indicator and undo. |
| Version comparison | Original/current version, approvals, image/media/document-appropriate comparison, impacted drafts and explicit replacement confirmation. |
| Source pack / Create | Selected evidence vs style samples, source locators, rationale, rights warnings, missing inputs, editable draft handoff. |
| Suggested for you | Reason, affected work, open/review/apply when permitted, dismiss/snooze/disable, no misleading unread urgency. |
| OpenUI task result | Streaming, partial, completed, recoverable error, denied/conflict, busy mutation and deterministic fallback with retained selected sources. |

## 3. Cards and previews
Card order: authentic preview -> readable title -> concise type/duration/page metadata -> at most one most relevant status plus optional secondary warning. Put large sets of tags, hashes and diagnostic details behind detail. Titles can be user-edited without losing original filenames. Show selection affordance on keyboard focus as well as hover; use touch-accessible selection on mobile.

**Image:** preserve recognizable composition and aspect ratio; no destructive crop of the original. Density modes may letterbox or use a clearly defined fit. Mark suggested crops as suggestions.

**Video:** real poster and duration, play affordance, available segment highlights and transcript snippets. Loading a grid should not instantiate a video player for every asset. Use visibility-based lazy loading and bounded concurrency.

**Audio:** compact player, true amplitude waveform, duration, transcript availability/language and useful segment summary. A decorative symbol can represent audio when peaks are unavailable, but it must not resemble an analyzed timeline. Support play/pause/seek and Save moment with a real interval. Respect user initiation; no autoplay simply from opening a detail panel.

**PDF/Office:** a genuine first-page/slide rendition may be labelled as such. Extracted text covers must say Extracted text preview. Preserve the original file and offer a viewer appropriate to its type. Avoid loading many full PDF iframes in the grid; prefer cached private thumbnail renditions when implemented. Unavailable conversion is an honest fallback, not a blank tile.

**Generic file:** clear type/filename and original download, with no claim of content understanding. Unsupported extraction and successful storage can coexist.

## 4. Detail panel as a work surface
Overview leads with what this is, source status, permitted purposes, suggested uses and next action. Content has real preview, transcript/structural text and source locators. Related shows version stack, original/derived relations, near-duplicate suggestions and an optional bounded relation explorer. Usage shows actual draft/post references and available metrics. Technical fields such as hash/MIME move to an expandable details area.

Use source-purpose settings with plain language and explicit consequences. Selecting My voice should require sample/author confirmation; it is not a generic tag. Show extracted assertions, AI suggestions and confirmed fields differently without relying on color alone. Let the user correct an annotation and see that correction persist after analysis.

Primary action is context-specific: Use in draft / Add to sources / Play / Open relevant page. Delete is secondary, in an overflow or separated danger area, with dependency impact and existing confirmation policy. Never let a swipe-to-close dismiss the user's unsaved edit without a recoverable state.

## 5. Search and navigation behavior
Support exact query entry without forced natural-language conversation. Display the scope in ordinary words: Entire permitted Library, This collection, or Selected N items. A model failure must not disable lexical search. Show why a result matches and provide playable/clickable moment or passage results where appropriate.

URL/deep-link state should encode stable asset/version/locator identities and safe filters, not signed URLs or secrets. Search state includes query, scope, filters, sort, mode, density and selected IDs. Returning from a draft or detail restores scroll and selection unless the source became inaccessible; then remove inaccessible data and explain generically.

Batch selection exposes actions only after selection: add/remove collection, adjust permitted metadata, build source pack, compare supported versions and delete with separate permission/confirmation. Mixed selections return per-item success/failure without claiming all succeeded. Repeated clicks use idempotency keys. Optimistic updates must roll back on conflict and never visually confirm an unauthorized write.

## 6. Mobile and accessibility
Test 390 x 844, 768 x 1024 and 1440 x 900, plus landscape and 200% zoom. These are test viewports, not device claims. Obtain a real iPhone Safari smoke test for upload, audio playback, seek, source selection, drawer and return navigation; desktop WebKit alone is not a substitute.

Keyboard: predictable Tab order, visible focus, focus trap and restoration in dialog/drawer, Escape close where safe, keyboard selection and all drag operations available through non-drag alternatives. Announce asynchronous upload/search/action changes through appropriate live regions without repeated chatter. Label controls and singular/plural counts correctly; animated digits must not create duplicate accessible names.

Use the app's 44 CSS-pixel interactive target design target where feasible; test WCAG 2.2 AA criteria including text contrast (4.5:1 normal, 3:1 large), non-text contrast, focus visibility, reflow and alternatives to dragging [E7]. A screenshot or automated scan alone cannot establish compliance.

Reserve layout space for bottom navigation, Now Playing and safe-area insets; no stacked fixed bars covering the last result or action. Prefer one combined media-control region rather than three competing footers. Reduce motion for affected users, maintain frame stability during streaming, and use no hover-only interactions. Glass/blur must have an opaque fallback and not make scrolling unusable.

## 7. OpenUI integration contract
The official renderer uses a component library, supports streamed rendering and structured actions, and exposes state/query/mutation/error integrations [E1]. Pin the actual compatible package/version only after checking the repository's existing OpenUI rollout and lockfile. Reuse that runtime, registry, error boundary, schema and transport instead of installing a duplicate framework.

OpenUI does NOT generate the permanent Library shell. It may compose only the task-result region using a versioned Rafii component allowlist:
`AssetCandidateCard`, `SourceCitation`, `SourceScope`, `VersionComparison`, `CollectionProposal`, `SourcePackReview`, `DraftWorkspace`, `ProcessingStatus`, `SuggestionReview`.

These are proposed registry entries, not existing exports. Reuse existing app components behind them. They accept typed server-issued AssetRefs and ActionEnvelopes, not arbitrary HTML, script, URLs or SQL. The host owns selection and draft state; partial streams must not reset it.

`SourcePackReview` displays evidence and style refs separately and cannot mark a fact or rights status approved. `CollectionProposal` must show a before/after membership preview and the effect of an action. `VersionComparison` carries source version identity. `ProcessingStatus` reflects server state rather than model narration.

## 8. Generated-action safety and recovery
Generated Query/Mutation bindings are not a privileged back door. The host adapter accepts only explicitly registered functions with per-action server authorization, intent validation, current source/grant revisions and idempotency. Do not expose a generic fetch, arbitrary MCP client or raw SQL capability to model-generated markup. View replay/rehydration must never execute a mutation without a fresh permitted user action.

Default limits: 100 rendered task components, nesting depth 12, 5 read actions per task render cycle, no parallel mutation actions, one parser-repair attempt and no automatic retry of a mutation. Limits are initial product policy and should be surfaced as recoverable errors, not silently truncated content. Server rate limits remain authoritative.

Streaming partial data is read-only until a complete validated action is available. On parse/network/tool error, show the deterministic result components using the same validated source data. Retain scope and selected assets. If no valid result exists, show an honest retry/error state rather than fabricate cards. Revocation or source revision conflicts invalidate affected actions and require refresh. Persist safe view state but no ephemeral signed URLs.

## 9. Required visual review evidence
Capture current baseline before changes and candidate after changes at the same viewport/state. Review overview, search with moment results, each asset type, open detail, smart collection preview, source pack, version comparison, proactive list, OpenUI success/error/conflict, empty and partial-processing states. Store evidence with candidate SHA and environment. Do not reuse the prior conversation's narrow screenshots as proof of the new UI. Include short recordings for scrolling, drawer/player interactions and streaming stability.
