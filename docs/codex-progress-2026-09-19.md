# Codex checkpoint — 2026-09-19

Execution state: Steps 0, 1, 2A, 2B and the authorized parts of 2C are complete locally. Settings URLs remain explicitly deferred. Step 2D was tested on the incoming language branch but its reported failure was not reproduced. Step 2E now includes five CLI effort levels and guided onboarding chat; memory proposals were already implemented. New research connectors await James. Step 2F remains blocked on the live-Threads harness and production migration verification. Nothing was pushed, deployed or published; no production migration ran.

## Commits

- `e52c417` — feat(onboarding): preserve guided tours and welcome clips
- `625fa41` — fix(shell): preserve responsive header and page help
- `8c24467` — feat(home): preserve decorative particle backdrop
- `bdb588e` — feat(channels): preserve capability cards and connection sheets
- `a22cc24` — feat(overview): preserve honest status cards and next-up strip
- `19d2115` — feat(api): preserve integration inventory and honest availability
- `eb6822d` — feat(memory): preserve file disclosure and learning history
- `52cf5aa` — feat(brand): preserve voice status and revision review
- `59fb9cd` — feat(calendar): preserve live status filters and review states
- `6e06cf9` — feat(analytics): preserve per-account coverage and native readings
- `eebcb5a` — feat(ideas): preserve source capture and approval inspector
- `c32754e` — feat(pipeline): preserve complete board and receipt details
- `89ff2bf` — feat(queue): preserve exact approvals and publishing receipts
- `d4e8058` — feat(library): preserve image upload queue and usage details
- `6dbb1bd` — feat(inbox): preserve per-account comments and exact reply approvals
- `1c38926` — feat(workspace): preserve roles and member access controls
- `429ffc7` — feat(audit): preserve event filters and readable details
- `e947fea` — feat(billing): preserve honest allowances and checkout states
- `0259d06` — feat(privacy): preserve data inventory and reviewed controls
- `188cf9f` — feat(models): preserve writer availability and consent disclosure
- `9b38dbe` — chore(onboarding): preserve welcome composition source
- `4b189af` — docs: preserve app update plan and session handoff
- `f6ce211` — refactor(app): unify job states attention and error codes
- `018ac97` — fix(queue): resolve duplicate reviews and permit fresh retries
- `2ca8b10` — fix(app): align shared types navigation and draft actions
- `0a3535e` — fix(library): honor edit access and carry images into scheduling
- `1e686ae` — fix(inbox): persist reply history and require send reconfirmation
- `b40314b` — fix(api): read the public tool registry through shared contracts
- `7df038b` — fix(billing): enforce period and plan limits with private cost access
- `cde3969` — fix(privacy): limit source invalidation to dependent drafts and posts
- `635af90` — fix(models): rescan available writers and disclose learning extraction
- `9798014` — fix(audit): align admin access and refresh recorded activity
- `8a24ef5` — fix(memory): unify proposal history and confirm learning reset
- `d5f0916` — fix(brand): allow voiceless review and clarify voice decisions
- `2ba8d78` — refactor(publishing): share receipts approval and cancel controls
- `7da362c` — feat(shell): add mobile tabs live attention and shortcut help
- `f8d7fbb` — fix(auth): separate verification and preserve invitation access
- `e667699` — feat(api): add expiring workspace tokens with live scope enforcement
- `c527432` — fix(onboarding): align tour motion and voiceless scheduling copy
- `814e011` — feat(agent): expose five CLI reasoning levels end to end
- `423c853` — feat(agent): add durable voice interview with owner review

## Sequence and remaining work

The handoff was the first file read, in full. Main-plan sections 1 and 3 were read before staging. Other main-plan sections were inspected to identify the founder decisions and distinguish finished work from follow-ups.

All 22 preservation commits are complete. Step 1's required documents were read before backlog code: main plan, motion system, post-preview templates, preference learning, and worldwide languages. Page specs are consulted when needed.

