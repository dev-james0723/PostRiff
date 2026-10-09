# Cross-lane integration review — 2026-10-09 UTC

This is a review/coordination note from James's explicitly authorized multisource Trends execution. It does not authorize broader data rights or production changes. Preserve each lane's ownership.

## Important: do not silently filter lifecycle markers

The current draft in the sibling ingestion-recovery worktree adds a test requiring a nonzero `maxMessageSizeBytes` equal to the client frame bound. This conflicts with the upstream Jetstream completeness contract.

Primary source checked 2026-10-09: https://github.com/bluesky-social/jetstream/blob/main/docs/README.md , Section 2, invariant 4, "Eventually-consistent, cooperative completeness". Upstream explicitly says a nonzero maxMessageSizeBytes skips any oversized event, INCLUDING markers, and folding consumers must leave it at its default 0. Losing deletion/account/sync markers can retain data whose lifecycle has changed. This is an IMPORTANT release blocker, not merely a coverage-quality issue.

Please reconcile before merging the P0 patch: do not add a nonzero server-side size filter. Keep bounded local memory/bytes; when a message exceeds an admitted limit, surface a gap/degraded state and preserve lifecycle invalidation/reconciliation. A live-tip reconnect after CursorTooOld must not make retained observations, projections or receipt lineage look continuously verified; preserve an explicit gap/epoch and reconcile or exclude stale state.

The multisource lane will not overwrite the P0 worktree. Its branch is `codex/rafii-multisource-trends-20261008`, worktree `/Users/ouxianxing/Documents/.agent-worktrees/rafii-multisource-trends-20261008`. It owns YouTube/GDELT reference adapters, registry/runtime wiring, honest coverage-backed source filters, and the Mastodon backend-filter bug. No source admission or policy grant is made by that lane.

## Other interface findings

- `service.PLATFORMS` lacks Mastodon even though the current Trends UI offers it.
- The current worker considers every non-Bluesky billable_unit paid; free/quota-only operations need explicit validated economics, not a fabricated price/cap.
- YouTube references must reuse the existing project-level `CapacityController` search bucket, and stay separate from native account analytics/cross-platform measurements.
- Current YouTube search.list docs use a separate Search Queries bucket (one unit per call, default 100/day). Do not reuse the historical 100-general-units assumption.
- The current controlling conversation's production DB read was safety-blocked. Do not route that denied read through another credential/tool. This note requests code coordination only; live-source proof remains unverified for the multisource lane.

Status: review findings and code preparation only. No production fix or new live platform is claimed.
