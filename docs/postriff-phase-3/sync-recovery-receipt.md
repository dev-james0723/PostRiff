# Phase 3 sync recovery follow-up

User requested continued local desktop/web sync work, explicitly deferring API key setup and real AI testing. No provider, payment, cloud deployment or account action was performed.

## Delivered and verified

- Each submitted edit is frozen in the local pending record before sending. Further typing creates a distinct edit; retries resend the original submission unchanged.
- Server sync receipts identify the operation, variant and resulting revision. Reload/reconnect can recognize a committed edit even when its HTTP response was lost.
- Acknowledgement removes only the acknowledged text. Newer local words survive and retain the acknowledged base revision, so intervening remote edits still cause an explicit conflict.
- Conflict comparison and explicit rebase remain available after a rejected stale save. Rebase creates a fresh operation, never silently overwrites another revision.
- Visible workspace refresh runs while idle as well as during jobs, with online/focus/visibility recovery. Disposed requests cannot update an unmounted panel; polling skips hidden/offline windows and overlapping requests.
- Storage failures now show an instruction to preserve/copy unsent text rather than claiming durable storage succeeded.

## Validation

- Python integrated suite: **135 passed** ([log](evidence/sync-python.log)). Includes persisted acknowledgement, replay after restart and conflict rejection.
- Frontend suite: **75 passed** ([log](evidence/sync-frontend.log)); TypeScript and shared production build passed.
- Rebuilt macOS sidecar/Electron app ([log](evidence/sync-package.log)).
- Packaged acceptance outside development cwd: delayed successful HTTP response with continued typing, committed save with dropped HTTP response followed by page reload, independent edits, offline text, restart, vault persistence, device revocation, no orphan sidecar, desktop/mobile layout, keyboard and zero page errors passed. [Extended harness](../../desktop/tests/sync-acceptance.cjs), [log](evidence/sync-desktop.log), [desktop result](evidence/sync-desktop/desktop-acceptance.json). Synthetic native pairing confirmation was injected by the harness. Mobile screenshot inspected.
- Disposable local PostgreSQL: existing migration/pairing/two-user isolation/revocation checks passed ([log](evidence/sync-postgres.log)); no hosted database was touched.
- [Scoped source diff](evidence/sync-source.patch) and [hash/ZIP audit](evidence/sync-audit.json). Original files preserved in `evidence/sync-before/`. Git history remains unavailable for this installed tree without Git metadata.

## Current local package

[PostRiff.app](../../desktop/artifacts/PostRiff-darwin-arm64/PostRiff.app) now contains these changes. [New ZIP](../../desktop/artifacts/PostRiff-0.3.0-macos-arm64-sync-recovery.zip); earlier ZIPs are preserved.

SHA-256: `a57d8ac9ea0eb2f0c75f343a508aa962cbd783c76333ff0446ab94ff39d8bd8d`.

macOS arm64 local development delivery; no Developer ID/notarization or Windows validation.

## Remaining boundaries

These are shared UI/local protocol improvements, not deployed desktop-to-cloud synchronization. Hosted runtime mounting and signed-in remote device confirmation still need implementation/integration; genuine separate-device hosted acceptance remains pending. Physical sleep/wake was not exercised. Existing receipts from older versions lack the new variant/revision metadata; new submissions receive it.

API key setup and real generation remain deferred by user request. Phase 3 is incomplete; Phase 4 billing/paid beta has not started.
