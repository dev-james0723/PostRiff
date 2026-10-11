# rafii.io production domain migration (2026-10-08)

Canonical origin `https://rafii.io`; `https://www.rafii.io` → apex. Former origin `https://postriff-phase2-private.vercel.app`
stays served (callbacks, webhooks, Bluesky client metadata, existing sessions). Vercel project `postriff-phase2-private`
(`prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, team `team_PgXY5VdAYKcsv0RLoDPHscNq`). Production Supabase `buoyhkbodnhzngaotoel`
(confirmed from the production sign-in bundle); staging Supabase `oxacvkhpfgytkepxcaqh` is separate and unchanged.
Values of secrets are never recorded here; env vars are named only.

Read-only impact map reused from the OpenUI release lane: `docs/design/openui-production-2026-10-08/evidence/a/rafii-io-origin-switch.md`
on branch `claude/rafii-openui-production-20261008` (commit `b1349ffc`).

## Before-state (2026-10-08 ~17:55 UTC)

| Item | Value |
|---|---|
| Production deployment | `dpl_23gCJrH5BWZt5gQSV4iqNt2sV5Vt`, `consumer-saas@3da806f0` (PR #133), READY |
| Previous rollback candidates | `dpl_FftzybN56AvCf93cx7eEYjtBjTzw` (07b3295e), `dpl_9Jiq5wtAzg7iwJHC7DqW5kbJw8en` (91f6572c) |
| Project domains | `postriff-phase2-private.vercel.app` (prod); `postriff-phase2-private-staging.vercel.app` (gitBranch `staging`); `rafii.io` (added 17:34 UTC by the OpenUI session at James's request); `www.rafii.io` → 308 `rafii.io` |
| Deployment protection | `ssoProtection = all_except_custom_domains` (unchanged; the `.vercel.app` production alias is already publicly served, so attaching rafii.io adds no new unauthenticated surface) |
| DNS (Spaceship, NS `launch1/2.spaceship.net`) | apex A `216.150.1.1`, `216.150.16.1`; `www` CNAME `2540cc411daf2949.vercel-dns-016.com.`; no MX/TXT existed to preserve |
| TLS | `www.rafii.io` issued 2026-10-08 16:51 UTC (exp 2027-01-06); apex pending at 17:52 UTC |
| Prod env (names, origin-relevant) | `NEXT_PUBLIC_APP_URL`, `POSTRIFF_PUBLIC_BASE_URL` (both = old origin per og:url / Bluesky metadata), `RAFII_CONTROL_ORIGINS`, `RAFII_PHONE_PUBLIC_BASE_URL`, `NEXT_PUBLIC_PASSKEY_SIGN_IN`, `POSTRIFF_VAPID_SUBJECT` |
| App access control (old host, no cookies) | `/` 200, `/api/health` 200, `/api/me` 401, `/api/workspaces` 401, `/api/founder` 401, `/founder` 307 → sign-in |

## Code changes (this branch)

1. `POSTRIFF_OAUTH_<ID>_CALLBACK_ORIGIN` (optional, trusted config, fixed HTTPS origin only): a provider whose console
   lists only the earlier callback keeps using it after `POSTRIFF_PUBLIC_BASE_URL` moves. The public callback route already
   forwards `state/code` to `{POSTRIFF_PUBLIC_BASE_URL}/channels/connect` and never trusts Host/X-Forwarded-Host, and the
   token exchange uses the `redirect_uri` stored on the transaction, so exact redirect_uri agreement holds.
2. `POSTRIFF_BLUESKY_CLIENT_ORIGIN` (optional): pins Bluesky `client_id`, metadata `redirect_uris`, `jwks_uri` and the PAR /
   exchange redirect to one origin, so existing grants keep refreshing with the client they were issued to.
3. `NEXT_PUBLIC_PASSKEY_RP_ID` (optional): passkey sign-in, registration and phone passkey proof are offered only on hosts
   inside the Supabase passkey RP ID; elsewhere users see Google/email. Unset = previous behaviour.
4. `RAFII_LEGACY_HOSTS` + `RAFII_LEGACY_HOST_REDIRECT=off|temporary|permanent`: GET/HEAD public pages on a listed legacy
   host redirect (307/308) to `NEXT_PUBLIC_APP_URL`. Never redirected: `/api/*` (not in the proxy), `/app`, `/founder`,
   `/auth`, `/channels`, `/connectors`, `/invite`, `/sign-in`, `/sign-up`, `/sw.js`, manifest. Default off.
5. `siteConfig.url` fallback → `https://rafii.io`; preview validator accepts rafii.io as production.

Tests: `tests/test_rafii_origin_migration.py`, `web/tests/legacy-host.test.mjs` (run in cloud CI `consumer-ready.yml`).

## Ordered cutover

| # | Step | Owner | Reversible by |
|---|---|---|---|
| 0 | DNS live, apex + www TLS valid, www → apex 308 | done / Vercel | — |
| 1 | Supabase (prod `buoyhkbodnhzngaotoel`) → Auth → URL Configuration → Redirect URLs: **add** `https://rafii.io/**`; keep existing entries; Site URL unchanged for now | James (dashboard) | remove entry |
| 2 | Provider consoles: add (keep old) `https://rafii.io/api/oauth/{linkedin,instagram,facebook,x,youtube,tiktok,discord}/callback` for providers with prod credentials | James (consoles) | remove entry |
| 3 | Merge this PR (production deploy of code; behaviour unchanged until env is set) | PR + checks | revert PR |
| 4 | Prod env (Production scope only): `NEXT_PUBLIC_APP_URL=https://rafii.io`, `POSTRIFF_PUBLIC_BASE_URL=https://rafii.io`, `POSTRIFF_BLUESKY_CLIENT_ORIGIN=https://postriff-phase2-private.vercel.app`, `RAFII_CONTROL_ORIGINS` += `,https://rafii.io`, `NEXT_PUBLIC_PASSKEY_RP_ID=<current Supabase passkey RP ID>`, `POSTRIFF_OAUTH_<ID>_CALLBACK_ORIGIN=https://postriff-phase2-private.vercel.app` for any provider not yet updated in step 2; then one production redeploy (coordinated with the OpenUI release lane) | agent, after ack | restore previous values + redeploy, or promote previous deployment |
| 5 | Verify on rafii.io (matrix in the receipt) | agent + James for consent flows | — |
| 6 | Supabase Site URL → `https://rafii.io`; check email templates for `{{ .SiteURL }}` / `{{ .ConfirmationURL }}` | James | revert field |
| 7 | `RAFII_LEGACY_HOSTS=postriff-phase2-private.vercel.app`, `RAFII_LEGACY_HOST_REDIRECT=temporary` → validate → `permanent` | agent | set `off` + redeploy |
| 8 | Later, separately: passkey RP ID → `rafii.io` (invalidates existing sign-in passkeys; announce; WebAuthn-only MFA users add TOTP first), `RAFII_PHONE_PUBLIC_BASE_URL` with Dial console `wsUrl`, VAPID subject | James + agent | per item |

`RAFII_PHONE_PUBLIC_BASE_URL`, preview/staging variables, `POSTRIFF_STAGING_PUBLIC_BASE_URL` and the staging domain are
**not** changed. Stripe and Resend are not configured in production, so there are no billing/email webhooks to move.

## Rollback

- Code: revert the merge commit on `consumer-saas` (new behaviour is env-gated, so reverting env alone is usually enough).
- Env: restore `NEXT_PUBLIC_APP_URL` / `POSTRIFF_PUBLIC_BASE_URL` to the old origin, remove the added variables, redeploy;
  or instantly promote `dpl_23gCJrH5BWZt5gQSV4iqNt2sV5Vt` (pre-migration build, old env baked in).
- Domain: remove `rafii.io` / `www.rafii.io` from the project (old origin is untouched throughout).
- Supabase / provider consoles: remove only the added rafii.io entries; old entries were never removed.

## Retiring legacy callbacks (conditions, all required)

1. Every provider with production credentials has a verified fresh connect on `https://rafii.io/api/oauth/<id>/callback`
   and its `POSTRIFF_OAUTH_<ID>_CALLBACK_ORIGIN` override is unset.
2. Zero `pr_oauth_transactions` rows with an old-origin `redirect_uri` created in the previous 30 days.
3. Bluesky: either the pin is kept permanently (old host must keep serving `/api/oauth/bluesky/*`), or every Bluesky
   connection has been reconnected under a rafii.io client after an announced window.
4. Runtime logs show no requests to old-host `/api/oauth/*/callback` or `/api/telegram/webhook` for 30 days.
5. `RAFII_PHONE_PUBLIC_BASE_URL` and the Dial console have moved; no Twilio/Dial callbacks hit the old host.
