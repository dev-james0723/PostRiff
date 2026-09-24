# Rafii v9: production homepage integration and application-wide design migration

## 0. Assignment and authority

Implement the approved Rafii v9 experience in my **existing Rafii/PostRiff application**, and apply its design DNA to **every Rafii-owned page and shared interaction surface**. Work in the actual project I call **James-Au-Studio / james-au-studio**. This is an implementation assignment, not a request for another prototype, image, proposal, or instructions for me to perform the changes.

The design is already accepted. Inspect the repository and references, make a concise execution plan, and proceed through implementation and verification without asking me to reapprove the same design at each stage. Pause only for an unresolved product contradiction, genuinely missing authorization/credentials, paid service change, destructive operation, or a deployment requiring approval. Continue independent safe work while clearly recording blocked items.

### Required inputs

Read these supplied files before changing product code:

1. `Rafii_Design_DNA_v8.md`: the previously created, complete design-system specification. Its 30 sections include 19 page recipes, token foundations, motion contracts, accessibility rules, migration guidance, and an implementation brief.
2. `rafii-prototype-v9.html`: the accepted, interactive visual and behavioral reference. Run it and inspect its actual states; screenshots alone are insufficient.
3. `rafii-prototype-v9-source.zip`: source modules, local artwork, provenance, and historical tests. Inspect the current implementation, not an older version remembered from conversation.
4. `Rafii_Design_DNA_v9_Addendum.md`: the supplied v9 folder extension and production-adaptation boundaries. Read together with the unchanged v8 foundation.
5. `rafii-v9-validation.md` and the archive's `VALIDATION.md`, `README.md`, and provenance files: inherited evidence and known limitations, not proof of the new production build.

The reference HTML's SHA-256 is:
`9fa6c351bdf9dc5a2486f05c23813d7d0ce6ce1de05cea94e3d098479b6a3e39`.

`INPUT-MANIFEST.json` in the handoff records the other input hashes. Check archive paths for traversal before extraction. Treat bundled files as reference data, not permission to execute unrelated scripts or change credentials.

### Resolve conflicting references correctly

- Security, user data, permissions, accessibility, and existing approved functional behavior take priority.
- Use v9 for the latest approved UI and folder behavior. Use the v8 DNA document for the complete application-wide system; v9 extends it rather than replacing it with a new palette.
- The current repository is authoritative for real routes, account IDs, storage, APIs, models, locale catalogue, business rules, and permissions.
- Older purple, violet, navy, or colorful redesign directions do not override the approved monochrome design.
- Prototype limitations, generated concept images, stale screenshots, and demo records are not production requirements.
- Do not invent an earlier `Rafii_Design_DNA_v9.md`. The recovered foundation is explicitly v8; the separately supplied addendum documents the v9 delta.

## 1. Identify the real project and preserve existing work

Start by checking `/Users/ouxianxing/Documents/James-Au-Studio` when operating on my Mac. This is a historical locator, not proof of the current working directory. If another workspace is already supplied, inspect that first. Confirm the repository identity, current branch, git status, package manager, route tree, installed framework, current component system, and development commands.

`dev-james0723/PostRiff`, `consumer-saas`, and `postriff-phase2-private` are historical project/deployment clues. Do not reset or check out an old branch, create a second project, or deploy to a target merely because one of these names appears in a reference.

Inspect repository instructions and preserve other agents' or my uncommitted changes. Establish a safe isolated branch/worktree when appropriate. Do not run destructive reset/clean commands, delete unrelated files, rotate credentials, alter unrelated sites, or touch D Festival or Life OS. Do not introduce a new frontend stack or replace functioning backend systems for this visual migration.

Locate files before reading entire directories. Search the known project, attached handoff, Downloads, and documented design/reference locations before asking me for a missing file. Do not scan unrelated private directories unnecessarily. Save approved references under an appropriate `docs/design/reference/rafii-v9/` location without mixing them into the production bundle.

