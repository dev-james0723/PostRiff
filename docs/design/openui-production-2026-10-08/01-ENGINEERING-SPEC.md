# Rafii × OpenUI — Full Production Specification

**Status:** Implementation-ready directive; not implementation evidence.  
**Target:** Full release by 2026-10-09, America/Indiana/Indianapolis, subject to the mandatory release gates.  
**Evidence baseline:** `06-EVIDENCE-SOURCES.md`. Names of proposed modules/interfaces below are design decisions, not assertions they already exist.

## 1. Product outcome

Rafii should turn an ordinary request into a live, grounded workspace inside the existing conversation. Users can inspect actual records, manipulate filters, compare outputs, fill forms, prepare or execute permitted actions, and ask for changes to the interface without losing their task or conversation. This must work in the full Agent Chat, Site Agent panel, expanded workspace and mobile sheet. Existing browser voice shares the same conversation and selected objects. Founder-agent integration uses the same renderer infrastructure with a separately authorized component/tool manifest.

This is NOT a site generator, arbitrary-code executor, replacement chat application, collection of static demo cards, or an automatic grant of new permissions. Generative UI makes existing Rafii capabilities more usable; it does not by itself improve voice learning, create missing analytics history, grant provider OAuth approval, or make every unrelated product defect disappear.

The scope is the full GenUI integration across all nine journeys below, plus fixes to integration-related blockers and regressions in the app's launch-critical paths. Do not silently expand it into a rewrite of unrelated social integrations, billing products or the whole admin design. Discover such unrelated blockers and report their exact impact; do not claim the whole app launch is certified if they invalidate the tested release.

## 2. Non-negotiable architecture

### 2.1 Keep the existing agent and application authority

Preserve the Python OpenAI Agents SDK Manager, specialist-as-tool architecture, model router, guardrails and structured answer contract. Preserve the existing composer, attachments, model choice, credits, memory consent, conversation IDs, page-context guides, source links, private assets, approval paths, audit and usage ledger. OpenUI is a presentation/runtime layer, not a new agent brain.

Use `@openuidev/react-lang` and the official parser core with Rafii-owned components. The full OpenUI AgentInterface is not required and must not replace the existing chat shell. Do not scaffold a second app or introduce a parallel conversation/memory/billing/approval system. Do not upgrade Next/React/Agents SDK merely because an example does so.

### 2.2 Data flow

User intent + authorized app state → existing Rafii turn → verified tools/results/proposals → UI projection + capability manifest → restricted UI Presenter → progressively rendered OpenUI → guarded query/action bridge → original domain services → re-read + native receipt + conversation context update.

Authoritative answer text, permission/billing warnings, approval confirmations and execution receipts remain in a native layer OUTSIDE the generated subtree. They must remain usable when generation, parsing, queries or component rendering fail. A green generated card is never evidence that an action happened.

### 2.3 Presenter

Introduce an isolated presentation stage with no business-write tools and no conversational handoff. It receives only the approved projection, versioned component subset, permitted query/action descriptions and current artifact state. It may compose layout, state bindings and presentation patches. It cannot invent resources, grant permissions, decide approval, change billing or run arbitrary tools.

Do not replace the Manager's structured output with an OpenUI-only instruction. Start presentation from a completed authorized tool-result projection when available; update resolved data bindings as further verified results arrive. Do not launch one LLM call per token/tool event. Coalesce results into one generation per artifact and only intentional semantic edits/one bounded repair. For a simple turn whose Manager produces only a final result, presentation may start then; record its true time origin rather than claiming end-to-end reasoning streamed.

Prefer UI selection through a deterministic eligibility predicate on intent/result structure. Greetings, plain text questions and trivial acknowledgements do not invoke the Presenter. User requests such as 'compare', 'show a table', 'filter', or 'add a chart' should produce meaningful appropriate UI, not decorative clutter.

### 2.4 Cross-language contract and parsing

One versioned component/tool definition generates the component specification, prompt assets, manifest hash and frontend/backend contract fixtures. No hand-copied Python OpenUI grammar. The official parser must be used for structural validation and edit merging, with conformance tests against the installed, pinned package exports.

C owns a trusted Node parser adapter for canonical validation and patch merging. A wires it through the existing deployment's web/Node service with a precise authenticated internal route when server-side validation is needed. Do not assume Node exists inside the Python function. Validation performs parsing/policy analysis only: no rendering side effects, network queries or tool execution. Scope the request to an authenticated run and reject oversized inputs before parsing. No new external parsing service.

The browser still validates and renders incrementally. Partial source is untrusted preview data; writes stay disabled until its revision has server-accepted source/hash and current action bindings. Client-reported parse success alone is never authoritative. Never use `eval`, dynamic function execution, raw HTML injection or regex as a replacement for the official parser.