Step 2A was followed by §10 rows in order through Models, Audit, Memory and Brand. Step 2C followed those commits. Settings URL reorganization is explicitly deferred. D was investigated next; E implementation followed the reproduction attempts. F cannot be considered complete from synthetic checks.

## Decision received from James

Main-plan §8 item 1: **`published` is still sending until provider verification completes.** James explicitly selected this in the current conversation. This choice is implemented in the shared job-state helpers. Inspect the actual terminal/verified states before consolidating the job helpers; do not equate this decision with successful verification of any particular job.

Main-plan §8 item 13 is resolved by the original request: this Codex session is authorized to make the hand-filtered preservation commits. Do not ask that again.

James subsequently decided:

- Item 3: Audit stays admin/owner-only; fix RLS to match navigation instead of opening navigation. Export stays owner-only. James explicitly clarified: **no retention limit for now**. Do not introduce automatic expiry or deletion.
- Item 6: Show Inbox and Roles to every member; preserve action-specific permission enforcement.
- Item 11: Editors/admins may upload and delete Library images; viewers remain read-only.

Inbox/Roles navigation and Library image permissions are now implemented. Audit API/RLS access is implemented; no export feature exists, so the owner-only export policy is retained as a constraint.

## Remaining decisions resolved by James

The latest reply resolves the remaining eight plan decisions. All decisions below authorize implementation in this pass, except the explicit deferrals:

- Plan item 2: allow approval without active voice; remove the hard block and show a reminder.
- Item 4: API tokens are read/draft/propose only. No direct-publishing scope.
- Item 5: defer the Settings URL reorganization to a separate follow-up.
- Item 7: new/edited sources invalidate only dependent drafts.
- Item 8: refill only at a new billing period; trial expiry stops publishing. Leave `assist-bounded-v1` unchanged and report real usage before proposing retirement.
- Item 9: source retraction affects only dependent drafts/posts.
- Item 10: enforce seat and connected-account limits.
- Item 12: recorded reply approvals are allowed without a sender; each must be reconfirmed before a real send worker may use it.

No additional founder answer is needed for these scoped choices. Production execution boundaries below remain in force.

Additional boundaries from the handoff:

- Do not run production migration `013_locale_tags.sql` without James's specific approval.
- Production migrations 009/011 and Supabase Auth TOTP/WebAuthn dashboard settings need James's involvement. Their production state was **not checked in this turn**; the handoff reports them as outstanding.
- Migration 010 was not applied or checked. Its production application and the live-Threads UI pass remain part of F's pre-deploy work.
- Flag any other externally visible product behavior change beyond a straightforward bugfix before applying it.
- Do not start desktop companion transport without an explicit request.

## Validation

Executed from `web/` against the existing working tree, including the other sessions' unstaged files:

- `npx tsc --noEmit` — passed, zero errors.
- `npx oxlint src` — passed, zero errors; one existing `consistent-function-scoping` warning for `targetLabel` in `members-view.tsx:342`.
- `POSTRIFF_DIST_DIR=.next-codex-handoff-20260919 NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_SENTRY_DISABLED=1 npx next build` — passed. Build warning: missing fallback-font override values for Google Sans Flex.
- `git diff --cached --check` — passed for each preservation group.
- `ffprobe` — both themes' MP4/WebM files are 896×560, eight seconds; both JPEG posters are 896×560. Light/dark posters were visually inspected.

These are working-tree checks, not proof that the commits build in isolation from the uncommitted page work.

A signed-in browser pass now exists against an isolated **synthetic** harness (API :4397, web :3197, disposable PostgreSQL :55947). It covers Overview/header states, Pipeline editing, Calendar controls, Library image preselection/picker and viewer Inbox/history. All browser passes had zero page errors. Scripts and screenshots are under `/tmp/codex-{handoff,backlog-b,library,inbox}*`.

`validation_unavailable`: F’s signed-in **live Threads** harness has not been located or tested. At entry :4331 was absent; it now runs `scripts/postriff_dev_hosted.py` with synthetic providers, confirmed through the other task and process/source inspection. :4326 is a separate alpha app. Shared :3100 was left untouched. Synthetic checks are not deployment readiness.