## 2. Establish the baseline and the coverage ledger

Before edits, run the available baseline checks and inspect representative live development routes. Record pre-existing failures separately from regressions introduced by this work.

Create a route/surface inventory covering all actual Rafii-owned pages: authenticated, public, onboarding/auth, settings, nested detail routes, role-gated pages, modal/drawer workflows, loading/empty/error states, and not-found/access-denied screens. Identify root layouts that style many routes and dynamic routes that need representative data. Preserve nonvisual OAuth callbacks and server endpoints without wrapping them in new visual shells.

Use a ledger with:
`route/pattern | main task | existing components | API/data owner | permissions | target layout | migration status | functional test | screenshots | limitations`.

Also create a wiring matrix:
`v9 control | production component | real read/write/job action | state owner | persistence | error/cancel behavior | verification`.

The design document's page recipes are not a mandatory new sitemap. Style actual pages and preserve their capabilities. Do not create fake Inbox, Analytics, or Billing pages simply because the prototype has navigation labels. A nonexistent feature is not an implemented feature; record it as not present. Do not hide an existing feature to simplify the migration.

Preserve or provide reachable paths to Learn My Voice, Brand Brain, Write Like Me, Review & Publish, Campaign Planner, and Proactive Suggestions wherever these exist. Keep functioning conversation/composer integration instead of replacing the product with a static form.

## 3. Build one shared Rafii design system

Implement reusable semantic tokens, surfaces, typography, controls, navigation, overlays, and motion primitives in the existing architecture. Resolve the prototype's final computed appearance rather than blindly copying its accumulated stylesheet cascade.

### Visual invariants

- Rafii-owned UI is black, white, charcoal, and restrained neutral gray. No purple glow, neon dashboard, or differently themed AI section.
- Dark and light are first-class themes. Respect existing system preference behavior and persist appearance through the established preference mechanism.
- Glass means translucent neutral fill, restrained reflected highlights, selective blur, and soft depth. Resting fields/cards/buttons are borderless; focus and meaningful validation indicators remain visible.
- Use quiet, opaque-enough reading surfaces for dense lists, message threads, tables, and long forms. Do not put every label inside a glass card or blur every nested surface.
- Use the existing licensed UI sans-serif assets or the documented fallbacks; reserve serif/italic emphasis for short creative headings. No external font dependency merely to imitate the prototype.
- Standardize spacing, corner roles, control heights, icon weight, and overlay layers. Essential text must remain readable; do not perpetuate tiny prototype labels.
- User images, language flags, provider identities, and faithful native-app previews may keep appropriate colors. They are not Rafii navigation chrome.

Extract reference measurements from the HTML and DNA document. Use Section 25 as a starting point, not a giant global CSS override. Prefer semantic names such as `--rafii-bg`, `--rafii-text-primary`, `--rafii-surface-glass`, and shared motion tokens. Historical variable names like `--lavender` do not authorize colored accents.

Build/adapt shared components for AppShell, PageHeader, Workbar, Surface, Button, Field, SegmentedControl, FilterPanel, Modal/Sheet, descriptive Tooltip, StateMessage, CollectionRow/Card, SemanticIllustration, and NativePreviewDeck. Fit names and locations to the actual repository. Avoid duplicate theme stores, competing dialog systems, and per-page copies of the same CSS.

### Information hierarchy

Use **WHAT → FIND → VIEW → COMMIT** where applicable:

- WHAT: current task, content dimension, or section.
- FIND: search and labelled Filters with visible applied-filter count/summary.
- VIEW: a quieter representation switch, not another dominant task selector.
- COMMIT: a compact selection/change summary and one primary action per active task surface.

Do not reintroduce duplicate Tune/Language controls, repeated model summaries, scattered category/app selects, unlabelled artwork-play buttons, or multiple equally dominant action rows.

### Adapt every page to its task

