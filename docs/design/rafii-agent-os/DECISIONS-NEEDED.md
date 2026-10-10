# Decisions still needed from James

Only decisions that are still open after James's 2026-10-09 decisions (DP-1, DP-3/DP-4, DP-5, DP-8, DP-10, LIB-D1..D5) and that nobody else can settle. Technical conflicts (X1–X12, the engine defaults, renumbers that touch no applied ledger) are settled by the coordinator and recorded in [00-README.md](00-README.md). None of these blocks freezing CF-1, CF-2 or CF-3.

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
- **If Rafii-originated only:** a person who opens the page by themselves gets today's rule. The contract's handoff marker can only make a page stricter, so dropping it is never looser than today.

### DP-2 — Approve the paid live runs that DP-1 requires

DP-1 (decided) requires a fixed 60-case live corpus with at least 59/60 first-pass valid. It must pass twice on the release SHA: once with the full manifest and once with a narrowed-grant fixture. Until then, permissions cannot be enforced on a GenUI workspace (267f7d90).

- **Recommendation:** approve two runs of 60 cases on the live provider, plus at most one re-run of each after a fix, under a hard budget stop in the existing live runner. The earlier 30-case run was planned inside the US$5 canary cap. Two 60-case runs are about four times that work, so a US$20 hard stop is a reasonable cap. This is an estimate, not a measured cost.
- **Prerequisite (no decision needed):** GA-A fixes the 60 cases and the denominator in the corpus file before the first measurement, and they never change afterwards.
- **If you decline:** enforcement can still start on 332ed6e6, which has no GenUI, using native surfaces. 267f7d90 stays in shadow mode.

### DP-9 — Apply migrations 107 and 108, and set the allowlists

- **Recommendation:** approve two release steps, each taken only after CI is green on the exact head and the dark deploy is done:
  1. Staging, then production: apply 107, verify (forced RLS, no browser access, server privileges as designed), then apply 108 and verify the same way.
  2. Set the fail-closed allowlists for 332ed6e6 first, then 267f7d90: `RAFII_AGENT_PERMISSIONS_WORKSPACES`, then `RAFII_TASK_ENGINE_WORKSPACES`, with the flags in shadow mode.
- **Method:** `scripts/postriff_migrate.py --apply-local` refuses any host that is not loopback, so production uses the reviewed runner method already used for earlier production migrations: a one-off pinned-checksum runner build, executed by the designated release executor, with the connection set to `prepare_threshold=None` for the transaction pooler. Before applying, J reads every environment's `postriff_private.schema_migrations` read-only.
- **Consequence:** after either file is applied anywhere, it can never be edited. Any change becomes migration 109 or later (the runner's checksum ledger).
- **If you wait:** nothing is enforced, and the engine and the permission store stay off. Today's behaviour continues unchanged.

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