### 2.5 Streaming deployment

The current `/api/*` routing goes to Python. Prove real chunk delivery on a deployment, not only localhost or a simulated typing animation. Reuse the current Python transport if it can flush correctly. If not, A introduces the smallest isolated streaming adapter/precise route while keeping original agent services, auth, ledger and business state. Do not migrate the whole API or borrow phone-session state.

Persist the artifact and ownership/attempt state before provider dispatch. One producer owns each artifact revision. Use existing durable job machinery where it actually provides guarantees; otherwise keep ownership within the streaming request, checkpoint source, and mark/settle interruption on disconnect or timeout. Do not create a detached in-memory task after the request ends and call it durable.

SDK finalization, usage reconciliation and durable checkpointing must complete before an artifact is marked ready. The last visible token is not run completion. Normal reconnect replays saved events and attaches to an existing producer; it never creates a second business action or unannounced new LLM attempt. [S9]

## 3. Required core capabilities — same release

| ID | Capability | Shipping requirement |
|---|---|---|
| C01 | Dynamic composition | Real model composes Rafii components differently for the task; not fixed if/else cards with an AI label. |
| C02 | Progressive rendering | Useful root and stable components appear while provider source arrives; progressive loading is accessible. |
| C03 | Reactive state | Inputs, selections, tabs, filters and derived views react locally; no LLM for ordinary UI changes. |
| C04 | Live queries | Authorized, bounded tools feed fresh data; cancellation, cache scoping, refresh/backoff and explicit as-of state work. |
| C05 | Forms and mutations | Validated user-triggered forms route through existing domain commands/approval paths; no mount-time writes. |
| C06 | Incremental editing | 'Add a chart', 'compare the selected two', 'change the period' can patch the existing artifact; preserve unaffected state and history. |
| C07 | Rich grounded views | Tables, line/bar charts, source panels, timelines, galleries, comparisons and task states use real data/references. |
| C08 | Persistence and recovery | Reload, reconnect, concurrent tabs, old artifacts, revoked data and failed edits have tested recovery. |
| C09 | Surface continuity | Full chat, panel, expanded/mobile surface and browser voice use the same artifact/conversation identity. |
| C10 | Reliability and operations | Bounded repair, graceful native fallback, observable errors, correct credits, production activation and rollback. |

OpenUI documents generation/execution separation, reactive variables, queries/mutations, renderer state callbacks and incremental edits. Use its actual supported APIs rather than pretending a handwritten approximation is native. Feature-probe the pinned version before dispatching dependent work. [S1–S7]

## 4. Full Rafii journey coverage

All J01–J09 are in the release. The normal path must pass using real services in a controlled test workspace, in addition to empty/permission/unavailable states. An unavailable-state screenshot alone is not normal-path coverage.

| ID | Journey | Required UI and actions | Authority / pass evidence |
|---|---|---|---|
| J01 | Draft and platform studio | Compare drafts, show evidence/platform/language, select, edit an unscheduled draft, request rewrite/adaptation, preserve user-selected writer/voice. | Read full current draft and revision; existing edit/writer path; re-read saved result. Selection is not publication approval. |
| J02 | Calendar and publishing operations | Agenda/week view, current queue status, timezone-aware date controls, collision warnings, prepare rescheduling; original apply/dismiss. | Query calendar AND queue; exact date/time/zone and revision/digest on proposals; no direct public publishing. |
| J03 | Universal Library / Living Archive | Search/filter authorized records, real thumbnails and previews for supported images/videos/audio/documents/links, sources/lineage and selection for a draft. | Existing library/index/media APIs, ownership and consent; private URLs not exposed to model; unauthorized/expired refs denied. Do not reduce to image_list when the real Library exists. |
| J04 | Brand Brain / Learn My Voice | Source selection, eligibility and cloud-consent status, learned-vs-proposed preferences, evidence/confidence, edit/confirm through existing paths and verification of actual learning job results. | Existing voice-learning/memory services; no invented 'trained' state or silent source uploads. UI must report the true backend state. |
| J05 | Campaign planning | Goal/audience/channel forms, plan/table/timeline, content membership, dependencies, progress and review of proposed changes. | Existing campaign commands and verified task state; multi-step failure preserves completed safe work and names unfinished steps. |
| J06 | Analytics / content performance | Date/platform filters, comparative tables and charts, drill-down, sample size, units, timezone, coverage/as-of and missing-data explanations. | Existing metric definitions and authorized analytics; deterministic calculations; unknown is not zero; derived scores cite rule/version. |
| J07 | Research / content intelligence | Source-backed briefs, comparison matrix, citations with source date, source-to-draft link and deliberate follow-up; add/remove chart or section through patch. | Existing approved research route and source consent; external text is data, never instructions; research-off state is explicit. |
| J08 | Automations / workspace recovery | Build or inspect recurring draft plans, show next run/timezone/status/history, prepare permitted changes; connection status and safe in-app recovery guides. | Existing automation proposal/decision and status APIs. Do not enable real outbound recurrence, disconnect accounts or expand OAuth grants merely to pass a test. |
| J09 | Founder agent | Reuse engine for authorized read-only revenue/cost/reliability/support summaries with drill-down and source coverage; keep native privileged controls. | Separate founder authentication/AAL2 and manifest; never load founder definitions/data into consumer chat. MRR interval/terms, cost dimensions or absent metrics remain unavailable until backed by real records. |