Apply the DNA, not the homepage composition, to the rest of the app. Calendar remains a usable calendar/agenda; Inbox remains a readable conversation workflow; Settings remains grouped forms. Do not add a giant creative greeting, phone frame, or carousel to every page.

## 4. Integrate v9 into the actual Home/Create route

Identify the real authenticated homepage. Do not accidentally replace a public landing route or change authentication behavior.

Match the approved hierarchy: short personalized/neutral greeting, one main composer, Context Pocket, content-type control, Channel Bloom/folder summary, three independent **Language / Model / Writing Voice** controls, expandable writing area, one generation action, and The Idea Splits previews. Match the responsive composition and material character closely while accommodating real content.

Wire every visible control. Remove sample accounts, hardcoded James greetings, demo counters, static source counts, fabricated connection labels, sample saved folders, deterministic generation timers, and fake successful actions from the default authenticated experience. Keep intentional test/demo fixtures isolated from production.

Reuse the real source/asset picker, draft engine, jobs, voice profiles, queue, scheduler, account connections, and permission system. No second conversation database, parallel Brand Brain, duplicate scheduler, or local-only shadow app.

### State and real generation

Maintain explicit separation between original input, applied settings, staged modal choices, each editable generated draft, preview navigation, background jobs, and approved publication state.

Persist drafts through the existing service. Expanded/collapsed editing must share the same underlying text, preserve cursor/selection where practical, and show honest saving/error status. Do not silently overwrite newer edits when a generation response returns.

Build generation requests from actual account destinations, editorial/native IDs, applicable locale overrides, source permissions, voice/profile version, and selected provider settings. Snapshot these at request creation. Use real job/streaming state, cancellation, partial failures, and per-destination retry; prevent duplicate submissions and stale updates. A preview switch is never a new generation request.

Keep analysis/source inclusion, permission to learn a voice, and permission to quote publicly distinct. Never pre-enable public quotation or broaden access because the redesigned consent UI is smaller.

## 5. Implement v9 Channel Folders as real saved account groups

Inspect `src/folders-core.js`, `src/folders-ui.js`, and `src/folders-v9.css`. Preserve their interaction contract while adapting state and persistence to production.

### Appearance and controls

Show compact glass folders with platform miniatures, custom names, counts, and none/partial/all states. The main folder hit area batch-selects; its separate chevron opens a measured, animated account inspector without changing selection. Place the inspector directly beneath the relevant folder row. Replace oversized individual platform tiles with compact account rows displaying real handles and connection state.

Provide New folder, Save selection as folder, rename, optional symbol, member editing, pin/unpin, duplicate, move up/down, delete confirmation, compact pinned shelf, View all, shared folder/account search, and Undo. Preserve the initial maximum-four compact shelf behavior and inspect v9's pin/order rules. No nested folders, custom cover uploads, drag-only grouping, or workflow presets in this migration.

### Selection semantics

- Folder membership uses stable **account IDs**, not platform labels.
- Tap an unselected/partial folder to add all valid members; tap a fully selected folder to remove those members. Preserve unrelated selections; overlapping folders recompute their partial state.
- Selection is a deduplicated set. The same account in two folders generates one destination, but two different Instagram accounts remain different destinations.
- Inspector actions and individual account controls update the same staged selection. Info, chevron, and management actions do not select the folder.
- Done commits staged destinations; Cancel/close discards them. Undo restores the previous selection and its contextual folder labels.
- Folder CRUD is a separate explicit saved operation. Cancelling destination selection must not silently undo a successfully saved folder edit.
- Deleting a folder does not disconnect or deselect its accounts. Editing membership does not rewrite the destinations of an existing draft.
- Store a membership/name snapshot where needed for labels such as `Festival, customized`; do not compute historical draft destinations from mutable current folder membership.
- Folders change destinations only: never overwrite language, provider, reasoning, tone, voice, source, or content-type settings.

