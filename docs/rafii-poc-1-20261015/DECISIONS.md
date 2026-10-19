# Rafii POC-1 — decisions

## D-1 (AP-2): integration owner for the review data contract — 2026-10-15
James delegated this decision ("你幫我決定啦"). Decided by Claude.

**Decision.** PR #201 is the mainline for:
- the review data/snapshot contract (`coworker/review.py`);
- the 24h window rule (`metric_schedule.WINDOW_TOLERANCE`);
- the `analytics.read` capability projection.

The parts of PR #126 and PR #142 that #201 already carries are superseded by #201. Their other parts are **not** superseded. Each becomes a follow-up delta, rebased onto #201 after #201 lands:
- **PR #126:** Saved Views, classifications, the review UI components, Trends provenance, reuse candidates and personalization status.
- **PR #142:** feature enrollment, readiness, comment re-sync and Instagram audience.

**Why**
- #201 is built on today's `consumer-saas` (`5f93f375`). #126 is 532 commits behind and #142 is 505 behind.
- #201 has fresh remote evidence on that base: JCB runs `vp5kcw6596` and `n0cd7hj8n5`, plus green GitHub CI.
- #201 is the smallest change that gives each contract a single owner.
- Rebasing the two older PRs first would mean resolving months of drift before any evidence exists.

**Consequences**
- Never merge #126 or #142 as they are while #201 is open. They define the same module and window rule, so merging them would create two implementations.
- #126 and #142 are left open and untouched; whether to close them is James's call. Nothing was commented, closed or rebased.
- Merging #201 is still a separate decision. It needs a review, and AP-6, the optional Codex review, remains open.
