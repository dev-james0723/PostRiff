# Hosted deployment preparation

**State: the hosted foundation and full synthetic lifecycle are validated on Production with a registered one-minute cron.** The social adapter remains fail-closed and submitted no live post. Phase 0 remains incomplete at 0/5 full external interviews, and customer validation remains false.

The lifecycle upgrade is also deployed and validated. Protected Preview `dpl_CFRFBACsLDGmfFcmTiqRvN83HKX7` is Ready at `https://postriff-phase2-private-qednj2wbi-jamesau0723-6572s-projects.vercel.app`. Additive migration 002 created forced-RLS account tombstone and session-revocation tables. The expanded two-user exercise passed refresh, export, logout revocation, account deletion and trial replay protection, then removed both users and all synthetic rows. Evidence: [hosted lifecycle validation](evidence/hosted-lifecycle-validation.jsonl).

Deployment attempt `dpl_BXPa5ddTYxVNmsmgx7AbnC4uA2NA` failed before readiness because local `.phase3-build-venv` and desktop artifacts entered the Python bundle. The corrected source and function exclusions also block `vendor`; the replacement upload was 22.4 kB and the Ready Python function is 19.61 MB.

## Executed Preview target

- Vercel: `jamesau0723-6572s-projects/postriff-phase2-private`, Preview deployment `dpl_3oFbMAJBfJBP7nfJrijADGonPtdX`, Ready at `https://postriff-phase2-private-i09esnd9x-jamesau0723-6572s-projects.vercel.app`.
- Supabase: `postriff-phase2-private`, project ref `buoyhkbodnhzngaotoel`, East US (`us-east-1`), `ACTIVE_HEALTHY`.
- Schema: 13 `pr_*` tables, all 13 with forced RLS, plus private bucket `postriff-private`.
- Environment: all five values are configured for Preview and Production with the intended Config/Secret visibility. Secret values are absent from source and evidence.
- Synthetic proof: two temporary users received distinct workspaces; cross-workspace and cross-media access returned 403; media upload/read/delete passed; unauthenticated cron returned 401; authenticated worker returned `externalExecution: false`; all temporary rows and both users were removed.

## Prepared architecture

The candidate uses [Vercel Services](https://vercel.com/docs/services) so one deployment can route `/api/*` to the Python WSGI service while serving the Vite application at every other path. The API receives the original request path. This is a current Vercel beta capability and its compute, invocations and transfer remain subject to the selected plan.

- Frontend service: `studio/web/`, Vite alpha build, SPA fallback.
- API service: Python 3.12, `api.index:app`, 60-second maximum function duration.
- Function bundle: local credentials, `.env` files, launchers, private social modules, tests, evidence and unrelated application directories are explicitly excluded.
- Database and identity: a new private Supabase project, with the additive [Phase 2 migration](../../migrations/postriff/001_phase2.sql).
- Runtime database path: [Supabase transaction-mode pooler](https://supabase.com/docs/guides/database/connecting-to-postgres) on port 6543 with `sslmode=require`; psycopg prepared statements are disabled.
- Media: private Supabase Storage. The hosted API fully decodes JPEG/PNG with pinned Pillow, strips metadata and stores an immutable JPEG rendition. The local runtime may continue using ffmpeg.
- Worker: authenticated `/api/cron/worker`, bounded to ten jobs or twenty seconds per invocation. Its social adapter remains fail-closed, so the prepared deployment cannot submit a real post.

## Environment contract

Set these only in the selected Vercel project. Never paste values into source files or deployment receipts.

| Name | Visibility | Source |
| --- | --- | --- |
| `POSTRIFF_SUPABASE_URL` | Public configuration returned by the API | Supabase project URL |
| `POSTRIFF_SUPABASE_PUBLISHABLE_KEY` | Public configuration returned by the API | Supabase publishable key |
| `POSTRIFF_DATABASE_URL` | Server only | Transaction pooler URI, port 6543, TLS required |
| `POSTRIFF_SUPABASE_SECRET_KEY` | Server only | Legacy Supabase `service_role` JWT required by the current Storage Bearer adapter |
| `CRON_SECRET` | Server only | New random value of at least 32 characters |

The checked-in [.env.example](../../.env.example) contains placeholders only. The [preflight checker](../../scripts/check_postriff_hosted_preflight.py) reports names and validation results without printing values.

## Verification commands

```sh
python3 scripts/check_postriff_hosted_preflight.py
python3 -m unittest discover -s tests -p 'test_*.py'
npm --prefix studio/web test
npm --prefix studio/web run build:hosted
vercel dev -L
```

The local preflight reports local environment values as pending because real secrets remain in Keychain/Vercel rather than a workspace file. Production deployment `dpl_3cA573dgFvhXipWn4KxjfZLe6tY4` is Ready, health reports `configured: true`, and five successive one-minute cron invocations returned HTTP 200. To validate a protected local environment file, run:

```sh
python3 scripts/check_postriff_hosted_preflight.py --env-file /protected/path/postriff.env --require-environment
```

The Vite build currently reports one non-blocking performance warning: the main minified JavaScript chunk is about 589 kB before gzip and 163 kB after gzip. It does not prevent deployment preparation, but code splitting should be considered before a wider production launch.

## Remaining production sequence

1. Exercise hosted recovery, session revocation and export with synthetic identities.
2. The owning Vercel team is verified as active Pro. The reviewed candidate cadence is every minute; no plan upgrade is needed.
3. Production credential scope, redeployment and the full synthetic lifecycle exercise are complete; all temporary identities and rows were removed.
4. Qualify and implement live LinkedIn/Instagram OAuth, identity, capabilities, media, submission and reconciliation after separate scope approval.
5. Connect and execute the approved live image provider/model after its exact count and cost are approved.

## Rollback

Disable the cron first, then roll back or disable the Vercel deployment. Revoke the five newly issued environment values. Delete synthetic Storage objects and test identities after checking their exact project. A fresh disposable Supabase project may be removed only after confirming it contains no retained user data. Do not run an automatic destructive down migration, and do not touch either local SQLite database.

## Exact choices still required for production

- Preview and production domains for Auth redirect allowlists.
- Production Auth redirect domains and live-provider accounts/scopes.
- Live provider accounts, scopes and exact test manifests.

## Approved Preview scope

The user approved the hosted foundation and later directed completion of Phase 2. Production deployment `dpl_3cA573dgFvhXipWn4KxjfZLe6tY4` is Ready with five Production-scoped values, a verified one-minute cron and truthful hosted/private-beta labels. No custom domain, new live-provider OAuth consent, social publication, billing or customer-data upload was performed.