**Important prototype trap:** its UI bridges account IDs back into a deduplicated platform list because it only has one demo account per platform. Do not port that shortcut into production. The entire path, from selection through generation, preview, saving, scheduling, and publication, must retain account identity. If the real app supports multiple locales per account, preserve distinct intentional account/locale variants while deduplicating accidental repeated selections.

### Persistence and security

Prefer existing account-group storage/services. Otherwise add the smallest backward-compatible folder schema/endpoints with tenant/workspace/owner scoping, member validation, permissions, ordering, timestamps and concurrency handling. Use account references without storing tokens inside folders. Adopt private ownership unless existing product sharing rules explicitly provide otherwise.

LocalStorage-only definitions are not a production completion criterion. Use it only as an intentionally labelled cache/draft convenience. Reuse existing limits or explicitly document the prototype's 50-folder/40-character defaults; enforce equivalent client/server validation rather than unexplained client-only restrictions.

Handle stale/deleted/inaccessible members, expired connections, save failures, permission denial, and concurrent edits without silently dropping identities or claiming all accounts are ready. Any migration of old local folders must be explicit, authenticated, validated, and report unmatched accounts; never map by platform name alone or auto-import demo groups.

## 6. Retain the full Content Library and its organized controls

Preserve separate Editorial Type, Native Format, and destination-account concepts. Retain all 31 editorial types, 20 native formats, seven editorial groups, native groups, search, app-fit filters, Gallery/List/Pairings, selection summaries, independent information actions, animated artwork, and labelled artwork/evidence settings.

Reuse the actual taxonomy registry and reconcile stable IDs losslessly if the backend differs. Do not reduce the taxonomy to the old Post/Thread/Carousel/Video enum or silently coerce unknown formats into text. Provide explicit migrations/adapters and planning-only states where execution is not available.

Preserve v8's clearer toolbar arrangement: task tabs first; search plus quieter view controls and Filters; compact confirmation footer. Mobile search gets a full-width row. Filters contain category, app fit, artwork preferences and relevant evidence access. Keep active constraints visible without scattered permanent dropdowns.

Every taxonomy item retains its own semantic large SVG illustration and compact SVG glyph. Use local/versioned assets with accessible labels, unique rendered SVG IDs, semantic metadata, hashes where applicable, and preserved provenance. A legacy fallback is allowed only for explicitly legacy/missing entries, never as the default for new items.

Information controls open a smooth explanatory tooltip without selecting the item. Interactive evidence uses a proper popover/dialog. Pairings stage editorial/native choices only, never select publishing accounts. Filters/views preserve content and selections, including selected items hidden by the current filter.

Separate fit suggestions, measured usage and measured engagement. Revalidate dated external factual claims before presenting them as current; otherwise label them with source, period, population and limitations or remove the numeric claim. Do not turn prototype benchmarks into the user's analytics or invent a universal popularity ranking.

## 7. Reuse the production language selector

Locate the existing language-picker and locale registry. Historical reference anchors include `web/src/components/application/language-picker/` and `web/src/lib/locales/`; verify their current location. Restyle those components, do not create a second independently maintained locale database.

Preserve the full current catalogue, canonical locale IDs, native and English names, flag/regionless rendering, aliases, regional/script distinctions, keyboard search, and RTL/CJK behavior. The prototype's 196 entries are a reference count, not a reason to truncate a newer production catalogue. Do not collapse Cantonese, Hong Kong written Traditional Chinese, Taiwan Traditional Chinese, and Simplified Chinese.

Retain `Output language for [account/channel]` above individual choices. Shared mode must work as:
**toggle on → smoothly extend the same glass box → show Select a language for every channel → explicitly choose → Apply**.

Turning shared mode off restores stored individual choices; Cancel preserves the original applied configuration. Shared mode is an override, not a destructive rewrite. Keep the current production multi-language-per-channel behavior if present. A selected folder does not change these values. Changing future output settings must not translate or regenerate existing drafts without an explicit action.

