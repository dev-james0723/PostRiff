# Decisions still needed from James

Decisions below distinguish unresolved questions from approvals already given. Human transcript decisions at 2026-10-09T21:52:56Z (DP-2) and 2026-10-10T01:05:39Z (DP-9, DP-17, DP-11) supersede the earlier open labels. Technical conflicts (X1–X12, the engine defaults, renumbers that touch no applied ledger) are settled by the coordinator and recorded in [00-README.md](00-README.md). An approval is not evidence of execution or acceptance.

Grouped by when the answer is needed.

---

## Needed before the first canary (R1)

### SD-1 — What "Recommended" asks before spending credits

The open half of DP-4. Recommended either asks before **media credits only** (images, video frame reads), or before **all paid work** (also paid writer runs: drafts and rewrites).

- **Recommendation: all paid work.** This matches today's credit quotes. On a workspace with credit billing, every paid writer run, every media-notes read and every image already needs its own confirmed credit limit (`credit_wallet.py` `prepare`: "Confirm this task credit limit before generating"; `credit_requests.py:23`). A valid credit quote for the same request counts as Rafii's spend confirmation, so a credit-billed person is asked once, not twice.
- **If you choose "all paid work":** Recommended asks once before each paid draft or rewrite as well as before images. People on the allowance plan see one more confirmation per paid draft than they would under "media only". Nothing spends credits without a person seeing it.
- **If you choose "media only":** paid drafts run without a prompt under Recommended. That is looser than today's credit-billed behaviour, so on credit-billed workspaces the existing credit quote would still ask anyway, and the two kinds of workspace would behave differently.
- **What changes either way:** only the literal `PRESETS["recommended"]["spend_confirmation"]` (`all` or `media`) and its copy. No schema change. The contracts freeze with `all`.

### R3-1 — Does the 5-minute re-sign-in apply to R3 actions people do without Rafii?

DP-5 says R3 actions (connect or disconnect an account, billing checkout, members, sessions and MFA, API tokens, delete account, auto-publish authority, Library delete) are something Rafii only navigates to, with re-authentication within 5 minutes. The contracts apply the 5-minute rule whenever Rafii hands the person to an R3 page or an R3 approval. The native pages themselves keep today's rule (`permissions.py:57-58`: some of them need a sign-in verified within 10 minutes, some need none).

- **Recommendation: Rafii-originated only, in P0.** Native pages are unchanged until a separate security review.
- **If you want it everywhere:** lane B tightens every R3 native action to a 5-minute sign-in, including ones people reach without Rafii. People will be asked to sign in again more often (for example, removing a member 7 minutes after signing in would now ask again), and the account security help text must change.
- **If Rafii-originated only:** a person who opens the page by themselves gets today's rule. The server-bound single-use handoff record enforces the 5-minute rule for pending Rafii handoffs even if a client drops the marker. Independent native visits keep today's rule.

## Approved, with conditions still to verify

### DP-2 — Paid live runs: US$20 total cap approved

DP-1 (decided) requires a fixed 60-case live corpus with at least 59/60 first-pass valid. It must pass twice on the release SHA: once with the full manifest and once with a narrowed-grant fixture. Until then, permissions cannot be enforced on a GenUI workspace (267f7d90).

- **Approved:** James raised the total cap to US$20 at 2026-10-09T21:52:56Z. This supersedes US$5/US$10 and is not US$20 of new remaining allowance. Reconcile already incurred and unknown costs and open reservations before each paid run; stop before the cap rather than guessing. No approval to increase the cap is implied.
- **Prerequisite (no decision needed):** GA-A fixes the 60 cases and the denominator in the corpus file before the first measurement, and they never change afterwards.
- **Gate remains:** payment authorization does not waive either fixed-corpus pass, ordinary-account acceptance or independent review.

### DP-9 — Permissions and task migrations approved after release gates