The initial build directory and its added tsconfig entries were cleaned after preservation validation. Later isolated caches remain ignored locally. This session removes only its own generated tsconfig includes; other sessions’ configuration edits are preserved.

## Shared-tree and integration cautions

At entry, `consumer-saas` was at `707aefe`, eight commits behind the existing `origin/consumer-saas` reference (`5dd8188`). No fetch, merge, reset, stash, or rebase was performed. After the 22 preservation commits it is ahead 22 / behind 8 relative to that reference.

The incoming history contains the worldwide-language components and migration 013. They are absent from the current checkout. Integrate carefully after preserving shared-tree work; D cannot be reproduced against this checkout as though those components were already present.

Preserved unstaged work includes:

- `.claude/launch.json` and vendor submodule working-tree changes.
- Account-picture backend/provider/privacy/test/migration 012 changes.
- Post-preview templates, picture helpers, preview tooling, `html-to-image` dependency changes, icons, and preview-specific gitignore changes.
- Agent conversation/variant-card edits from another session.
- Shared API client/type additions for account pictures. The manifest channel-id field was hand-staged with Overview.
- Unrelated research/specification documents. All inherited rebuilt pages, motion composition source and plan documents are now committed.

Some §10 tour follow-ups are already present in the preserved `tours.ts` (including Pipeline, Library, API, Billing, Privacy, Models, and Audit tours). Check actual anchors and conditional steps before treating each row as still missing.

Tour motion mismatch resolved in c527432: one 250 ms pulse, transform/opacity movement, 150 ms close, reduced-motion support. Voice-free scheduling tour copy now matches James’s decision. Existing motion throughout the entire application was not exhaustively re-audited.

## Step 2A current work

- Shared lib/jobs.ts drives Queue, Pipeline, Overview and header; published remains sending and only verified is complete. Shared attention drives Overview, Home and sidebar approval count.
- AlphaError has stable optional code overrides and status defaults; hosted/local HTTP preserve error text/status and return code. ApiError.code tolerates old or malformed responses. Workspace revision, draft revision, step-up and MFA have distinct codes.
- Tests: 64 pytest tests and 22 subtests passed using /tmp/codex-handoff-tests-20260919; node --test web/tests/shared-contracts.test.mjs passed. tsc/oxlint pass (one inherited warning). Isolated .next-codex-backlog production build passed.
- Own synthetic API is localhost:4397; disposable PostgreSQL port 55947; own web is localhost:3197, dist .next-codex-ui. Logs /tmp/codex-handoff-{harness,web}.log. This is not a live Threads test.
- Tailwind scanned a compiled cache when custom dist dirs were not ignored. Added only /.next-codex-*/ to web/.gitignore, restarted own web with clean own cache; page now returns 200. The inherited /.snapshots/ addition belongs to other work.
- web/AGENTS.md and CLAUDE.md appeared automatically from installed Next 16.3.5; read AGENTS and relevant installed server/client guide, leave these generated files unstaged.

## Step 2B implemented groups

- First shared rows: distinct Ideas icon/Channels shortcut, current InfoButton contents, Calendar anchors, actual API source/analytics/job fields, shared profile channel status, Queue/Pipeline aliases, duplicate-review resolution/fresh retry keys, optional snapshot polling, accurate scheduling gate, Queue cancel tips, exact receipt deep links, preserved author edits/rejected-draft restore, Roles navigation, member-removal note, invitation query opt-out, real access documentation and shared sign-in-again handling.
- Library: shared Asset fields/in-flight helper; context-gated tips; image preselection from both Library entry points; shared thumbnail AssetPicker; cache-level blob cleanup; edit-authorized image changes with sample protection and media configuration code. Backend role tests, object URL lifetime tests and browser interaction pass.
- Inbox: server provider implementation metadata; production verification callback for comment ingestion (reviewed Threads only, transaction savepoint); shared reply types/history/counts; all-member nav; accurate starter-line and approval wording; approvals recorded while sender disabled carry requiresReconfirmation. Legacy approvals also fail closed. Production runtime never enables reply sending. Disposable PostgreSQL test proves flipping the test-only sender flag cannot replay old approvals and explicit per-reply reconfirmation is required. HTTPS transport context bug fixed in a hand-filtered shared-file hunk.
- Existing Pipeline/API tours and connected-only Overview counts were already present; verify against actual row requirements rather than duplicating them.