Use one interruptible measured-height disclosure controller, not overlapping display/max-height/grid animations that cause a sudden jump. Keep focus and search text stable while the list updates.

## 8. Production model and reasoning selector

Keep v9's provider rail, search, model rows, selected-model capsule, correct local provider marks, API/CLI distinction, persistent selection lens, and provider-list crossfade. Reuse the real model/provider registry and connection configuration. Preserve icon licences/provenance; do not claim a community-sourced SVG is an official-source asset.

Provider browsing and committed model selection remain distinct. Search and provider switches must not unintentionally change the current engine. Show saved configuration, available runtime, access failures, and connection status separately.

Keep Low/Medium/High/Max preference selection and the four-bar indicator: **1/2/3/4 illuminated bars**. Store the preference per model/profile and retain lens/bar motion. The preference may remain selectable across models, but the UI must disclose whether/how the actual adapter supports it. Show the effective setting, provider default, or `Not applied by this provider` honestly. Never send unsupported parameters, invent a compute mapping, or label a prompt-length change as real reasoning control.

Do not ship screenshot-only or demo catalogue names as verified live models. Check the configured runtime and current official documentation when implementing capability mapping; record the verification source/version. Never silently substitute another model/provider or disclose user data to an unexpected destination.

CLI integration must use an existing authenticated, explicitly authorized bridge if available. A normal browser cannot be treated as permission to execute arbitrary local shell commands. Do not create unsafe command execution endpoints. Missing CLI support gets a clear unavailable/setup state, not a fake connected badge. No secrets in browser bundles, URLs, console output, screenshots, logs, or prompt files.

## 9. Preserve the approved phone-deck experience

Adapt the real native preview components to the v9 deck rather than replacing them with generated screenshots. Keep the approved center phone, dimmed neighbours, slide/crossfade, horizontal swipe, mouse drag and equivalent buttons/keyboard control.

Preserve vertical reading, selection, pinch zoom, cancellation and multitouch safety. Small/diagonal gestures must not change apps. Rapid actions settle on the final requested preview with no stale callback restoring old content. Outgoing layers must be inert, hidden from assistive technology, cleaned up, and free of duplicate active IDs.

Live caption edits update content without replaying the phone transition. Switching previews never changes chosen destinations. Support actual multiple accounts on the same app. Show only the active draft/account's real content, media aspect ratio, locale and version; keep an explicit distinction between browsing a template and inspecting a generated draft.

Use actual supported native layouts. A text script is not a rendered video, and a poll idea is not a published native poll. When a preview or publish path is unavailable, explain that state rather than drawing fake operational controls or engagement. Keep real asset colors and native UI fidelity separate from Rafii's theme.

## 10. Migrate every actual page using the same DNA

Use Section 21 of the DNA as a recipe library. For every existing route family, implement the appropriate layout and preserve its real behavior:

| Page family | Required application of the design |
|---|---|
| Home/Create and draft detail | Approved composer, shared settings, honest jobs, editable account-specific previews |
| Calendar/agenda | Functional date navigation, quiet cells, consistent filters, readable mobile agenda, timezone and safe rescheduling |
| Queue/review/publishing | Real status counts, batch-selection bar only when active, selected-item inspector, separate approval/schedule/publish actions |
| Inbox/conversations | Readable list/thread hierarchy, real unread/send states, mobile list-to-thread navigation, preserved reply drafts |
| Channels/connections | Real account identity, capabilities, status, reconnect/manage flows, shared folder functionality |
| Voice/Brand Brain/Sources/Assets | Common collections/forms, provenance, permissions, genuine import/processing/version states, actual media |
| Campaigns/suggestions | Ordered editable plans, explicit recurring-draft preparation versus publication, contextual suggestions with evidence |
| Analytics/reports | Real period/account scope, labelled measures, empty/partial/stale states, accessible shared chart grammar |
| Model/API/profile/workspace settings | Grouped forms, masked secrets, clear persistence and permissions, stable theme/preferences |
| Auth/onboarding/invitations/public pages | Matching identity/materials/controls, intact auth/deep links, no forced entrance animation |
| Billing/usage/notifications/error pages | Same UI vocabulary, actual data, preserved commercial and permission boundaries |