- **Approved:** James's 2026-10-10T01:05:39Z decision covers the permissions migration followed by the task migration as separate production release steps, each only after its exact PR passes CI and independent review, merges, and deploys with its features OFF. The permissions file is now proposed as 109 and tasks remain 108; authorization follows their reviewed purpose/content, never a number alone. The occupied YouTube number is excluded.
- **Order:** the two DDL files have no dependency on each other. This docs suite tests numeric order for compatibility, but production retains the approved permissions-then-tasks release order. A runner that automatically applies every lower pending migration is not sufficient: the release owner must prepare an exact-file, pinned-checksum action preview for each approved step and verify its ledger and privileges afterwards.
- **Rollout remains separate:** initial allowlists stay fail-closed. This migration approval does not itself prove or authorize broader enforcement, general availability or additional external effects; follow the recorded canary and acceptance gates.
- **Method:** `scripts/postriff_migrate.py --apply-local` refuses any host that is not loopback, so production uses the reviewed runner method already used for earlier production migrations: a one-off pinned-checksum runner build, executed by the designated release executor, with the connection set to `prepare_threshold=None` for the transaction pooler. Before applying, J reads every environment's `postriff_private.schema_migrations` read-only.
- **Consequence:** after either file is applied anywhere, it can never be edited. Any change becomes a new, later migration (the runner's checksum ledger).
- **Current evidence:** read-only production audit at 2026-10-10T02:20Z found neither migration nor any of their 13 relations. No migration was executed by the takeover audit.

### DP-17 — Visible context approved for the canary behind its own flag

James approved allowlisted on-screen tab state, filter ids and date ranges at 2026-10-10T01:05:39Z. Lane C5 must pass review first. Use the separate `RAFII_CONTEXT_VISIBLE_STATE_ENABLED` flag and initially only workspace `267f7d90`; this does not authorize raw document contents, arbitrary DOM text or broader workspace rollout.

### DP-11 — Real publication test approved in principle only

The same decision approves preparing a real publish/schedule test, but the exact account and post still require a fresh action-specific confirmation at execution time. D Festival public channels remain excluded. No public post is authorized merely by this document.

## Still needed before the first canary (continued)

### LIB-D6a — Library card titles in the page outline

From the Library plan journal (wf_d5b0d850): on /app/library, Library card titles reach the Manager's model through the page outline with no Library gate (`asset-card.tsx`, `use-page-context.ts`). LIB-D1 approves Library metadata egress for the canary first, with an owner toggle and a privacy page update before general release.

- **Recommendation:** mark Library cards `data-private` in the outline on every workspace where LIB-D1 is not yet enabled. On canary workspaces the titles are covered by LIB-D1.
- **If no:** on non-canary workspaces, Library titles keep reaching the model provider without the consent that LIB-D1 requires everywhere else.
- **Related, no decision needed:** the `content_search` snippets are fixed in hotfix HF-1, and the upload `createdAt` change is a separate task.

## Needed before R2 (Library to approved campaign)

### DP-12 — A second per-minute Vercel cron for background steps

P0 needs no new cron. Recovery and expiry run inside the existing `/api/cron/worker`, and Journey C runs entirely inside people's own requests. Journey A needs background polling of publish jobs, which runs on `/api/cron/agent-tasks`. That route ships in the code but is not scheduled.

- **Recommendation:** approve adding `{"path":"/api/cron/agent-tasks","schedule":"* * * * *"}` to `vercel.json` when R2 starts, after checking the plan's cron limits. Vercel Queues is not adopted.
- **If not:** publish results update only when a person opens the task. Journey A cannot show a verified result without someone looking.

### DP-13 — Undo window

- **Recommendation:** 24 hours, and undo stays allowed after the category is revoked, because undo only reverses Rafii's own change. The table allows at most 7 days.
- **If shorter:** fewer conflicts with later edits, but less time for people to notice a mistake.
- **If undo is not allowed after a revoke:** someone who turns Rafii off cannot undo what it just did.

### DP-6 — Consent wording, languages and legal review

- **Recommendation:**
  - write `permission_copy.json` (`agent-permissions/1`) in English and Traditional Chinese (Hong Kong);
  - correct the WelcomeDialog line "Nothing publishes on its own" (`welcome-dialog.tsx:12`), which is untrue while auto-publish automations exist;
  - you decide whether external counsel reviews the wording before general release.
- **Effect:** this blocks the Settings → Rafii Agent page and the onboarding step from general release. It does not block the freeze, the shadow rollout or the canary.

## Conditional

### DP-15 — Migration 100 collision (#131 against the merged #138)

`100_youtube_api_privacy_erasure.sql` is now on `consumer-saas` (#138, merged). Open PR #131 also adds `100_social_cost_reservations.sql` (and `101_x_oauth_provider.sql`). The runner refuses two files with the same number.

- **No decision is needed** if #131's `100` is in no database ledger. Its owner renumbers it (proposed 113, with 101 → 114 if 101 is also unapplied).
- **A decision is needed only** if #131's file is already in some environment's ledger. Renaming it then requires a ledger edit, which is destructive. J reads the ledgers read-only first and brings you that one case if it exists.

## Not blocking these contracts (deferred, recorded so they are not lost)

- **DP-18 Conversation privacy.** Conversations are shared across the workspace (`ideas.py:703-724`). The engine now keeps tasks, approvals and idempotency per person. But answers drawing on personal data (notifications, usage and billing, account) are still visible to co-members in a shared conversation. Recommendation for later: either do not store those answers in shared conversations, or make conversations private to their creator. This is a prerequisite for team delegation.
- **DP-7 First release.** The plan recommends Journey C ("organise with preview and undo") as R1, rather than "A-lite". This affects staffing order only. The contracts support both.
- **DP-22 Owner ceiling API.** The `pr_agent_workspace_policy.ceiling` column exists and `decide()` honours it, but P0 has no API to set it.
