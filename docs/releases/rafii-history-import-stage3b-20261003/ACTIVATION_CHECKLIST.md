# Rafii Stage 3B History Import activation checklist

This is a separate, unexecuted activation procedure. This release ships with `POSTRIFF_HISTORY_IMPORT=0`. Do not turn it on as part of deployment, change Stage 3A flags, run a production backfill, or apply a migration from this checklist without a separately authorized operation.

## Before requesting activation

- [ ] Verify the deployed commit and production project `postriff-phase2-private`. Record existing History Import and Stage 3A configuration. Keep History Import `0` until approval covers the target, accounts, data access and provider request allowance.
- [ ] Confirm Stage 3A acceptance, `POSTRIFF_METRIC_READS=1`, healthy authenticated cron/metric collection, and existing 032/035 tables, constraints, RLS and purge markers using an authorized read-only check. Missing schema or Stage 3A changes require their own reviewed operation. This release does not migrate production.
- [ ] Verify production Threads/Instagram provider eligibility, approved analytics scopes and credential expiry on the selected account. Analytics must be **Direct**, with actual grant evidence. Assisted, Bridge, Unsupported and disconnected/revoked accounts cannot import. UI fixtures do not prove live capability.
- [ ] Have a language reviewer check consent/error copy for intended customers: en/en-GB, zh-Hant (HK/TW), zh-Hans, ja, ko, fr, de, es and pt-BR. All keys and bounds are tested; native-language review remains an activation check.
- [ ] Review retention/support language. Rafii reads the account's own historical posts, keeps IDs/dates/media types/HTTPS links/caption length, and collects available current analytics separately. Neither caption text nor hashes are retained. These readings do not reconstruct 1-hour/24-hour metrics.
- [ ] Confirm the privacy distinction from the existing Writing DNA sample-import flow: its separately retained samples are not this metadata-only import. This consent must not opt a customer into retaining writing samples.
- [ ] Confirm canary limits and monitoring ownership: **90 days before request, 300 processed posts, 12 pages, 25 entries/page**, 3 pages/tick, 2 runs/20 seconds/tick, 5 consecutive attempts and 5 interactive requests/workspace/actor/hour. Do not put captions, tokens, cursors or private URLs in receipts/logs.
- [ ] Establish `historyImportsFailed24h`, `historyPurgesPending`, `metricReadsDead24h` and `metricReadsOverdue` baselines and a rollback owner. Verify the purge sweeper runs with growth flags OFF; a purge owed more than 10 minutes appears in operational signals.

## Approved canary

- [ ] Obtain explicit activation authorization for the production flag and selected live accounts. Only then set `POSTRIFF_HISTORY_IMPORT=1` on the verified project and deploy/restart with the approved configuration. This document does not execute that step.
- [ ] Verify endpoint availability and unchanged Stage 3A settings. Opening review and reading status must cause **zero import POSTs** and no provider listing.
- [ ] Have the owner/admin review bounds, metadata/analytics access and purge policy, explicitly check consent, and submit once. Verify 202, one active run and one `history_import.requested` audit with `history-import.v1`. Viewers can read status; API tokens cannot request; cross-workspace access is denied.
- [ ] Verify opaque pagination, atomic progress, no out-of-window posts or overshoot, and partial/failed coverage for malformed next pages against the authorized provider response. Do not request extra imports solely to generate evidence.
- [ ] Observe metadata status and the separate backfill queue. Missing metrics stay unavailable. Verify transient 429/5xx through an approved fault/test path: retries preserve committed cursor/backoff and never automatically repeat a customer's POST.
- [ ] Through an approved test account or isolated rehearsal, verify permission/Direct-analytics changes fence requests/writes. An uncertain POST response reconciles with GET before another confirmed request is offered.
- [ ] With explicit disconnect authorization for a disposable canary account, verify the committed purge marker fences in-flight import/metric writes. Remove imported metadata, job-less observations and readings, cancel active runs, and preserve Rafii-published job observations/readings. Failed removal must retain its marker, block reconnect/import and retry until successful.
- [ ] Review monitor deltas and provider effects before widening activation. Record missing live evidence; local fixtures are not live acceptance.

## Rollback and recovery

- [ ] Set **only** `POSTRIFF_HISTORY_IMPORT=0`, deploy the verified rollback configuration, and confirm GET returns `404 feature_disabled` and the Channels entry disappears. Preserve accepted Stage 3A settings.
- [ ] OFF stops new requests/import ticks; it does not purge retained history or cancel every queued run. Keep the purge sweeper active. Disconnection purges must continue; pending imports remain dormant until an explicitly approved resume/cancellation.
- [ ] Reconcile uncertain submissions before retrying. Use existing disconnect/account-deletion operations for removal; do not manually delete production rows or discard a failed purge marker.

Activation status: **NOT RUN**. Live provider acceptance, native-language review and production data/schema preflight remain activation gates.
