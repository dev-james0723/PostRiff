# Rafii POC-1 — candidate (not production-ready)

Approved scope (James, 2026-10-15): isolated candidate only; one account, one native metric, one 24h cohort;
qualification, a same-snapshot weekly report, and takeaway → existing Growth Loop / draft fixture. No merge, deploy,
migration, production change, OAuth/scope/refresh, install, service, paid provider/LLM, external message or
publication was performed. The commit, push and draft PR followed James's separate AP-1 approval.

## Where
- Worktree: `/Users/ouxianxing/Documents/.agent-worktrees/rafii-poc1-candidate-20261015`
- Branch: `claude/rafii-poc1-candidate-20261015` (committed and pushed as a draft PR on James's AP-1 approval; no merge,
  no deploy, flags off)
- Base: `5f93f37519e13c1ef4ffe2629576156b588875ed` = `origin/consumer-saas` = remote HEAD, re-verified 2026-10-15
- Reviewable diff: the draft PR (12 code, test and script paths). The remotely validated working tree had patch sha256
  `85415a3c…`; the commit holds exactly that tree plus this folder (docs are excluded from JCB uploads).
- Case table: `CASES.md`; per-ID results: `ACCEPTANCE.md` / `acceptance.json`; runs: `runs.json`; open gates: `APPROVAL-PACKAGES.md`

## What changed (minimal increments, no second store/OAuth/approval/scheduler/router/ledger)
| Path | Owner role | Change |
|---|---|---|
| `src/postriff_phase2/operation_eligibility.py` (new) | capability contract (single owner) | `analytics.read` eligibility projected from existing channel, credential scopes, capability row, deletion marker and stored readings; no writes, no provider calls; `platformApproval` stays `unknown` |
| `src/postriff_phase2/coworker/review.py` (new) | data/snapshot contract (single owner) | PR #126 subset: strict cohort qualification, frozen report snapshots in the existing `coworker.review` aggregate, Markdown/CSV/printable-HTML from one payload, current-rights re-check on read/render/export; plus upper window bound, actual age, as-of cutoff, `qualification`, no aggregate below the floor, Trends-lineage fail-closed |
| `src/postriff_phase2/growth/metric_schedule.py` | data contract | PR #142 subset: `WINDOW_TOLERANCE`; late scheduled reads close as `window_missed` without a provider call; observations record the provider read time |
| `src/postriff_phase2/coworker/growth_loop.py` | existing Growth Loop | proposal bound to a saved report takeaway (snapshot id/version/payload digest), bound-evidence re-check before decisions, owner-only `attach_draft` linking an existing versioned draft (no review, approval or job) |
| `src/postriff_phase2/coworker/{http,service,flags}.py`, `hosted.py` | wiring | 3 review routes behind `RAFII_REVIEW_SNAPSHOTS_ENABLED` (default off); report storage hidden from generic workspace state |
| `tests/test_rafii_poc1_review.py`, `tests/phase2/postgres_rafii_poc1.py` (new) | tests | synthetic case table and disposable-PostgreSQL acceptance |
| `scripts/cloud-rafii-poc1-validation.sh` (new), `web/package.json` | validation | remote-only JCB stages (`ci:rafii-poc1:jcb`, `ci:rafii-poc1:pg-all:jcb`) |

## Preserved work (untouched)
Canonical checkout `/Users/ouxianxing/Documents/James-Au-Studio` (branch `consumer-saas` @ `80bc24d2`, ahead 3 / behind 695,
144 dirty/untracked paths incl. `official_social.py`, `wave3_connectors.py`, Xiaohongshu vendor trees, Channels UI
capabilities/state); PR #126/#139/#140/#142/#143/#175/#197/#199/#200 heads; every other worktree. No reset, stash,
rebase or checkout in the canonical tree. The app-made worktree `.claude/worktrees/rafii-poc-1-candidate-c21d92`
holds only an empty local branch `claude/rafii-poc1-candidate-5f93f37` (at base, no changes).

## Rollback
- Runtime: keep `RAFII_REVIEW_SNAPSHOTS_ENABLED` off (default) — review routes and report-bound proposals refuse.
- Not behind that flag: the scheduler window bound (closes late reads instead of storing them as 24h) and the
  `attach_draft` action (link only). Revert those hunks of the PR diff to undo them.
- Data: no migration; raw observations are never rewritten; report snapshots live only in `coworker.review` of
  workspaces where the flag was on.
- Candidate: close the draft PR; removing the remote branch, the worktree or the two local branches
  (`claude/rafii-poc1-candidate-20261015`, `claude/rafii-poc1-candidate-5f93f37`) each needs its own yes.
