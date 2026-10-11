# Disconnect fences and approved native-schedule tracking

This additive release candidate repairs two acceptance gaps found in the public-launch branch. It does not establish Google verification, public upload eligibility, higher approved quota, or real provider acceptance.

## Resulting behavior

- Each YouTube consent completion gets a new authorization generation. Ordinary access-token refresh preserves it. An in-flight upload retains the exact generation it started with.
- After quota admission and before the next provider request, the service checks that the grant is still active and unchanged. A late upload initialization or cache response cannot recreate data purged by disconnect. Preparing an action also checks the exact generation in its insert transaction.
- Journal/cache saves and identity claims acquire workspace locks before credential locks, consistent with disconnect. Short database transactions finish before provider I/O. A held or terminal job cannot regain dispatch authority through a stale worker lease after reconnection.
- An approved reschedule/cancel action is bound to the exact workspace, connection, immutable channel/video, original upload operation, manifest and approval digest. Subsequent approvals identify the preceding approved action; stale reviews and ambiguous chains fail closed.
- The original upload manifest, options and approval digest stay immutable. Completion tracking follows a separately verified bound schedule, or ends the pending job after verified cancellation while retaining the video privately.
- A provider-readback/approval-receipt race performs only reads of the existing Video ID. It allows three bounded reconciliation checks before requiring intervention. Recovery retains the read-only tracking marker and cannot restore the superseded original schedule or open a replacement upload.

The fence cannot recall a request already sent to Google. It rejects subsequent requests when it observes committed revocation or replacement and rejects stale data persistence in the corresponding write transaction.

## Deployment order

1. Review and apply `migrations/postriff/098_youtube_authorization_generation.sql` to the intended staging/production database before deploying these server changes. The migration only adds a non-null consent-generation UUID to the existing encrypted credential table; it changes no provider permissions or application audience.
2. Deploy through the existing reviewed release pipeline. Keep public publishing and Autopilot gates dependent on actual Google and account-owner approval evidence.
3. Verify the schema, normal consent/refresh behavior and disconnect/recovery behavior in the deployed environment. An absent migration makes YouTube dispatch fail closed with `youtube_authorization_schema`.
4. Reconcile ambiguous accepted operations by their existing journal/session/Video ID. A new connection does not authorize an old held worker or a replacement upload.

Rolling server code back does not require deleting the additive column. Do not remove live journals or customer content to roll back.

## Validation boundaries

The candidate adds synthetic API and worker regressions, exact-grant journal contracts, approved-reschedule/cancel/race tests and a cloud-only disposable PostgreSQL fixture using real OAuth/journal/worker transactions with an injected Google transport. The PostgreSQL fixture checks both actual disconnect/save lock orderings, the first identity-claim/cache-insert race, rollback, refresh, consent rotation, reconnect isolation and held-job exclusion.

Cloud validation must be tied to this candidate's exact source; earlier public-launch CI does not cover these edits. The coordinator's release receipt records the actual run, result and source hashes. No fixture result is real Google acceptance, and no migration or production deployment is implied by this document.
