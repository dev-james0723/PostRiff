# Rollback: Founder Connections attention queue

## What the change does

**Read-only Founder route.** It adds `GET /connections/attention`, plus a Settings panel that calls it.
- Neither writes anything: no tables, no actions, no provider calls, no credential reads.
- The panel re-reads the route every 5 minutes.

**Hourly `connection_health` cron stage.** Before classifying connections, it now overlays YouTube vault facts. These are metadata only: `refresh_supported`, whether a refresh token is present, access expiry, and revoked. As a result:
- **Refreshable YouTube connections** are no longer reported `expired` or `expiring`, and they store no grant deadline.
- **A retained but disabled refresh grant** (Channels card: `client_binding_missing`) is now `blocked`. It is stored as `connection_state = reauthorization_required` because the 060 CHECK has no `client_binding_missing` value. The remedy is the same: the account holder must consent again.
- **Overlay failures** are contained. The overlay runs inside a savepoint, so any error falls back to the previous classification and the hourly refresh still commits.

**Channel query.** It now drops rows the projection would skip anyway (invalid ids, duplicates, configured-but-disconnected) before applying the 5,000 cap. So when the cap is hit, the projection has exactly 5,000 connections, and the reader reports coverage as partial.

**Not involved:** migrations, flags, environment variables and provider configuration.

**CI.** The release also carries #155, which pins the `document-runtime` builder and Lambda images by digest. That change affects CI only.

## Known-good production before this release

| | |
|---|---|
| Deployment | `dpl_4mAFnvUjrhzZVcYNir4TMXxvfHCH` (Vercel project `postriff-phase2-private`, target production, `isRollbackCandidate: true`) |
| Source | `de4e5907281e13638654bc027c7d22006ca715c1` (merge of #138) |
| Observed | 2026-10-10 ~00:00Z: `https://rafii.io/api/health` → `sourceRevision=de4e5907…`; `www.rafii.io` 308 → `rafii.io` |
| Projection baseline | 2026-10-10 00:16:26Z refresh:<br>• facebook ok/read_verified 1<br>• instagram ok/publish_verified 1<br>• instagram ok/read_verified 1<br>• linkedin blocked/reauthorization_required 2<br>• youtube expired/token_expired 1 |

## Rollback steps

1. **Instant rollback (preferred).** Roll production back to `dpl_4mAFnvUjrhzZVcYNir4TMXxvfHCH`, using the Vercel dashboard "Instant Rollback" or `vercel rollback dpl_4mAFnvUjrhzZVcYNir4TMXxvfHCH`.
   - This re-points `rafii.io` and `www.rafii.io` to the previous build. Nothing is rebuilt.
   - Verify that `https://rafii.io/api/health` reports `sourceRevision=de4e5907…`.
   - Note: after an instant rollback, Vercel stops auto-assigning production domains to new Git deployments until a deployment is promoted again.
2. **Durable revert.** Revert the merge commit on `consumer-saas` in a PR. Its Git production deployment then replaces the rolled-back state.
3. **Projection catch-up.** The next hourly `connection_health` run (within one hour) rewrites `public.pr_connection_health` with the old classification.
   - Rows are fully recomputed on every run, so no backfill or cleanup is needed.
   - The YouTube row returns to `expired/token_expired`.

## What rollback does not do

- It does not touch connections, grants, jobs, incidents, follow-ups or the AI ledger. This change never wrote to any of them.
- It does not revoke anything, delete posts or change provider consoles.

## Stop conditions after release

Roll back immediately if any of these happens:
- an authorization bypass on `/connections/attention`, for example a 200 for an anonymous, non-founder or aal1 caller;
- private identifiers or credential material appear in a response;
- the wrong deployment or SHA is serving `rafii.io`;
- new 5xx or runtime errors are attributable to this change;
- the hourly refresh fails (no new `refreshed_at` within about 70 minutes of deploy).
