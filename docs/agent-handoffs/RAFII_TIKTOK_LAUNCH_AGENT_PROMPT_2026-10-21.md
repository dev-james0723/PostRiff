# Agent handoff — Rafii × TikTok public-connect launch

You are the executor for Rafii's TikTok launch. Work through the checklist one blocker at a time with maximum autonomy. Stop for James only at the batched human checkpoints defined below.

## Source of truth

- **Checklist (read fully first, then keep it current):**
  `/Users/ouxianxing/Documents/James-Au-Studio/.claude/worktrees/tiktok-connection-status-8c0399/docs/agent-handoffs/RAFII_TIKTOK_LAUNCH_CHECKLIST_2026-10-21.md`
  Copy it into your own worktree at `docs/agent-handoffs/` as your first commit. From then on, update the copy in your worktree. After every item, record status, UTC time and evidence in section 7.
- **Background:**
  - Memory `project-tiktok-launch-audit.md` and `reference-identify-live-vercel-code.md` in `/Users/ouxianxing/.claude/projects/-Users-ouxianxing-Documents-James-Au-Studio/memory/`.
  - The two handoffs on branch `codex/rafii-tiktok-sandbox-oauth-20261013` under `docs/agent-handoffs/`.
  - Repo `AGENTS.md` and `CLAUDE.md`.
- Memory and old handoffs are evidence, not authority. Re-verify anything you rely on.

## Goal, stated honestly

James wants thousands of customers to connect TikTok from 2026-10-22. TikTok's App Review (several days to two weeks) and posting audit are outside your control. Your job:

1. Make every Rafii-owned item true and proven.
2. Keep TikTok honestly "export only / connect coming soon" until TikTok approves.
3. Get App Review submitted as early as possible.
4. Stage the post-approval rollout so that turning it on is a single, verified, reversible step.

Never claim approval, Direct capability or launch readiness that you have not observed.

## Environment

- **Repo:** `dev-james0723/PostRiff` (local checkout `/Users/ouxianxing/Documents/James-Au-Studio`; the stash is shared, so never use bare `git stash`). Respect Token Pilot write leases: if a write is refused because another session holds the lease, do not bypass it. Work elsewhere or wait.
- **Live lineage:** `rafii.io` runs `7dc95e2e` (`origin/codex/rafii-pinterest-production-prep-20261014`), not `consumer-saas` (`5670ce3c`). Before branching, re-prove the live SHA with the sha1 file-match method in `reference-identify-live-vercel-code`. If it changed, base on the new live SHA.
- **Your worktree:** `git worktree add /Users/ouxianxing/Documents/.agent-worktrees/rafii-tiktok-launch-20261021 -b codex/rafii-tiktok-launch-20261021 <live SHA>`. Do not touch other agents' worktrees. At least one Codex session is editing a YouTube release candidate on `7dc95e2e`.
- **Vercel:** project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, team `team_PgXY5VdAYKcsv0RLoDPHscNq`. Git deploys and automatic previews are **off** by policy; do not change that.
- **Supabase:** prod `buoyhkbodnhzngaotoel` (read-only SELECTs, aggregate or non-identifying columns only); staging `oxacvkhpfgytkepxcaqh` (shared with other sessions; non-destructive).
- **TikTok:** App ID `7689508412459370497`, Sandbox `7689479552734136327`, target user `@jamesaucreates`.
- **Validation is cloud-first.** Run `jcb doctor` first, then `jcb test` / `jcb typecheck` / `jcb lint` / `jcb ci` from your worktree. Never run full Node/Vitest/TypeScript/Next builds or large Python suites locally. Single narrowly targeted Python tests are fine. If JCB fails, report it; there is no local heavy fallback.

## Authority

### Pre-authorized — do these without asking

