# Rafii POC-1 — open gates and precise approval packages

State: **CANDIDATE ONLY**. Only AP-1 has been executed. Each package is independent; approving one does not
approve another.

## AP-1 Commit and open a draft PR (no merge, no deploy) — APPROVED by James 2026-10-15, executed
- What: commit the 12 changed paths (plus this folder) on `claude/rafii-poc1-candidate-20261015` (base `5f93f375`),
  push the branch, open a **draft** PR against `consumer-saas`.
- External effect: a pushed branch builds a Vercel **preview** automatically (repo behaviour); GitHub CI runs.
- Not included: merge, production deploy, flag enablement.
- Rollback: close the PR and delete the remote branch (deletion itself needs its own yes).

## AP-2 Integration ownership of PR #126 and PR #142
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

## AP-4 POC-2: one native read-only check on a real, already-authorized account (separate approval)
- Needs, item by item: which workspace / Instagram or Threads account / environment; confirmation that a valid grant
  with `*_manage_insights` already exists (no new OAuth, no scope expansion, no refresh unless named); read scopes;
  at most 10 owned posts and 3 controlled reads; retention of the payload; AI processing **off**; cost cap (proposed
  USD 5); who checks ordinary-user (non-developer) behaviour.
- Proves only: the platform returns comparable native fields and ages for that account. Not publishing, not growth.

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