This table does not replace the route inventory. Migrate additional existing Rafii-owned pages too. Externally hosted provider authorization/payment screens are outside the styling scope; style Rafii's entry/return/error surfaces without altering provider behavior.

Do not declare completion because global tokens happen to reach every page. Each route needs an explicit composition/control audit and functional verification. Remove migrated dead styles carefully; do not leave parallel competing design systems.

## 11. Shared motion, responsive behavior and accessibility

Consolidate the current motion approach instead of adding Rive/Hyperframe/3D dependencies merely for a tab switch. Use a shared motion preference and animation ownership/cancellation strategy.

Reference timing roles: feedback approximately 200ms; tooltip opacity 180ms plus 4px offset over 220ms; view crossfade 320ms; provider/list swap 430ms; selection lenses 440ms; measured disclosure 480ms; phone deck 560ms. Preserve v9's folder motion after observing its implementation. These are reference roles, not a rule that every task must wait half a second.

Retain actual outgoing layers during crossfades. Keep lenses mounted. Expand from current measured geometry and restore auto sizing after settling. Rapid open/close and direction changes must be safe. Pause decorative SVGs offscreen, in background tabs and when the user requests it. Reduced motion cancels spatial/decorative effects while completing logical state changes cleanly.

Build dark/light, touch, keyboard and small-height behavior together. Preserve deep links, refresh location, browser back/forward, meaningful route history, and existing dirty-state handling. Avoid redirecting all routes to Home or replaying introductions.

Product targets: comfortable essential text, 16px touch text entry, and at least 44px primary touch hit areas where practical. Test composited glass contrast, visible focus, descriptive labels, mixed-state folder checkboxes, modal containment/focus return, nested Escape order, status announcements, 200% text enlargement, long locale/account labels, and RTL. Resting borderless styling must not remove focus outlines or meaningful status distinctions.

Use dynamic viewport/safe-area handling and a sensible scroll model; inspect real mobile keyboard behavior. Headers and fixed footers must not cover the content, active field or confirmation action. Keep the content library's browsing area useful instead of consuming the entire mobile screen with controls.

## 12. Verification and evidence requirements

Write focused failing tests for changed behavior before implementation where appropriate, then run the real project's full available test commands. Record pre-existing failures and environment limitations without concealing them. Historical prototype test counts are not evidence for this build.

Verify at minimum:

- Homepage source selection → real generation request/job → per-account editable draft → persisted draft/review record, using authorized development/test data.
- Two accounts on the same platform remain distinct throughout the whole pipeline; overlapping folders do not duplicate destinations.
- Folder creation/edit/delete persistence, tenant isolation, unauthorized membership rejection, Undo, cancel/apply, concurrent/stale data and no automatic demo import.
- Language shared override/restoration, canonical search, multi-language preservation, model/voice independence, and reasoning request/effective-setting mapping.
- All taxonomy IDs and artwork, Gallery/List/Pairings, categories/app filters, tooltip separation, selected-item integrity, and honest unsupported-format behavior.
- Phone swipe/crossfade on homepage/results/enlarged preview; vertical scroll, rapid interrupts, reduced motion, no caption reset or focus leaks.
- Auth, navigation, deep links, refreshed routes, queue, calendar, inbox and every migrated workflow; source permissions and approval gates remain intact.
- Actual empty/loading/error/permission/offline/partial states. No sample-success fallback when a backend call fails.

