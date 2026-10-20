# X G16 — production-preserving release candidate

## Release boundary

This is isolated engineering, not public acceptance or permission to deploy. Preserve PR #214 and its qualified `41a7c54aeb2262d3b35062fec939080d34b2274c` source. This branch descends from it and restores already-live integration code so an X release does not remove another platform. No real customer identity, X provider receipt, charge, schema mutation, staging build or production promotion is asserted.

Canonical targets remain Vercel `postriff-phase2-private` and Supabase `buoyhkbodnhzngaotoel`; never substitute the old staging project. Git automatic deployment remains globally disabled. The local optimized browser build uses loopback fixture routing and MUST NOT be deployed.

## Production source preservation

The recovered input manifest of live deployment `dpl_yKAToJbvjRdQRmCS3RLKHTYegqUr` contains 2,217 hash-verified paths. Its historical Git SHA remains unknown; recovered bytes are not invented historical Git provenance.

Compared with PR #214, 61 live paths differed: 15 were intended X-only changes, 34 required preserving live code/configuration, and 12 needed three-way reconciliation. Thirty-three files were restored byte-for-byte. The old live `vercel.json` per-branch autodeployment setting was deliberately NOT restored: `git.deploymentEnabled=false` stays in force. Nine shared files merged without textual conflicts; three files required explicit preservation of both platforms' independent consent and dispatch guards.

`X-PRODUCTION-PRESERVATION.json` records exact inherited-file hashes and reviewed overlaps. Tests enforce those 33 files and the no-autodeploy policy. The resulting comparison is 2,189 unchanged live paths, 28 intentional X/shared/policy differences, zero missing live paths and zero unclassified differences. Restoring live code does not certify that its original features have provider approval. The existing Pinterest private-trial, quota, account binding, visibility and consent restrictions remain intact.

## Pending-OAuth disconnect defect

A real local HTTP/PostgreSQL test reproduced a 500 response when an X customer disconnected while another OAuth callback was pending. The old code wrote `outcome='disconnected'`, which the real OAuth CHECK constraint does not permit. Provider revocation could already have occurred before the database transaction failed.

The corrected X path records the existing valid outcome `denied`, consumes the pending transaction, removes its verifier, expires it, cancels queued work, and retains the existing account/credential-generation fences. Tests prove that the old callback cannot exchange, new interactive consent can reconnect, and old approvals do not resume. This does not weaken or replace the existing outcome constraint.

Both Chromium desktop and WebKit mobile acceptance now exercise pending consent -> disconnect -> rejected stale callback -> visibly disconnected account -> new explicit reconnect, in addition to media approval, per-step receipts, separate post approval, exact media readback, schedule cancellation and tenant denial. All identities and provider responses remain synthetic; the actual Rafii HTTP, SQL, PKCE and application code runs.

## Migrations 131–135 and rollback

Migrations 131–134 are still pending production approval. They are applied only to disposable databases by acceptance. Actual database roles are tested: anon and authenticated cannot read the direct or cost tables; the service role retains its explicit server-side privileges. The synthetic full-schema role setup matches the observed production service-role BYPASSRLS attribute, without granting privileges in production.

Migration 135 is now conservative and bounded. An already-effective validated exact rule is a catalog-only no-op; its constraint OID is preserved. Only the known legacy length rule is upgraded. Missing, unvalidated, NO INHERIT or unexpected rules fail closed. The upgrade is rechecked under an exclusive lock, with a five-second lock timeout and thirty-second statement timeout. Tests cover legacy upgrade, exact no-op, unknown-policy refusal, and client-role isolation. Alternate PostgreSQL expression formatting deliberately requires review rather than guessing equivalence.

Rollback is forward-compatible containment: disable X admission/dispatch and keep journals, approvals and provider receipts intact; restore only an independently qualified compatible application deployment. Do not DROP the new journals, erase cost counters or replay uncertain writes. The cost-controller tests continue to reject old-binary inserts that would bypass the new durable grant counters. Any destructive DB recovery needs separate approval and verified backup/PITR evidence.

## Verification and reviewer scope

Use `scripts/x_direct_acceptance.py` with the pinned requirements, Node and Playwright dependencies. The runner now includes inherited Pinterest regression and an explicit opt-in no-egress local OAuth/SQL lifecycle fixture. It records exact source manifests before/after and stops only its own disposable servers. The new OAuth tests also run directly with `RAFII_X_LOCAL_OAUTH_E2E=1`.

The complete repository's secret scanner is unchanged. Three restored zero-network test constants were reviewed and permitted by exact path+hash only: two synthetic redaction sentinels and the example.com `user:pass` negative URL test. There is no broad file/directory exemption, credential verification or real secret in those fixtures.

Author review and test evidence are not independent external approval. A second reviewer must examine the three manual shared-file merges, OAuth disconnect ordering, migration 135's recognized expressions and the exact release source. Do not approve this PR using the author account as a substitute for independent signoff.

## Remaining human and hosted acceptance

The original X app's current registered callback, API entitlements, transfer pricing, finite provider billing cap, and consenting ordinary non-owner customer still require authenticated nonsecret Console evidence. No current Console login or real customer consent is supplied by this branch. The prior US$0.10 identity-only allowance is not a publishing/media budget.

Before any external effect, bind explicit authorization to the final SHA, canonical schema plan, exact test account/content/media/scheduled time/cleanup actions, current per-endpoint pricing and total allowed spend. A separately approved production-target staged build must verify its immutable Git source and actual deployment artifact before a further alias-promotion approval. The existing live alias and independent working integrations must remain untouched until those gates pass.

Current verdict: **engineering candidate only; PUBLIC PRODUCTION NO-GO until actual provider/customer and hosted release gates pass**. Poll/tagged-user or other unimplemented/unverified operations must remain accurately disabled; a complete public API catalogue is not a claim of universal entitlement.
