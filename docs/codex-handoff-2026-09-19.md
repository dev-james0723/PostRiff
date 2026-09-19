# Codex handoff — 2026-09-19

A prior Claude Code session hit its usage limit mid-task and had to stop.
This document hands off the remaining work so a fresh agent (Codex) can
continue without losing context.

## CONTEXT

Repo: `/Users/ouxianxing/Documents/James-Au-Studio`, branch `consumer-saas`.
Several parallel Claude Code sessions share this same working tree, so
treat any uncommitted file you didn't create yourself as possibly someone
else's in-progress work, not garbage.

Ground rules (apply to everything below):

1. **Real data only.** Numbers/status/progress must come from a live
   snapshot or API call. Never show a fake 0 for "unavailable" data —
   show "Unavailable" and let it stay unavailable.
2. **Remind, don't block.** Rules may add a reminder to a draft/action.
   They must never produce a hard failure or a blocked run because a fact
   is missing — missing facts trigger research, not refusal.
3. **General, not personal.** Anything shipped to users (templates, tour
   copy, examples, empty states) must read the same for a designer,
   teacher, shop owner, or developer — no reference to a specific named
   user.
4. **Capability honesty.** Each connected channel is graded per-capability
   (Direct / Assisted / Unsupported + evidence + verifiedAt). Never show a
   blended "Connected ✓".
5. **Permissions are enforced server-side.** UI only hides controls; the
   API is the real gate.
6. **Motion:** open 250ms / close 150ms, stagger ≤40ms, total ≤300ms, only
   transform/opacity, respect `prefers-reduced-motion`, decorative motion
   (e.g. the particle field) never reads real data.

## STEP 0 — SAFE COMMIT OF EXISTING WORK (do this first, carefully)

`git status` currently shows ~170 modified/untracked files on
`consumer-saas`. Most of it is 18 already-finished, browser-verified page
rebuilds described in `docs/postriff-app-update-plan.md` (typecheck 0
errors, lint 0 errors, `next build` passes all 50 routes as of the last
check).

- Do **NOT** run `git add -A` or `git add .` — other sessions may have
  their own uncommitted edits interleaved in shared files (this has
  happened before: `hosted_app.py`, `client.ts`, `types.ts`, `rls.sql`,
  `nav-config.ts`, `members-view.tsx`, `conversation-view.tsx`).
- For each file, run `git diff <file>` first and confirm the diff matches
  what `docs/postriff-app-update-plan.md` §1/§3 describes as "今次已落實"
  before staging it. If a hunk looks unrelated to this plan, leave it
  unstaged and note it instead of guessing.
- Stage explicitly: `git add <file1> <file2> ...` then commit with **no**
  pathspec on the commit command itself. Never run
  `git commit -- <pathspec>`: that form silently re-stages the whole
  working tree from disk and undoes your hand-filtering.
- Group commits logically (e.g. one per page/feature area), not one giant
  commit. Reasonable grouping: onboarding system, particle field +
  welcome clip, app-shell fixes, then one commit per rebuilt page
  (Channels, Overview, Analytics, Calendar, Ideas, Pipeline, Library,
  Queue, Inbox, Roles/Members/Audit, Brand, Memory, Billing, Privacy,
  Models, API & integrations).
- Read `docs/postriff-app-update-plan.md` §1 and §3 fully before staging —
  it has the authoritative list of exactly what's finished per page.

## STEP 1 — READ FIRST

Read these before writing any code:

- `docs/postriff-app-update-plan.md` (main plan; §2 has the 7 design
  principles above in full; §8 lists 13 open decisions; §10 lists shared
  files multiple pages need touched)
- `docs/postriff-app-update-plan/pages/*.md` (per-page spec, if you need
  detail on a specific page)
- `docs/postriff-motion-system.md`, `docs/postriff-post-preview-templates.md`,
  `docs/postriff-preference-learning.md`,
  `docs/postriff-worldwide-languages-plan.md` for the other in-flight
  subsystems referenced below.

## STEP 2 — WORK THE BACKLOG IN THIS ORDER

### A) App Update Plan — Phase 0 (do this before touching more pages further)

From `docs/postriff-app-update-plan.md` §7 Phase 0:

- Create one job-state source of truth: `web/src/lib/jobs.ts`, merging the
  three currently-separate copies in `features/overview/queue-status.ts`,
  `features/queue/job-state.ts`, `features/pipeline/job-state.ts`.
- Create one attention source of truth: `web/src/lib/attention.ts`,
  lifting the existing `deriveAttention` out of
  `web/src/features/overview/attention.ts` (Home + sidebar badge share
  it).
- Define one error-code contract: `AlphaError(code=)` on the backend
  paired with `ApiError.code` on the frontend.

### B) App Update Plan — §10 shared-file follow-ups

`docs/postriff-app-update-plan.md` §10 is a table of ~50 concrete,
file-scoped changes that implementer agents already identified but didn't
apply because other sessions were touching those shared files. Work
through that table top to bottom. Each row names the exact file, the
reason, and which page's spec it came from. Typical types of change:

- Add missing fields to `web/src/lib/api/types.ts` that the API already
  sends (so pages can drop local narrow-type casts).
- De-duplicate small helpers (`retractionImpact`, `useSignInAgain`,
  channel badge state) into one shared lib location.
- `nav-config.ts` fixes: duplicate "h h" shortcut for Home/Channels, Ideas
  icon reuse, Inbox/Roles visible to more roles than currently gated.
- Register the remaining onboarding tour anchors/tips in
  `web/src/features/onboarding/tours.ts` for pages that already carry
  `data-tour` ids but no registered steps yet.
- A handful of backend-only rows are marked "(backend, for the founder or
  backend session)" — implement those too, but if a row changes
  externally-visible behavior in a way that isn't purely a bugfix, flag it
  instead of guessing (see "ASK FIRST" list below).

### C) App Update Plan — Phase 2 tail (`docs/postriff-app-update-plan.md` §7 Phase 2)

- Shared `JobDetailSheet`, `ReviewApproveButton`, `JobCancelHold`
  components (Queue/Pipeline currently have near-duplicate versions).
- Settings section reorg (§6 of the plan): collapse Workspace+Account into
  `/app/settings/[section]` with Personal/Workspace/Developer rails, with
  redirects from old URLs. This touches nav-config.ts and routing
  broadly — do this only after Step 0's commits land, and grep for any
  other session's uncommitted edits to `nav-config.ts` /
  `app-sidebar.tsx` first.
- Mobile tab bar, notification bell, shortcuts dialog.
- Auth flow: `/auth/verify` (2FA second step split out), `/auth/reset`,
  permission-aware post-invite redirect.
- Personal access token migration + security review (§6.2 has the full
  spec: read/draft-only scope, mandatory expiry, one-time reveal, step-up
  to create/reveal, scope intersected with creator's live permissions on
  every request).

### D) Worldwide languages — known bug fix (non-blocking but worth fixing)

`LanguagePicker` / `ChannelLanguageChip`
(`web/src/features/.../post-preview` and calendar/composer areas — grep
for the component names): adding a 3rd+ language to a channel chip fails
silently (popover state gets confused — search still filters, but neither
click nor Enter fires `onPick`). The first two languages per channel work
fine; reproduce and fix the popover state bug.

### E) PostRiff agent chat — pick up deferred items if still unclaimed

Check current git log / other sessions' state before starting (these were
deferred as of 2026-09-16 and another session may have since picked them
up):

- Agentic research sources beyond agent-reach / URL fetch
- Onboarding chat, memory proposals surfacing in the agent conversation
- Reasoning-effort mapping to the underlying CLIs

(Desktop companion transport — pairing/claim/device events/memory sync —
is a larger, separate effort; only start it if explicitly asked.)

### F) Preference learning — pre-deploy checklist

- Apply migration 010 before this subsystem goes to production (it has
  **not** been applied yet as of the last check).
- No browser verification of the Memory/conversation/Home learning UI has
  been done yet against a live-Threads harness — do that pass before
  considering it deploy-ready.

## STEP 3 — ASK JAMES BEFORE DOING (do not do these unilaterally)

- Running migration `013_locale_tags.sql` against the **production**
  database (worldwide languages). It's a one-way rewrite of live customer
  data. Confirm with James first.
- Running migrations 009/011 against production, or changing Supabase
  Auth dashboard settings (enabling TOTP/WebAuthn MFA factors) — these
  need James in the Supabase dashboard, not something you can do from the
  CLI; just confirm they're still outstanding and remind him.
- Any of the 13 items in `docs/postriff-app-update-plan.md` §8 ("要你決定
  嘅事") — these are explicitly founder decisions (e.g. how "published"
  job status is counted, whether API keys can ever publish directly, when
  to do the Settings URL reorg, plan-limit enforcement). Implement the
  parts that don't depend on the decision; leave the decision-gated part
  as a clearly flagged TODO with the two options spelled out, don't guess
  which way James wants it.
- Anything that would change externally-visible product behavior beyond a
  straightforward bugfix (e.g. loosening a permission gate, changing what
  "staleness" invalidates) — flag first.

## STEP 4 — VERIFICATION

For anything touching `web/`, before calling it done:

- `npx tsc --noEmit` (0 errors) and `npx oxlint src` (0 errors) from
  `web/`.
- `next build` in an isolated distDir if the normal dev server (port
  3100) is in use by another session — don't fight over that port, don't
  kill another session's dev server.
- Browser-verify interactive changes yourself (your own tab/headless
  instance, not the shared :3100 preview) — screenshot or console-check
  before reporting a page "done".

For backend (`src/postriff_phase2`, `src/postriff_alpha`): run the
relevant pytest suite under `tests/phase2` / `tests/` before committing.

## REPORT BACK

What you committed (commit hashes + one-line summary each), what you
completed from the backlog, what you deliberately skipped and why, and
the exact list of items now waiting on a decision from James.
