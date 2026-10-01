# RAFII Product Growth v2 — decisions log

Program `RAFII-PRODUCT-GROWTH-v2`. Phases G0–G4 (not Founder P0/P1/P2). Newest last. Each entry: date, decision, reason, evidence.

## 2026-10-01 · G0.1 integration map

**D-001 · Integration base is the production SHA.**
Branch `claude/rafii-product-growth-v2` starts at `dcb5bcdcd76577835a6944f50310e25f16be9de8` (PR #84 head, branch `fix/rafii-call-lifecycle-20260930`).
Reason: production alias `postriff-phase2-private.vercel.app` → `dpl_HSmKDFfjkd8UCaoo2QfgerZUVwLL` (READY, source `cli`) serves that SHA, re-read 2026-10-01 ~17:00Z. `origin/consumer-saas` (`1acd88a8`) is 8 commits behind it, and the canonical local checkout (`d91660b7`) is older still. Basing on either would drop the voice/phone fixes.
Worktree: `/Users/ouxianxing/Documents/James-Au-Studio-product-growth`.

**D-002 · Pricing v2 is reused by merge, unchanged.**
`feat/rafii-pricing-credits-v2` @ `b862cf1f` (11 commits, local only, never pushed) merged cleanly as `8726adbd`. Its worktree (`~/.codex/worktrees/rafii-pricing-credits-v2`) holds staged, uncommitted Free-preview work last modified 2026-09-29 21:07 EDT; that worktree is not modified by this program. Whether that staged work is ported is decided separately (D-008).

**D-003 · Inbox v1 is reused by merge.**
`codex/rafii-inbox-v1-20260928` @ `cb4d5f6a` (6 commits, local only) merged as `575caaf9`. Four conflicts were resolved by keeping both sides:
- `hosted_app.py` / `scripts/postriff_dev_hosted.py`: production's Growth wiring and `pricing_from_environment` kwargs stay; Inbox switches (`RAFII_INBOX_SYNC_ENABLED`, `RAFII_INBOX_REPLY_SEND_ENABLED`, `RAFII_ENGAGEMENT_COPILOT_ENABLED`) and `audience=` on the worker are added.
- `oauth._capabilities`: production's positional `access_token` (used by `write_qualified` and the Business Profile destination call) stays sixth; Inbox's `existing` evidence becomes a keyword argument. `tests/test_inbox_oauth_capabilities.py` passes `existing=` by name.
- `inbox-view.tsx`: `GrowthEntry` stays above the new sync status bar.
Migration `047_inbox_operational_sync.sql` SHA-256 `bcb9be5b…a369553` matches the Inbox receipt.

**D-004 · Founder work is an adjacent, active owner.**
PR #86 (`claude/founder-admin-v2`, draft, based on the production SHA) was pushed at 2026-10-01 12:51:58 EDT and its worktree has ~80 uncommitted files. It is not merged here and its worktree is not touched. Shared metric definitions are agreed by message with its owner and recorded below; this program does not edit Founder contracts.

**D-005 · Migration numbers.**
Occupied or in flight: 047 (Inbox), 048 + 050 (Pricing v2), 049 + 051–060 + 062–068 (Founder; 061 unused, treated as Founder's). This program reserves **080–089** and records it in `docs/postriff-migration-numbering.md`. Hashes at reservation time: 048 `a36357de…792ba0`, 050 `f9aad0a0…b1e7d`.

**D-006 · Heavy work runs on Vercel preview / GitHub CI.**
At 12:53 EDT the Mac showed swap 94 %, load 21 on 12 cores and 7 `next-server` processes, above every local-resource limit. Local work is limited to focused Python unit tests and focused disposable-PostgreSQL groups; full builds, browser suites and whole-suite gates run in the PR's `Rafii local release gates` workflow and on Vercel previews.

**D-007 · Release authority.**
Pricing v2's handoff forbids production deployment, production DDL, live Stripe Prices and production checkout without a new explicit authorization; Inbox v1's receipt requires separate authorization for push/merge/release, production migration and live replies. The current request asks to deploy "within the applicable release authority", which the PRD (§2.3) says does not override a prior explicit prohibition. Therefore: push, PR and protected Preview are in scope; a production deploy containing Pricing v2 or Inbox v1 code, production migrations 047–050/080+, live Stripe, and live provider sends each need James's specific superseding permission, requested once with the exact action.