For a missing in-repo adapter, implement the integration; do not stop with 'tool unavailable' when its source service exists. For missing external approvals/data, complete all independent integration and fault states, report the precise remaining prerequisite, and do not label that normal path verified.

## 5. Rafii component system and visual behavior

C owns reusable primitives: RafiiRoot, Stack/Grid/Section, Card, Tabs, Accordion, Text, EvidenceLink, Empty/Loading/Error state, ToolBoundTable, ToolBoundChart, Form, Input, Select, DateRange, AssetPreview, SelectionList and guarded ActionButton. E owns domain wrappers for J01–J09. Reuse existing Rafii/shadcn/Base UI primitives, theme tokens and chart/table dependencies, rather than importing a competing global CSS theme.

Use per-journey component groups, not the whole registry in every prompt. C01 does not mean maximize component count. Bind facts through resource/query references; computed visuals must derive from those values. Separate generated commentary from stored facts and verified status. Model-selected decorative words cannot masquerade as exact metrics, source titles or evidence.

Desktop: inline response for small results; expanded working surface for dense tables/forms. Panel: preserve narrow readable layout and explicit expand. Mobile: same artifact in an accessible full-height sheet, safe-area/keyboard aware, horizontally scroll only genuinely wide tables. No new conversation when expanding. No fixed-height clipping, nested scroll traps, input loss or constant auto-scroll while reading earlier messages.

Stable statement/component IDs, not array-index remounts. Preserve focused input, text selection, user edits and selected rows across stream chunks, refresh, layout patches and viewport changes. An edit that removes dirty form state requires a native warning/recovery path; cannot silently erase it. Loading/success/error announcements are concise, deduplicated and contain no raw DSL.

Support existing app locales, with explicit English, Traditional Chinese/Cantonese and Simplified Chinese coverage, long text, emoji, locale dates/numbers and RTL where the app supports it. Keyboard access, visible focus, accessible labels, screen-reader table/chart alternatives, contrast and reduced-motion are release gates. Do not generate unnecessary motion effects to show the UI is 'AI'.

## 6. Data, actions and user intent

### 6.1 Capability manifest

Each artifact receives a server-created capability manifest scoped to principal, workspace or founder scope, conversation/run, permission version, permitted resources/query names, argument constraints, action bindings, egress policy, source timestamp and expiration. The model can select an existing binding, not create authority. Backend checks every query, action, refresh, read and replay against current access.

Principal is derived from authentication. A workspace path or body field is a requested scope, never proof of membership. Resource IDs are re-resolved within that scope. All caches, event streams, live subscriptions and form state must include tenant/principal scope and be cleared on logout/workspace switch.

### 6.2 Queries

Pure local filter/sort/tab actions do not invoke a model. Read queries use an allowlisted function map with typed arguments. Do not pass a complete MCP client, raw SQL, arbitrary URL fetcher or generic tool executor to generated UI. Query loading is not zero/empty business data. Refresh policy, bounds and deduplication are in `02-CONTRACTS.md`.

Queries must have read-only semantics even if malicious output labels a write tool as `Query`. Do not trust the OpenUI expression type to enforce the server effect class.

### 6.3 Writes, proposals and user actions

There is one guarded action dispatcher. Only an explicit user-triggered, registered control can initiate a permitted mutation. Every action checks current permission, revision, schema and binding; uses durable idempotency; routes to the original domain command; re-reads the outcome and creates the existing audit/receipt. An interrupted response must reconcile the original idempotency key before retrying.

For native OpenUI Mutation/@Run support, wrap execution with the trusted action activation context described in the contracts. If the pinned SDK cannot expose the required safe interception, implement the equivalent user-triggered form via Rafii-owned components and `onAction` while retaining native queries/reactive state; document the adapter honestly. Never expose an unguarded write function to `toolProvider` just to claim every syntax form works. A negative 'Query(writeName) on mount' test is mandatory.

Publishing, sending, buying, deleting, disconnecting, secrets and privileged account changes remain outside this generated execution surface. Link to the original authenticated review page when necessary. User urgency does not override tenant rights, an existing approval step or provider policy. Actual scheduling/automation changes use their current proposal/digest/expiry/decision path, not a second approval store.