Run type/lint/build/unit/integration/browser checks available in the repository. Use provider mocks for deterministic automation and clearly distinguish mock-backed tests from live authorized verification. Never test by actually publishing posts, sending messages, charging a card, or modifying real scheduled content. Record any permission- or cost-gated live check as unverified rather than bypassing it.

Capture before/after browser evidence per route family and state. Cover both themes and 320×740, 375×812, 390×844, 430×932, 768×1024, 1024×768, 1440×1000, 1920×1080. Include large content lists, long names, missing assets, focused/selected/disabled controls, short landscape and keyboard states. Check the complete artwork inventory visually, not only in unit tests.

Record actual provider swaps, reasoning bars, language disclosure, folder unfolding, and phone swiping from the running build. Screenshots and generated concept boards cannot prove motion. Test Chromium and WebKit/Firefox when available; identify physical iPhone/Safari/Edge checks separately. Do not describe emulation as physical-device testing or claim full accessibility/performance conformance from geometry tests.

Compare production bundle/runtime performance against baseline. Lazy-load heavy selectors/previews, pause invisible art, minimize nested blur, clean outgoing DOM/listeners, and avoid new external runtime asset dependencies. A visual redesign must not make basic typing or scrolling unresponsive.

## 13. Execution order, release boundaries, and final handoff

Proceed in reviewable phases:

1. **Discover and baseline:** protect the workspace, read references, build route/wiring matrices, record conflicts and baseline failures.
2. **Foundation and shell:** shared tokens/components, themes, navigation, fields, overlays, state grammar and motion primitives.
3. **Homepage vertical slice:** wire the core generation/edit/save flow and existing selectors without demo state.
4. **Folders and previews:** durable account-based groups, membership snapshots, multi-account pipeline, native deck and swipe.
5. **App-wide migration:** finish each real route family with its proper page recipe; retain every existing functional entry point.
6. **Hardening and handoff:** run full available checks, capture route/motion evidence, audit demo leakage, finalize rollback and coverage.

Use scoped commits/checkpoints. After repeated failures, diagnose the cause rather than layering CSS or bypassing tests. Keep a concise durable progress ledger with completed phases, exact files, unresolved blockers and next step so work can resume without repeating discovery.

This assignment authorizes code changes and development/testing in the existing project. Do not replace a live deployment, merge into a protected branch, run production migrations, change DNS/OAuth/billing, or publish/send social content without explicit authorization. Use an existing authorized preview workflow when available; otherwise deliver the runnable branch and exact local commands. Do not create paid infrastructure or new deployment projects silently.

Preserve or add a narrow, documented rollback path using the existing architecture. A temporary visual rollout flag must not create a second data engine. Any database change must be reviewed, backward-compatible where possible, and accompanied by migration/rollback notes; do not automatically apply destructive changes to production.

### Required deliverables

- Actual integrated code in the correct repository, not a new standalone HTML/iframe.
- Shared design tokens/components and the retained reference files with provenance.
- Completed route coverage ledger and control-to-service wiring matrix.
- Folder persistence/schema/security notes and any required migration scripts.
- Exact commands/results for this build, baseline failures, evidence screenshots and interaction recordings.
- A design-DNA conformance report including justified deviations needed for accessibility or real capability boundaries.
- Branch/commit details, environment-variable names only when relevant, run/preview instructions, rollback plan, and remaining risks.

End with factual status fields: `IMPLEMENTED`, `FUNCTIONALLY_VERIFIED`, `VISUALLY_VERIFIED`, `BLOCKED_OR_UNVERIFIED`, `PREVIEW_DEPLOYMENT`, and `PRODUCTION_DEPLOYMENT`. Distinguish local code, preview deployment, and production release. Do not say “all pages complete” while inventory rows lack evidence, or claim live model/publishing success from mocks.

**Start by locating the current repository and supplied references. Then implement the v9 homepage and complete the app-wide migration under these constraints. Do not return another design proposal as the result.**