- Create your worktree and branch, edit code, tests and docs, and commit to your own branch.
- Push **your own branch** and open or update a **draft** PR against the correct base. No merge.
- Run JCB remote validation and an independent Codex review before handing a release candidate back.
- Read-only inspection of Vercel (deployments, aliases, files, env **names**, logs), prod Supabase (SELECT), staging Supabase (SELECT), public TikTok docs and rafii.io pages.
- Read-only inspection of the TikTok developer portal through James's signed-in Chrome: prefer Kynlo browser tools; use Claude in Chrome if Kynlo's browser backend is unavailable. No clicks that change the app, submit, accept terms or sign in.
- `[James: delete this line to withhold]` Edit **Sandbox-only** Login Kit redirect URIs in the TikTok portal to add the exact Preview callback (checklist B3). Never edit Production app settings.
- `[James: delete this line to withhold]` Create **one** bounded hosted Preview for the Sandbox lane with `--skip-domain`, Preview-scoped env only, `RAFII_VIDEO_UPLOADS_ENABLED` on in that Preview only. Restore cost controls afterwards and record the deployment ID and rollback alias.

### Never do these — always route to James

- Merge any PR, push to `consumer-saas`, promote or deploy Production, or reassign `rafii.io`.
- Set or change any Production env var. In particular, never set `POSTRIFF_OAUTH_TIKTOK_REVIEWED`, `_PUBLISH_LIVE_TESTED` or `_PUBLISH_APPROVED` as a workaround.
- Enter credentials, complete 2FA or CAPTCHA, grant OAuth consent, accept TikTok terms, or submit App Review or the audit.
- Publish anything to TikTok or any platform. James approves each exact private test post.
- Apply migrations to production, write or delete production data, or read or print secrets, tokens, cookies or customer data.
- Remove the legal "Draft" banner or finalize legal text without James's approval. Do not present your text as legal advice.

## Operating loop (repeat until no item can move without James or TikTok)

1. Pick the first `[ ]` or `[~]` item, in checklist order, whose dependencies are met and whose owner is A.
2. Re-verify its current state. Something may already be done or may have changed.
3. Do the smallest change that satisfies its acceptance criteria. Match the surrounding code style. Add tests for behaviour changes.
4. Verify with evidence: remote JCB run IDs, SQL counts, HTTP status, screenshots or doc quotes.
5. Mark the item `[x]` with that evidence, or `[!]` with the exact blocker. Commit.
6. If an item needs James, prepare everything around it so his part is one precise action. Add it to the pending human-checkpoint packet and **continue with other independent items**. Do not idle.
7. If the same failure repeats twice unchanged, stop retrying. Diagnose the root cause, or delegate a bounded `/codex:rescue` with the evidence and acceptance test.

### Suggested order

A1 → A2 → B1 → B2 → D1 → D2 → D4 → A3 → C2 → C3 → C5 → C6 → C1 drafts → D3 → D5, then **H1**, then B5–B7, C7 prep, then **H2**, then **H3**. E and F wait for TikTok.

## Human checkpoint protocol

Send James **one** message per checkpoint (H1, H2, H3, H4 as defined in checklist section 4), in Cantonese. Each message contains:

- What is ready, with evidence links.
- The exact clicks or commands he needs, as a numbered list. Each step names its URL or command and its expected result.
- The decisions needed (D1–D4), each with your recommendation first.
- What you will do immediately after he replies.

Never ask for something you can verify yourself. After his reply, re-verify the result (for example the consent produced a credential row) before marking the item done.

## Definition of done

**For 2026-10-22:**

- Phases A–D are `[x]` or `[!]` with an exact external blocker.
- H1 and H2 are completed, and App Review is submitted by James.
- A SHA-pinned release candidate is validated by JCB and reviewed, with a draft PR open, waiting for H3.
- The public pages show no TikTok Direct level.

**Final:** E2 is verified with a non-owner account, and F4 is reached. These depend on TikTok.

## Final report (send when you stop)

Write it in Cantonese for James:

- Checklist status counts.
- Each blocker that remains and its owner (A, J or T).
- Branch, SHA and PR link.
- JCB run IDs and exit codes, plus the Codex review result.
- Deployment IDs created or touched, and the rollback target.
- Every external action taken, and who took it.
- Anything you could not verify.

No secrets in the report.
