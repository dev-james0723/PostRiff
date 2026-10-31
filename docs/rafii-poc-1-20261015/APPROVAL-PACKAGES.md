# Rafii POC-1 — open gates and precise approval packages

State: **CANDIDATE ONLY**. AP-1 executed; AP-2 decided on James's delegation; AP-4 executed (production env + same-commit redeploy); founder publication pending. Each package is independent; approving one does not
approve another.

## AP-1 Commit and open a draft PR (no merge, no deploy) — APPROVED by James 2026-10-15, executed
- What: commit the 12 changed paths (plus this folder) on `claude/rafii-poc1-candidate-20261015` (base `5f93f375`),
  push the branch, open a **draft** PR against `consumer-saas`.
- External effect: a pushed branch builds a Vercel **preview** automatically (repo behaviour); GitHub CI runs.
- Not included: merge, production deploy, flag enablement.
- Rollback: close the PR and delete the remote branch (deletion itself needs its own yes).

## AP-2 Integration ownership of PR #126 and PR #142 — DECIDED 2026-10-15 (see DECISIONS.md D-1: #201 is mainline)
- Fact: this candidate re-implements a **subset** of PR #126 (`coworker/review.py`, Growth Loop review binding,
  hosted presentation filter) and PR #142 (`metric_schedule` window truth). Both PRs stay OPEN and untouched.
- PR #126 head `bdb9b22e10` has no local worktree (Codex session, last update 2026-10-05). PR #142 head `2a27875108`
  has an idle clean worktree (`.agent-worktrees/rafii-growth-studio-20261009`, last commit 2026-10-08).
- Decision needed: which line becomes the data/snapshot contract owner going forward —
  (a) this candidate supersedes the overlapping parts of #126/#142, or (b) #126/#142 are rebased and this candidate
  becomes a delta on top of them. Until decided, do not merge both: they define the same module and window rule.

## AP-3 Write lease on the canonical checkout
- Fact: the Token Pilot write lease on `/Users/ouxianxing/Documents/James-Au-Studio` is held by the Codex session
  `rafii-discord-authorized-gate-completion` (heartbeat current). It refused edits in the app's worktree under that
  root, so this candidate lives in `/Users/ouxianxing/Documents/.agent-worktrees/rafii-poc1-candidate-20261015`.
  No takeover was attempted; the canonical checkout and its dirty files were not touched.
- Decision needed only if the candidate must live under the canonical root: coordinate with that session's owner.

## AP-4 POC-2: one native read-only check on a real, already-authorized account — APPROVED by James 2026-10-15, executed
**Receipt (2026-10-16 UTC):**
- **Env vars.** `POSTRIFF_METRIC_READS` and `POSTRIFF_METRIC_WORKSPACE_ALLOWLIST` (Production only, type Secret) were updated through `vercel env update`, to `1` and to the founder workspace UUID only.
  Both variables already existed, created about 4 October; their previous secret values could not be read.
- **Redeploy.** The production deployment `dpl_Em37A47dpiKuqxk9BQagi729zgpY` (commit `8df7afea`, PR #199 merge) was redeployed as `dpl_F43BZHmsguya3y8umoPMxMcqTtHK`. It is READY and serves rafii.io and www.rafii.io.
- **Health check.** `/`, `/api/health` and `/api/catalog` all returned 200, and `sourceRevision` is `8df7afea`.
- **Scheduler check.** `metric_reads.tick` logs every minute on the new deployment (status ok, nothing due yet), with no error or fatal logs in the first 10 minutes.
- **Not changed.** No PR #201 code, no migration, no OAuth, scope or token refresh.
- **Rollback.** Redeploy `dpl_Em37A47dpiKuqxk9BQagi729zgpY` for the previous build and env snapshot, or unset both variables and redeploy.
  Because the previous secret values were unknown, this rollback restores the build but not those exact values.

Preflight done read-only (see POC2-PREFLIGHT.md): the only eligible account is the founder's own Instagram (valid grant
with insights scopes, analytics Direct); it has 0 Rafii-verified posts and production has never run a scheduled read,
so the question cannot be answered from stored data.
- Production change (needs yes): on Vercel project `postriff-phase2-private`, target Production only, set
  `POSTRIFF_METRIC_READS=1` and `POSTRIFF_METRIC_WORKSPACE_ALLOWLIST=<founder workspace UUID>` (that one workspace,
  explicit UUID, no wildcard), then **redeploy the current production commit** so the existing per-minute cron mounts
  the existing scheduler. No code from PR #201 is deployed; no migration (035 is already live).
- Founder action (James, not Claude): publish 3 ordinary Instagram posts through Rafii's existing review/approval after
  the redeploy, so each verified post gets its t0/1h/24h/7d schedule.
- Native effect: at most 3 posts x 4 reads = 12 Graph insights GETs with the existing grant; no new OAuth, scope or
  refresh is requested (the token has about 48 days left); comments sync is not part of base. Cost: no provider
  invoice for these reads; USD 0 expected, cap USD 5. AI processing: none.
- Data/retention: native counts stay in `pr_metric_observations` for the founder's own workspace; purge on request.
- Check: after 24–27 h run the read-only qualification query in POC2-PREFLIGHT.md.
- Rollback: remove both env vars and redeploy; pending reads stop at the next eligibility check; stored readings remain
  until a purge is requested.
- Proves only: comparable native 24h values for this one account. Not publishing quality, not growth, not other platforms.

## AP-5 Screen (UI) rendering of the report — Lane D
- Fact: no web source changed. A-D13 parity is proven for the frozen report payload (the JSON the screen would render),
  Markdown, CSV and printable HTML. The on-screen React view and a real PDF print were not built or rendered.
- Decision needed: build the minimal Analytics review view on the frozen contract (and run its browser check
  remotely), or keep the API-only candidate.

## AP-6 Independent Codex review
- Not run: the approval for this task excludes paid provider/LLM calls, and a Codex review is a model call.
- If wanted: one read-only `/codex:review --base 5f93f37519e13c1ef4ffe2629576156b588875ed` on the committed branch.

## Not needed by this candidate
- Migration: none (report snapshots use the existing workspace aggregate `coworker.review`; no schema change).
- New OAuth, scopes, token refresh, store, approval model, scheduler, router or ledger: none added.
- Flag: `RAFII_REVIEW_SNAPSHOTS_ENABLED` defaults off; turning it on anywhere is a separate decision.