Recent validation: 23 backend tests + 8 subtests for Inbox/hosted contracts, disposable PostgreSQL audience script, Library role test (14 hosted tests + 8 subtests), shared job/API and media URL Node tests; tsc zero errors; oxlint zero errors/one inherited warning; isolated Next build passes. Each UI group was browser checked with synthetic data.

Additional §10 Billing navigation decision was answered and implemented: show Usage & plan to every member; keep costs and billing controls owner-only. API redaction landed before opening navigation.


## Billing and Privacy checkpoint

Billing commit 7df038b enforces seat/account limits, new-period-only refills and trial-expiry publishing holds. Hosted publishing checks SQL entitlements, so an old trial timestamp does not block an active paid subscription. Usage navigation is open to every member per James's additional answer. Private costs and checkout/portal controls remain owner-only. Migration 014_billing_cost_visibility.sql restricts direct ledger reads to owners; applied only in disposable local PostgreSQL, never production. assist-bounded-v1 is unchanged; real customer usage has not been queried.

Billing validation: 83 Python tests + 37 subtests passed; disposable repository/plan-guards/Stripe scripts passed, using synthetic providers. Node contracts/media-cache checks, typecheck, lint and isolated Next build passed. Synthetic browser checks covered registry loading, no additional tour usage query, viewer usage navigation and absence of costs/billing controls.

Privacy commit cde3969 leaves the shared brief revision unchanged for source addition/fact approval/retraction/policy changes. Only dependent drafts become stale or blocked; publishing preflight reads the draft's source list rather than the whole brief. Ideas and Privacy share exact dependent draft/proposed update/held post counts. Public deletion instructions no longer promise in-flight cancellation or a nonexistent delete-source action. Diagnostics history says Created rather than Shared.

Privacy validation: 61 tests + 24 subtests passed (alpha, phase2, content types); typecheck, lint (0 errors, one inherited warning) and isolated build passed; synthetic browser selected a source and checked matching scoped impact on Privacy and Ideas, no page errors. Scripts/screenshots: /tmp/codex-privacy-*.

Another active session has since added publishing processing/status/support changes in shared backend/worker/social/outcomes, shared UI jobs and new tests. Their changes remain unstaged by this session. Privacy's store.py was hand-staged from HEAD to exclude their IN_FLIGHT processing addition. Do not overwrite those changes.


## Models and Audit checkpoint

Models commit 635af90 consolidates the saved writer choice; an authenticated POST /api/ideas/models/rescan requires editor access and forces CLI installation/auth probes, including newly installed enabled routes. API summaries disclose configured rules/local/cloud learning extraction and consent eligibility. Codex reports no budget cap as null. Browser fixtures verify shared fallback, rules-only disclosure and one authenticated rescan POST. Validation: 42 tests + 8 subtests, tsc, oxlint (0 errors), isolated Next build, browser (0 page errors). CLI tests used fake executables; no paid model calls.

Audit commit 9798014 enforces admin/owner API reads and adds local candidate migration 015_audit_visibility.sql. No retention expiry/deletion was introduced. Direct routes and Overview respect the same roles; relevant audit-writing mutations refresh the shared audit query. Audit has no export endpoint/UI in the current code, so no new export feature was added; James's owner-only export restriction applies if that feature is introduced. Validation: disposable SQL exercises all five roles and cross-workspace access, retains records; 16 hosted tests + 8 subtests; typecheck/lint/build and synthetic browser access/refresh checks passed. Migration 015 has NOT been applied to production.