### 6.4 Interaction memory

Record meaningful selections/submissions as structured context with artifact/revision/entity IDs and their actual outcome. Debounce local form persistence and whitelist fields. Do not append every keystroke to model history or logs. A follow-up referring to 'the second draft' must resolve against the stable selection/order at the time of the interaction, not a subsequently reordered live table.

## 7. Persistent artifacts and incremental editing

Reuse the existing message/run artifact machinery. A message stores artifact references and native result; revisioned presentation source/metadata lives in a bounded artifact record attached to the existing run model. Technical additive storage/indexes are allowed only where needed for CAS/idempotency; no parallel conversation, approval, memory or credits database.

Store canonical source, library/language/prompt/contract versions and hashes, approved bindings, safe state, fallback and generation/validation status. Preserve prior revision source/history. A patch specifies baseRevision and baseSourceHash; server-side official parsing/merge and authorization checks precede CAS commit. A stale patch returns conflict and offers rebase/retry of presentation only. It cannot overwrite another tab's accepted state or change action scope.

Persist source/references according to existing data-retention policy; do not duplicate private datasets in public HTML or localStorage. Historical messages show as-of data distinctly from live refreshed data. Revoked/deleted sources are reauthorized before access; old snapshots are not a bypass. Failed/unsupported old versions get a native fallback instead of silently regenerating and charging.

Load/refresh/replay does not call the model. Retry or semantic UI edit is explicit, separately metered and never reruns completed business actions. Older library versions use compatible rendering when verified; otherwise safely render the stored fallback. Prefer backwards-compatible changes and avoid destructive migrations.

## 8. Voice, agent progress and continuity

Browser voice reads `speakableSummary`, never DSL, IDs, raw chart data or a speculative generated success message. Text/voice selections share the current conversation and artifact references. Existing spoken approval ambiguity, expiry and permission binding remain intact. Phone mode does not require a second visual UI; preserve its backend behavior and test shared-runtime regressions without starting real outbound calls.

Progress uses safe task/tool states, not private model reasoning or hidden chain-of-thought. A task is done only when its tool verified it. Distinguish 'preparing interface', 'waiting for data', 'needs your review', 'saved', 'scheduled' and 'published'. Do not mark the business task failed solely because visual generation failed.

## 9. Reliability, privacy and cost

Parser error, unknown component, invalid props, missing root, unresolved final reference, query denial/failure, render exception, provider timeout and disconnect all preserve a usable native answer. Keep last known valid revision. Partial writes are never enabled. Auto-repair is presentation-only, at most once per generation; deduplicate error callbacks, respect remaining budget, and never start an infinite render→repair loop.

Use the existing model/provider router and verified prices. Respect local-only, CLI/BYOK and cloud-memory boundaries; never silently choose a cloud presenter for a denied route. Do not hardcode model aliases from this document. Reserve appropriate budget before each physical generation/repair attempt, use no hidden SDK retries, track final or unknown usage, and settle exactly once. The user's original turn limit must cover the combined admission plan; a separate presentation reservation must not bypass it. A render fallback cannot cause automatic credit compensation without ledger reconciliation.

OpenUI OSS does not require adopting OpenUI Gateway, Autofix or hosted observability. Keep these optional external services off unless already explicitly authorized for Rafii, with data policy and budgets verified. Implement local validation, existing-provider repair and existing observability now, not as 'phase two'. Set `OPENUI_TELEMETRY_DISABLED=1` before dependency installation and do not enable runtime telemetry. [S8]

Do not log prompts, complete DSL with private values, drafts, writing samples, tokens, secrets or raw tool arguments to general telemetry. Restricted source artifacts follow conversation privacy. Metadata metrics cover latency, parse/render validity, fallback cause, query/action result, duplicate prevention, revision conflict, cancellation, attempts/tokens/cost and scope-safe correlation IDs. Sanitize errors before exposing them to the model or user. Use existing monitoring rather than adding a new vendor automatically.

## 10. Production scope and completion

Mandatory gates in `04-ACCEPTANCE.md` include real provider generation, real test-database actions, deployed transport, tenant/RLS negatives, mobile/iPhone evidence, existing-feature regression, accounting, rollback and actual production smoke.

A canary is an immediate deployment safety step inside this release, not the final deliverable. After the checks pass, activate for intended eligible production users under existing feature/plan permissions. Do not declare the project done with default-off flags, a hidden route, three staged demos, or a preview-only deployment. Do not activate unverified writes to meet the date.

Product release completion requires exact SHA, PR, CI, deployment identity, canonical origin, activation scope, evidence matrix and rollback receipt. The next-day target does not justify missing evidence. When genuinely blocked, finish independent work, state the exact external prerequisite and retain the honest partial-release state. Never label a blocked release 'production-ready'.