Memory changes committed in 8a24ef5: shared actionable history, error/retry, proposal expiry, hold-to-confirm reset, honest Recent total and shared WhatDraftsRead. Backend tests (29 + 8 subtests), disposable memory lifecycle/capped-total SQL and browser/typecheck/lint/build passed. Brand’s reminder-only scheduling behavior and owner decisions followed in d5f0916; 86 tests/33 subtests and browser/typecheck/lint/build passed.

## Step 2C local checks

Shared JobDetailSheet, ReviewApproveButton and JobCancelHold now serve Queue/Pipeline. Synthetic browser checks verified both receipt/approval entry points and exact digest submission. Shell browser checks verified live attention, shortcuts, mobile Calendar and More navigation, and 375px no overflow. Auth browser checks verified /auth/verify destination preservation, passwordless /auth/reset guidance, viewer invite routing to Overview and signed-out invite continuation. No real MFA factor or email was used. Node redirect/role tests passed. Required typecheck, lint and isolated builds passed (including the final token build).

One isolated Next dev cache became corrupt during HMR. Only our :3197 server was restarted; its old cache was moved to `/tmp/codex-ui-cache-before-restart-20260919`. The shared preview remained untouched. The browser-only React Query dev panel was hidden in the mobile test because it overlays the bottom-right navigation; this is not present in a production build.

Additional founder decision: trial plans may create read/draft/propose tokens. API token security review and usage contract: `docs/postriff-api-tokens.md`. `016_api_tokens.sql` has run only in disposable PostgreSQL.


## Step 2C tokens — complete locally

Commit e667699 adds service-role-only token storage in migration 016, mandatory expiry, one-time reveal, recent interactive sign-in for creation, live creator membership intersection, read/draft/propose route allowlists and rate limits. Trial plans are allowed per James. Publishing, replies, connections, billing and token management are unavailable to tokens. The UI never places the raw token in the query cache. See `docs/postriff-api-tokens.md` for the security review.

Validation: 62 tests/29 subtests; disposable PostgreSQL token lifecycle/RLS/live-role tests; browser creation, expiry, one-time reveal and keyboard-hold revocation; typecheck/lint/isolated build passed. No real token was created for a customer.

## Step 2D — reproduction evidence, no speculative fix

The shared branch does not contain LanguagePicker/ChannelLanguageChip. The incoming origin/consumer-saas history does. An isolated worktree at `/tmp/codex-language-popover-20260919`, branch `codex/language-popover-handoff`, base `5dd8188`, was used for the actual Home composer.

Three browser cases passed: reduced-motion desktop; ordinary-motion desktop with rapid reopening; ordinary-motion mobile at 390×844. Starting with English, each added French by click, German by Enter and Japanese by click: three saved actions and four distinct languages, zero page errors. Tests used a synthetic snapshot/save API. Scripts: `/tmp/codex-language-{browser,fast,mobile}.cjs`.

The initial fixture failure (undefined snapshot) was corrected before those passes. The reported popover bug was not reproduced; no language source was changed and no fix is claimed. Incoming commits were not merged over shared uncommitted work. If it still occurs, the failing page/channel/browser and interaction sequence are needed.

## Step 2E — implemented and decision-gated work

- Existing memory conversation proposals were verified in `ideas._memory_turn`, the intent router, ProposalCard rendering and git history; no duplicate implementation was added.
- Existing Exa search/Jina reading remain in place. Research beyond those sources is **not implemented**: adding platform connectors changes data recipients. James was asked whether to defer or select a new source; no answer yet.
- 814e011 implements James’s five CLI levels: Low, Medium, High, Extra High and Max. Legacy Quick/Standard/Deep map to low/medium/high. The selected level travels through Home and conversation, API requests, CLI arguments and stored runs. Claude side-job extraction keeps its prior default. Each model’s catalog carries its runtime’s levels. No silent fallback if a model rejects an effort. Migration **017 must precede deployment**. Validation: 40 tests; isolated PostgreSQL all five levels, aliases and pre-mutation rejection; synthetic browser selected all five and captured Max in the request; required web checks passed. Installed CLI help/schema were inspected; no paid CLI generation ran.
- 423c853 implements the approved guided onboarding chat. It reuses Brand’s question/choice schema, persists answers in a conversation, handles optional samples and creates a proposed voice only. Active voice, identity and jobs remain unchanged until an owner reviews on Brand. The existing owner approval applies the proposed context and voice together. Duplicate/stale replies fail safely; samples, viewers and API tokens cannot change the interview. The canonical question file is `src/postriff_alpha/voice_interview.json`; the web copy is `voice-interview.generated.json` because API/web services package separately. When changing questions, copy the canonical file and run the parity test.

Onboarding validation: 57 tests/18 subtests; disposable PostgreSQL durable/reloaded replies, replay rejection, editor proposal/owner activation, unchanged active voice/context before approval, token/viewer denials and zero runs; browser Home → interview → reload → optional skip → proposal on Brand, zero page errors and no approval/publishing request. Typecheck, lint and isolated build passed. Screenshots: `/tmp/codex-onboarding-proposal.png`; logs/scripts `/tmp/codex-onboarding-*`.

## Step 2F and deployment boundary

Migration 010 has not been applied to production by this session. The required live-Threads harness is still unidentified; the current :4331 server uses synthetic identity/providers. Earlier Memory/Home/conversation checks are local/synthetic and do not close this requirement.

The connected Supabase account listed two projects, one explicitly Mybestlifeos. A metadata-only check on the other found none of the PostRiff billing/workspace tables. This repo has no configured live Supabase URL. No customer data or production migration was queried/changed. Therefore actual `assist-bounded-v1` subscribers and usage are **Unavailable**, not zero; the plan remains unchanged. The actual PostRiff project reference is required to obtain the requested read-only aggregate counts.

Production status of 009/011 and MFA dashboard settings remains unverified; the handoff reports them outstanding. James must confirm/perform the dashboard steps. Migration candidates 014 (private costs), 015 (Audit RLS), 016 (tokens) and 017 (CLI reasoning) were tested only in disposable PostgreSQL. 013’s one-way locale rewrite still needs specific production approval. Nothing in this receipt authorizes production execution. Before deployment, update the outdated Vercel CLI with `npm i -g vercel@latest`; no global package was changed here.

## Exact pending inputs / deliberately skipped work

1. **Research decision:** defer new connectors, or identify the next source and consent scope. Existing Exa/Jina stays unchanged meanwhile.
2. **Live-Threads harness:** provide its local URL or task name for the required Memory/conversation/Home pass. No live approve/schedule/publish actions are planned.
3. **Production project:** identify the PostRiff Supabase project so real assist-bounded-v1 aggregate usage and migration state can be read. No retirement is proposed without those counts.
4. **Production execution / MFA:** migrations 009/010/011, new candidates 014–017 and Auth MFA setup remain deployment work; 013 explicitly requires separate approval. Dashboard changes require James. They were not executed.
5. **Language bug if still present:** provide the failing surface/browser/sequence; all three isolated reproduction cases passed. No incoming language merge or speculative source patch was made.

Settings URL reorganization is deliberately deferred by James. Desktop companion transport is outside this pass. Other sessions’ account pictures, post previews, publishing receipts/lifecycle, source-safety fixes and research artifacts remain unstaged. The branch is not claimed deploy-ready or independently validated without that working-tree context.


## Local cleanup and resumption

Own web/API processes on 3197/3198/4397/4398 were stopped after validation; the disposable API harnesses clean up their databases on shutdown. Shared servers on 3002/3100/4326/4331 were not stopped. Temporary browser scripts, logs, screenshots and ignored build caches remain under /tmp or the local web cache directories. The language worktree remains available for reproduction; no language source change exists there.

The last code commit for this pass is 423c853. Final `npx --no-install tsc --noEmit` passed after removing only this task’s generated tsconfig includes. The existing shared configuration edits, including the other session’s wp04a includes, remain untouched. The documentation receipt is committed separately.
