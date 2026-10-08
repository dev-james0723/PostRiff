# rafii.io canonical-origin switch: read-only map

Date: 2026-10-08. Worktree: `rafii-openui-a-integration-20261008` (production code 3da806f0 + release contracts). Read-only investigation. No file other than this one was written, and no Vercel, Supabase, GitHub or provider setting was changed. Env var **names** only; no values were printed.

Classification:
- **(a)**: A can change it safely via env, config or code (env changes take effect only on a new production deployment).
- **(b)**: needs James in a third-party console. The exact console, field and value are listed in section 8.
- **(c)**: must stay as it is, or needs no change because it is already origin-agnostic.

## 0. Observed state (live, read-only, 2026-10-08 ~13:45 local)

| Item | Observation | Source |
|---|---|---|
| Vercel project domains | `postriff-phase2-private.vercel.app` (prod, no redirect); `postriff-phase2-private-staging.vercel.app` (gitBranch `staging`); `rafii.io` (verified, no redirect); `www.rafii.io` with **redirect 308 → `rafii.io`** already configured | Vercel API `list_project_domains` for prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L |
| rafii.io DNS | Registrar **Spaceship, Inc.**; current nameservers `launch1.spaceship.net`/`launch2.spaceship.net`; **no A/CNAME** for `rafii.io` or `www.rafii.io` (NXDOMAIN-equivalent) | `vercel domains inspect rafii.io`, `dig`, `whois` |
| Vercel's requested DNS | Either `A rafii.io 76.76.21.21` (recommended) **or** nameservers `ns1.vercel-dns.com`, `ns2.vercel-dns.com` | `vercel domains inspect rafii.io` |
| Prod env names (origin-relevant, present) | `NEXT_PUBLIC_APP_URL`, `POSTRIFF_PUBLIC_BASE_URL`, `RAFII_CONTROL_ORIGINS`, `RAFII_CONTROL_MOUNT`, `RAFII_PHONE_PUBLIC_BASE_URL`, `NEXT_PUBLIC_PASSKEY_SIGN_IN`, `POSTRIFF_BLUESKY_CLIENT_JWK`, `POSTRIFF_TELEGRAM_BOT_TOKEN`, `POSTRIFF_TELEGRAM_WEBHOOK_SECRET`, `POSTRIFF_DISCORD_BOT_TOKEN`, `POSTRIFF_OAUTH_{LINKEDIN,INSTAGRAM,FACEBOOK,X,YOUTUBE,TIKTOK,DISCORD}_CLIENT_{ID,SECRET}`, `POSTRIFF_OAUTH_MASTODON_ENABLED`, `POSTRIFF_VAPID_{PUBLIC_KEY,PRIVATE_KEY,SUBJECT}`, `POSTRIFF_NOTIFICATION_SIGNING_KEY`, `RAFII_NOTIFICATIONS_V2_ENABLED`, `RAFII_WEB_PUSH_ENABLED`, `RAFII_PHONE_*`, `TWILIO_*`, `DIAL_*`, `CRON_SECRET` | `vercel env ls production` (122 names, saved to scratchpad) |
| Prod env names (absent) | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `EMAIL_FROM`, `POSTRIFF_STAGING_PUBLIC_BASE_URL` (prod scope), any `POSTRIFF_OAUTH_{THREADS,PINTEREST,...}_*`, `RAFII_NOTION/GMAIL_CONNECTOR_ENABLED`, `RAFII_SMS_ENABLED`, Sentry vars | same |
| Supabase Auth URL config (recorded) | Site URL `https://postriff-phase2-private.vercel.app`; Redirect URLs `https://postriff-phase2-private.vercel.app/**` and `https://postriff-phase2-private-*-jamesau0723-6572s-projects.vercel.app/**` | `docs/releases/founder-full-activation-20261002/google-provider-configuration.json` (read-only dashboard read, 2026-10-02). **Not re-read today.** A production read was denied by this session's permission classifier. |
| Prod robots | `Sitemap: https://postriff-phase2-private.vercel.app/sitemap.xml` (served by `web/src/app/robots.ts`, not `web/public/robots.txt`) | `curl` |
| Prod og:url | `https://postriff-phase2-private.vercel.app`, so `NEXT_PUBLIC_APP_URL` currently holds the old origin | `curl` of `/` |
| Bluesky client metadata (live) | `client_id=https://postriff-phase2-private.vercel.app/api/oauth/bluesky/client-metadata.json`, redirect `…/api/oauth/bluesky/callback`, jwks `…/api/oauth/bluesky/jwks.json` | `curl` |
| TikTok verification file | `/tiktokZXN6P78dvnOAOs6qgUIUjfBG4ZWRu5iv.txt` returns 200 on the old domain | `curl` |
| `/api/health` | 200 on the old domain | `curl` |

## 1. Map of origin-bearing code and env vars

### 1.1 `NEXT_PUBLIC_APP_URL` (web; inlined at build time, so a change needs a rebuild/redeploy)

| Location | Use | Class |
|---|---|---|
| `web/src/config/site.ts:7` | `siteConfig.url = NEXT_PUBLIC_APP_URL ?? 'https://postriff-phase2-private.vercel.app'` (hardcoded fallback) | (a) set the env at cutover; optionally change the fallback to `https://rafii.io` |
| `web/src/app/layout.tsx:21,33` | `metadataBase`, `openGraph.url` | (a) follows the env |
| `web/src/app/robots.ts:7`, `web/src/app/sitemap.ts:11-13` | sitemap URL and every sitemap entry | (a) follows the env |
| `web/src/components/marketing/json-ld.tsx:11,20`; `web/src/app/(marketing)/privacy/page.tsx:40`; `.../data-deletion/page.tsx:33` | Structured data and legal copy show the origin | (a) follows the env |
| `web/src/lib/workspace/bootstrap.ts:12-35` (`bootstrapOrigin`) + `server-bootstrap.ts:7-8` | Production SSR fetches `${NEXT_PUBLIC_APP_URL}/api/me` and `/api/workspaces` with the user's bearer, `redirect:'error'`. A wrong or unresolvable value only returns `null`, so the client fetches instead. | (a) set to `https://rafii.io` **only after DNS and TLS are live**. Both hosts reach the same deployment, so the old value keeps working meanwhile. |
| `web/src/lib/deployment-env.mjs:13` (called from `web/next.config.ts:2-3`) | Preview-only guard: `NEXT_PUBLIC_APP_URL` must equal `POSTRIFF_STAGING_PUBLIC_BASE_URL`. It returns early when `VERCEL_ENV !== 'preview'`. | (c). Do not touch Preview scope. |
| `scripts/check_social_voice_preflight.py:25-28` | Requires `NEXT_PUBLIC_APP_URL == POSTRIFF_PUBLIC_BASE_URL` | (c). This means the two must change **together**. |
| `scripts/founder_signin_web.py:28`, `scripts/check_social_learning_browser.py:37`, `scripts/consumer_ready_web.py:28`, `.github/workflows/{rafii-browser,library-release}.yml` | Local/CI harness values (localhost) | (c) |

### 1.2 `POSTRIFF_PUBLIC_BASE_URL` (Python; read at cold start, so it needs a redeploy)

This one value drives every social OAuth `redirect_uri`, the post-callback landing origin, the Bluesky `client_id`, the Telegram webhook URL, Stripe return URLs and email/SMS links.

| Location | Use | Class |
|---|---|---|
| `src/postriff_phase2/hosted_app.py:209` | Passes `public_base_url` into `HostedWorkspaceService` (OAuth, productivity, billing, mailer) | (a) |
| `src/postriff_phase2/oauth.py:195-199` (`callback_uri`) | `redirect_uri = {base}/api/oauth/{provider}/callback`. It must be fixed HTTPS with no path. `oauth.py:93` surfaces "register its callback with the provider". | (a), but gated by (b) provider consoles |
| `src/postriff_phase2/oauth.py:209-232` | The redirect is **stored per transaction** (`pr_oauth_transactions.redirect_uri`). The exchange (`oauth.py:~298`) uses the stored value, so in-flight connects survive a switch. `TRANSACTION_TTL=600` (`oauth.py:22`). | (c) |
| `src/postriff_phase2/hosted_app.py:583-611` | Public callback `/api/oauth/{p}/callback`. It **does not exchange**. It 302s to `{POSTRIFF_PUBLIC_BASE_URL}/channels/connect?state&code…` (`oauth.py:272-276`). It never trusts Host/X-Forwarded-Host (`:593`). An old-domain callback therefore lands the user on **whatever origin `POSTRIFF_PUBLIC_BASE_URL` names**. | (c) keep both routes. This behavior is what makes the old callbacks keep working after the switch. |
| `web/src/app/channels/connect/forwarder.tsx:11` then `/app/channels/connect` (`web/src/features/channels/connect-return.tsx:24-65`) | Completes with the **signed-in session on the landing origin** plus the `postriff_workspace` cookie. The `/app/*` gate (`web/src/proxy.ts`) sends unsigned users to sign-in with `next=` preserved. | (c). Cross-origin landing costs one extra sign-in. |
| `src/postriff_phase2/productivity_connectors.py:476-487` | Same pattern for Notion/Gmail (`/connectors/connect`). Flags are absent in prod. | (c) until enabled |
| `src/postriff_phase2/atproto_oauth.py:121-131,140-158,240-241,281,313-317` | **Bluesky `client_id` = `{base}/api/oauth/bluesky/client-metadata.json`**. It is used in PAR, authorize, the private_key_jwt `iss`/`sub` and **refresh** (`_dpop_post` sets `client_id`/`client_assertion`). | **Breaking**. See §3.2. (a) code pin recommended. |
| `src/postriff_phase2/social_connectors.py:144-149,161` (Mastodon), `src/postriff_phase2/wave4c_connectors.py:59` (Pixelfed) | Dynamic per-connect app registration with `redirect_uris={base}/…/callback`, `website=base`. Stored per transaction. | (a). No console; existing tokens are unaffected. |
| `src/postriff_phase2/social_connectors.py:239-262` (Discord) | `redirect_uri` from `callback_uri`; `website` is only in the bot User-Agent | (a) + (b) Discord portal |
| `src/postriff_phase2/social_connectors.py:405-441` (Telegram) | `webhook_url = {base}/api/telegram/webhook`. `ensure_webhook()` calls `setWebhook` automatically when Telegram's URL differs. This is triggered from `connect_instructions()` (`:448-449`), meaning the next Telegram connect after the switch. | (a)/(c). No console. Both routes are served. |
| `src/postriff_phase2/hosted.py:520-527` (`_app_url`), `:541-542`, `:572-573`, `:593` | Stripe checkout `success_url`/`cancel_url` and portal `return_url` | (a). Stripe is **not configured in prod** (no `STRIPE_*` names). |
| `src/postriff_phase2/hosted.py:400,643,716,755,1044`; `src/postriff_phase2/email.py:121-125,189-198,278`; `src/postriff_phase2/hosted_app.py:171-176` | Mailer base and links (billing, new-device, welcome, invitation `/invite/{token}`, pricing, privacy). Each link must share the base's netloc (`email.py:189-192`). | (a). Resend is **not configured in prod** (NullTransport). Invitation tokens are host-agnostic. |
| `src/postriff_phase2/notifications/service.py:37,195`; `notifications/delivery.py:34,143,150,345`; `notifications/email_render.py:72-102,191-212` | Notification deep links, avatar `{base}/raffi/avatar-128.png`, **unsubscribe** `{base}/api/notifications/unsubscribe?token=` (HMAC, host-agnostic) | (a). Already-sent links keep working while the old domain serves. |
| `src/postriff_phase2/notifications/sms.py:143-181` | SMS link plus Twilio `StatusCallback={base}/api/notifications/sms/webhook/{id}`. Signature check: `url.startswith(base)`. | (a). `RAFII_SMS_ENABLED` is absent in prod. Status callbacks in flight across the switch would fail the signature check (cosmetic). |
| `src/rafii_control/founder_activation.py:52` | Readiness check that requires the name to be present | (c) |
| `src/postriff_phase2/deployment.py:24-28` | Preview-only: must equal `POSTRIFF_STAGING_PUBLIC_BASE_URL` | (c). Preview untouched. |
| `scripts/postriff_dev_hosted.py:316,342` | Dev `https://dev.postriff.invalid` | (c) |

### 1.3 Other origin variables and hardcoded strings

| Location | Use | Class |
|---|---|---|
| `RAFII_PHONE_PUBLIC_BASE_URL`: `src/postriff_phase2/phone/config.py:31-32`, `phone/providers/twilio.py:53-56,83-84,133-135,155,165`, `phone/providers/dial.py:55-61,124,218-220`, `phone/http.py:61,81` | Twilio answer/status URLs, Twilio signature URL, Dial media `wss://{base}/api/phone/dial/media`. `readiness()` requires the **Dial console self-hosted `wsUrl` == this value** (`dial.py:124`). | **(c)** keep it on the old domain. Changing it breaks Dial readiness until the Dial console changes, and in-flight call callbacks fail signature checks. Switch later as its own change. |
| `src/rafii_control/auth.py:94-117` (`RAFII_CONTROL_ORIGINS`), `src/rafii_control/http.py:84,106`, `auth.py:165,215` | Embedded Founder Control: the request host must be in the list, **otherwise 404**. Origin/CSRF checks run against the list. Cookie `__Host-rafii-control` (`auth.py:16`, `http.py:110`) is host-only. | (a) **append** `https://rafii.io` and keep the old origin. The founder signs in again on rafii.io. |
| `src/postriff_phase2/agent_runtime_v2/ui_validator.py:41-52` | Parser seam target: `RAFII_WEB_INTERNAL_URL` / `RAFII_GENUI_VALIDATOR_URL` / `https://VERCEL_URL` | (c) deployment-URL based, not domain based |
| `src/postriff_phase2/hosted_identity.py:236-251` | `phone_mfa_challenge/verify(rp, site)`. No callers in this tree (dormant). | (c). If it is ever wired, `rp`/`site` must come from config, not the request Host. |
| `scripts/validate_postriff_hosted_preview.py:26` | `deployment_target="production"` only when the URL is the old domain | (a) also accept `https://rafii.io` |
| `scripts/validate_postriff_hosted_preview.py:45` | Keychain account `postriff-phase2-private` (Vercel project name, not a domain) | (c) |
| `src/postriff_phase2/hosted.py:400`, `hosted_app.py:176` (`postriff.invalid`); `notifications/service.py:37`, `email_render.py:99`, `delivery.py:34`, `src/rafii_control/founder_preview_delivery.py:313`, `web/src/lib/coworker/safe-href.ts:25` (`rafii.invalid`); `web/src/lib/auth/session.tsx:177`; `scripts/agent_runtime_live.py:159` | Inert placeholders and fallbacks | (c) |
| `web/src/config/site.ts:12` `supportEmail: 'support@postriff.app'` | Public support address | (a) once James has a rafii.io mailbox (MX at the registrar). Optional. |
| `web/src/features/workspace/members-view.tsx:475` | Invite link uses `window.location.origin` | (c) host-agnostic |
| `vercel.json:101-105` crons `/api/cron/worker` (relative) | Runs against the production deployment, not a domain | (c) |
| `.github/workflows/*` | No production domain references | (c) |

## 2. Auth

### 2.1 Supabase PKCE / Google / email OTP
- `web/src/components/auth/auth-form.tsx:77-80`: Google `signInWithOAuth({ redirectTo: window.location.origin + '/auth/callback?next=…' })`. Supabase only honors `redirectTo` when it matches **Redirect URLs**. Otherwise it falls back to **Site URL** (old domain), where the PKCE verifier cookie (host-only, set on rafii.io) is missing. So **Google sign-in on rafii.io fails until `https://rafii.io/**` is in the allowlist.**
- `web/src/lib/founder/sign-in.ts:102-113,132`: Founder Google sign-in uses `redirectTo=https://<origin>/founder/sign-in?founder_state=…`. The same allowlist entry covers it.
- `web/src/app/auth/callback/route.ts:6-15`: uses `new URL(request.url).origin`, so it is host-agnostic. (c)
- `auth-form.tsx:96-112`: Email OTP uses `signInWithOtp` + `verifyOtp` (code entry) with **no `emailRedirectTo`**, so it is domain-independent. If the Supabase email template also contains `{{ .ConfirmationURL }}` / `{{ .SiteURL }}`, those links follow the Site URL. James should check the templates (§8).
- The Google provider for app sign-in redirects to Supabase's own `https://<ref>.supabase.co/auth/v1/callback`. **No Google Cloud change is needed for app sign-in.**
- Sessions are host-only cookies (`web/src/lib/supabase/middleware.ts`, no `domain`). Visiting rafii.io starts signed out. **Old-domain sessions are not revoked.** No env change rotates the JWT secret, so nobody is logged out by the switch itself.

**Required Supabase values** (Dashboard → Authentication → URL Configuration):
- Redirect URLs: **add** `https://rafii.io/**`. **Keep** `https://postriff-phase2-private.vercel.app/**` and the preview pattern. `www` is not needed, because Vercel 308s `www` to the apex before any JavaScript runs.
- Site URL: change to `https://rafii.io` **at or after cutover** (step 6). It only affects the fallback and template `{{ .SiteURL }}`. It does not log anyone out.

### 2.2 Passkeys (two separate mechanisms)
1. **Sign-in passkeys** (Supabase experimental passkeys: `web/src/lib/auth/passkeys.ts:21-23,37-40,53-57,63-73`; enabled in prod via `NEXT_PUBLIC_PASSKEY_SIGN_IN`). The RP ID and RP Origins are **server-side** (Dashboard → Authentication → Passkeys). Supabase docs: each origin's hostname "must match or be a subdomain of the Relying Party ID", up to 5 origins, and changing the RP ID "makes every existing passkey unusable". The RP ID is presumably `postriff-phase2-private.vercel.app`, prefilled from the Site URL (not re-read). That host is under `vercel.app`, which is on the Public Suffix List, and it cannot share an RP ID with `rafii.io`. **Passkey sign-in can work on only one of the two hosts at a time.** On rafii.io, sign-in, registration and phone-call proof (`withPasskeyProof`, used by `web/src/features/rafii-phone/verify-call.tsx` and `agent-call-security.tsx`) fail until the RP ID changes. Switching the RP ID to `rafii.io` invalidates **all** existing sign-in passkeys on both hosts. WebAuthn Related-Origin Requests do not help, because Supabase rejects origins outside the RP ID.
2. **MFA WebAuthn factors** (`web/src/lib/auth/mfa.ts:98-101,143-145`). auth-js 2.116.0 (`web/package-lock.json`) defaults `rpId = window.location.hostname` and `rpOrigins = [window.location.origin]` (confirmed in auth-js `src/lib/webauthn.ts`). Each factor is bound to the hostname it was enrolled on. **A factor enrolled on the old host does not work on rafii.io.** A user whose only verified factor is a WebAuthn factor cannot reach AAL2 on rafii.io. Supabase also requires AAL2 to enroll a new factor when verified factors exist. That user is effectively locked out on rafii.io until they act on the old host.

**Safe migration path:** keep both origins live. Users sign in on rafii.io with Google or email. A WebAuthn-only MFA user first adds a TOTP factor **on the old host**, then passes AAL2 on rafii.io with TOTP and enrolls a new rafii.io passkey factor. Verifying a new factor signs out that user's other sessions, which is Supabase behavior, so tell them. Change the sign-in-passkey RP ID to `rafii.io` only in a planned step, with notice. Until then, A should hide the passkey sign-in button and the phone passkey proof on hosts other than the RP ID (code change, see §10). The Founder sign-in form already offers "Use authenticator code instead" when a TOTP factor exists (`web/src/features/founder/shell/sign-in-form.tsx:259`).

## 3. Social OAuth connectors

### 3.1 Which providers break if `POSTRIFF_PUBLIC_BASE_URL` changes before their console has the new callback
These have credentials in prod. Their `redirect_uri` is `{POSTRIFF_PUBLIC_BASE_URL}/api/oauth/{id}/callback`, so new connects and reconnects fail with a redirect-URI mismatch until the provider console lists the rafii.io callback. **Existing tokens and refresh are unaffected**: no refresh path sends `redirect_uri`, as checked in `providers.py`, `social_connectors.py`, `wave3_connectors.py` and `wave4*`.

| Provider id | Adapter | New callback to add (keep the old one) |
|---|---|---|
| linkedin | `src/postriff_phase2/providers.py:63` | `https://rafii.io/api/oauth/linkedin/callback` |
| instagram (Instagram Login) | `providers.py:160` | `https://rafii.io/api/oauth/instagram/callback` |
| facebook (Pages, Facebook Login for Business) | `src/postriff_phase2/wave3_connectors.py:46` | `https://rafii.io/api/oauth/facebook/callback` |
| x | `src/postriff_phase2/social_connectors.py:50` | `https://rafii.io/api/oauth/x/callback` |
| youtube (Google) | `wave3_connectors.py:181` | `https://rafii.io/api/oauth/youtube/callback` |
| tiktok | `wave3_connectors.py:251` | `https://rafii.io/api/oauth/tiktok/callback` |
| discord | `social_connectors.py:213` | `https://rafii.io/api/oauth/discord/callback` |

No console action is needed for Mastodon or Pixelfed (dynamic registration), Telegram (auto `setWebhook`) or Bluesky (self-hosted metadata, see §3.2). Threads, Pinterest, Reddit, GBP, Weibo, Bilibili, Douyin, Kuaishou, Zhihu, LINE, Xiaohongshu, Notion and Gmail have no prod credentials or flags. When any of them is enabled later, register `https://rafii.io/api/oauth/{id}/callback` (plus the old one).

Media publishing uses Supabase signed URLs (`src/postriff_phase2/hosted_social.py:82-88`) and TikTok `FILE_UPLOAD` (`wave3_connectors.py:358`). Neither depends on the app domain.

### 3.2 Bluesky (breaks existing connections)
`client_id` is the metadata URL on `POSTRIFF_PUBLIC_BASE_URL` (`atproto_oauth.py:131`). atproto refresh tokens are bound to the client, and refresh signs a `client_assertion` with `iss=sub=client_id` (`:240-241,313-317`). If the base URL changes, old grants refresh with a different `client_id`. Access tokens last ≤15 min (`:120`), so **every existing Bluesky connection needs reconnecting within about 15 minutes.** Also, the old URL would then serve a document whose `client_id` field ≠ its own URL, so in-flight old-client flows fail. Options:
- **(a) recommended**: a small code change. Add `POSTRIFF_BLUESKY_CLIENT_ORIGIN` (default `POSTRIFF_PUBLIC_BASE_URL`), used for `client_id`, `client_uri`, `jwks_uri` and **its own** `redirect_uris`/PAR/exchange redirect, instead of the generic `callback_uri`. Set it to `https://postriff-phase2-private.vercel.app` permanently (or until an announced re-connect). The old-domain callback already 302s to `{POSTRIFF_PUBLIC_BASE_URL}/channels/connect` (`hosted_app.py:583-611`), so the user still lands on rafii.io.
- Or accept a forced Bluesky reconnect and announce it. First count the affected connections (§9, unverified).

### 3.3 Optional per-provider decoupling
Provider approvals can lag (TikTok and Google may require re-review). A small code change (a) can add an optional `POSTRIFF_OAUTH_<ID>_CALLBACK_ORIGIN` (default `POSTRIFF_PUBLIC_BASE_URL`). A provider whose console has not been updated keeps using the old-domain callback, which still lands on rafii.io through the existing 302. This lets the web cutover proceed without waiting for every console.

## 4. Webhooks and signed links

| Item | Where | Class |
|---|---|---|
| Stripe webhook `/api/billing/webhook` (`hosted_app.py:521-527`) | Stripe is not configured in prod. When it is, keep the single endpoint on whichever domain is registered. A second endpoint would need a second secret (one `STRIPE_WEBHOOK_SECRET`). | (c) |
| Resend/Svix webhook `/api/notifications/email/webhook` (`src/postriff_phase2/coworker/http.py:61-73`) | Not configured in prod | (c) |
| One-click unsubscribe `/api/notifications/unsubscribe` (`coworker/http.py:75-85`, `delivery.py:143`) | HMAC token, host-agnostic. Old emails keep working while the old domain serves. | (c) |
| Telegram `/api/telegram/webhook` (`hosted_app.py:559-566`) | Secret-token header. Auto re-pointed on the next Telegram connect. | (c) keep both |
| Xiaohongshu `/api/xiaohongshu/webhook` (`hosted_app.py:567-580`) | HMAC. Not configured. | (c) |
| Twilio/Dial phone webhooks and media | Built from `RAFII_PHONE_PUBLIC_BASE_URL` | (c) keep on the old domain |
| Twilio SMS status (`sms.py:167,181`) | `POSTRIFF_PUBLIC_BASE_URL`. SMS is off. | (a) |
| Web Push / VAPID (`src/postriff_phase2/notifications/push.py:103-119`, `web/src/lib/coworker/push.ts:41`, `web/public/sw.js`) | Subscriptions are per-origin. Old-host subscriptions keep delivering, and clicks open old-host `/app`. rafii.io users re-enable push there. `POSTRIFF_VAPID_SUBJECT` is a contact (mailto/https), not origin-bound. | (c). Optionally set the subject to `https://rafii.io` later. |
| Cron (`vercel.json:101-105`) | Relative path | (c) |

## 5. Origin, CSRF, CORS, headers, SW, manifest, SEO

| Item | Finding | Class |
|---|---|---|
| Consumer API guard `hosted_app.py:310-320`, applied at `:702` | Mutations need `X-Postriff-Request: founder-alpha` and `Origin == {X-Forwarded-Proto}://{X-Forwarded-Host or Host}`. Same-origin by construction, so it works for any host. | (c) |
| CORS | No `Access-Control-Allow-Origin` anywhere; same-origin only | (c) |
| Founder Control `RAFII_CONTROL_ORIGINS` | Host allowlist (404 otherwise), exchange/CSRF origin checks, `__Host-` cookie | (a) append `https://rafii.io` |
| Headers `vercel.json:57-98` | `Permissions-Policy: camera=(), microphone=(self), geolocation=()`; `/sw.js` CSP `default-src 'self'; script-src 'self'`; `Service-Worker-Allowed: /` | (c) host-agnostic |
| Service worker | `register('/sw.js', {scope:'/'})`; `notificationclick` opens same-origin `/app` only | (c) |
| Manifest `web/src/app/manifest.ts` | Relative `start_url` | (c) |
| robots/sitemap/metadataBase/og:url/JSON-LD | Follow `NEXT_PUBLIC_APP_URL` (§1.1). No explicit `<link rel=canonical>` (no `alternates.canonical`). | (a). Optionally add `alternates: { canonical: '/' }` per page so the old host points crawlers at rafii.io. |
| `next.config.ts` | `allowedDevOrigins:['127.0.0.1']` (dev only), no host config | (c) |
| `web/public/robots.txt` | Shadowed by `app/robots.ts`; prod serves the dynamic one | (c) |

## 6. Verification files and well-known routes
- Bluesky metadata and JWKS: `/api/oauth/bluesky/client-metadata.json`, `/api/oauth/bluesky/jwks.json` (`hosted_app.py:556-558`). Keep them served on the old domain (§3.2).
- `web/public/tiktokZXN6P78dvnOAOs6qgUIUjfBG4ZWRu5iv.txt` verifies the **old** URL property. It is static and is also served on rafii.io, but a rafii.io property needs its own signature from TikTok. **(b)** James adds a URL property for `https://rafii.io/` in the TikTok developer portal, then either (i) adds the DNS TXT record the portal shows at the registrar, or (ii) sends A the new file name/content to add under `web/public/` (a).
- No Apple (`apple-app-site-association`), Google site-verification, `assetlinks.json` or `/.well-known/webauthn` files exist in `web/public`. Google Cloud may require **Search Console verification of `rafii.io`** before it can be added as an authorized domain (§8).

## 7. Ordered switch plan (each step has a read-only check)

**Step 0, now (no user impact).**
1. James: set DNS at Spaceship (§8.1).
2. James: Supabase Redirect URLs, **add** `https://rafii.io/**`. Keep everything else, including the Site URL.
3. A: `RAFII_CONTROL_ORIGINS`, append `,https://rafii.io` (Production scope only). It takes effect at the next production redeploy, so bundle it with step 5 or redeploy the current production SHA.
4. James: add the rafii.io callbacks in every live provider console (§8.3), keeping the old ones.
5. A (code, recommended before cutover): the Bluesky origin pin (§3.2); optionally the per-provider callback origin (§3.3); hide passkey sign-in and phone passkey proof on non-RP hosts (§2.2); `validate_postriff_hosted_preview.py:26` accepts rafii.io; `site.ts` fallback set to rafii.io.

Read-only checks:
- `dig +short A rafii.io` → `76.76.21.21`.
- `dig +short www.rafii.io` → Vercel.
- `vercel domains inspect rafii.io` shows no WARNING.
- `curl -sI https://rafii.io/` → 200 with a valid cert.
- `curl -sI 'https://www.rafii.io/pricing?x=1'` → `308 location: https://rafii.io/pricing?x=1`.
- `curl -s https://rafii.io/api/health` → 200.
- `curl -s -o /dev/null -w '%{http_code}' https://rafii.io/api/control/v2/session` → **404** before step 3 and **401** after (host allowed, not signed in).
- Supabase: on rafii.io, start Google sign-in and confirm the return lands on `https://rafii.io/auth/callback` and not the old Site URL. This is a manual check by James. Optionally inspect the `redirect_to`/`referrer` the authorize request accepted.

**Step 1, DNS/TLS live, before cutover.** rafii.io already works end to end on the old env: the same deployment, same-origin API and host-agnostic guards. OAuth connects started on rafii.io still land on the old origin (`/channels/connect` there), which needs an old-domain session, so expect connector UX friction during this window. Do not advertise rafii.io yet.

**Step 2, cutover (one production redeploy).** Precondition: every live provider in §3.1 lists the rafii.io callback, **or** the §3.3 override is in place for laggards. Also the Bluesky decision is made. Set **both** `NEXT_PUBLIC_APP_URL=https://rafii.io` and `POSTRIFF_PUBLIC_BASE_URL=https://rafii.io` (Production scope only), then redeploy. Leave `RAFII_PHONE_PUBLIC_BASE_URL`, Preview/staging variables and any webhook endpoints unchanged. Pick a low-traffic window, because in-flight connects (≤10 min) land on rafii.io and may need a sign-in there.

Read-only checks:
- `curl -s https://rafii.io/robots.txt` shows `Sitemap: https://rafii.io/sitemap.xml`.
- og:url is rafii.io.
- `curl -sI 'https://rafii.io/api/oauth/linkedin/callback?state=s&code=c'` → `302 Location: https://rafii.io/channels/connect?…provider=linkedin`. The same request on the old domain → Location **rafii.io**.
- `curl -s https://postriff-phase2-private.vercel.app/api/oauth/bluesky/client-metadata.json`: `client_id` is still the old URL (if pinned).
- Authenticated provider catalog shows no "register its callback" issue.
- One real connect per provider, done by James.

**Step 3, Supabase Site URL.** Change it to `https://rafii.io` and keep the old allowlist entry. Check the email templates.

**Step 4, passkeys (planned, announced).** Either keep the RP ID on the old host (passkey sign-in only works there) or switch it to `rafii.io` with origin `https://rafii.io`. Switching invalidates every existing sign-in passkey, and users re-register on rafii.io. Tell WebAuthn-only MFA users to add TOTP on the old host first (§2.2).

**Step 5, later and optional.** Phone base URL (with the Dial console `wsUrl`), VAPID subject, support mailbox. **Never** blanket-redirect `postriff-phase2-private.vercel.app`. Many senders do not follow redirects (webhooks, Telegram, Twilio), Bluesky client metadata must be served at its exact URL, and a redirect would force every signed-in user onto an origin where they are signed out. If a redirect is ever wanted, limit it to marketing paths and exclude `/api/*`, `/auth/*`, `/app/*`, `/founder/*`, `/channels/*`, `/connectors/*`, `/invite/*` and `/sw.js`.

## 8. James-only console actions (exact)

1. **Spaceship (registrar of rafii.io)**: DNS. Either:
   - (i) Advanced DNS: `A` host `@` value `76.76.21.21`, plus `CNAME` host `www` value `cname.vercel-dns.com`; or
   - (ii) Nameservers set to custom `ns1.vercel-dns.com`, `ns2.vercel-dns.com`, then manage DNS in Vercel.

   Remove any Spaceship parking or URL-forward records for `@`/`www`.
2. **Supabase Dashboard** (project `buoyhkbodnhzngaotoel`):
   - Authentication → URL Configuration → Redirect URLs: **add** `https://rafii.io/**`. Keep the two existing entries.
   - Later (step 3): Site URL = `https://rafii.io`.
   - Authentication → Emails → Templates: confirm whether they use `{{ .Token }}` only, or also `{{ .ConfirmationURL }}`/`{{ .SiteURL }}`.
   - Step 4 only, after notice: Authentication → Passkeys → Relying Party ID `rafii.io`, Relying Party Origins `https://rafii.io`. This invalidates existing sign-in passkeys.
3. **Provider consoles**: add each value and keep the old `https://postriff-phase2-private.vercel.app/...` entry.
   - LinkedIn Developer Portal → app → Auth → *Authorized redirect URLs for your app*: `https://rafii.io/api/oauth/linkedin/callback`
   - Meta App Dashboard (Instagram app) → Instagram → API setup with Instagram login → Business login settings → *OAuth redirect URIs*: `https://rafii.io/api/oauth/instagram/callback`
   - Meta App Dashboard (Facebook Pages app) → Facebook Login for Business → Settings → *Valid OAuth Redirect URIs*: `https://rafii.io/api/oauth/facebook/callback`. Also App settings → Basic → *App domains*: add `rafii.io`.
   - X Developer Portal → Project → App → User authentication settings → *Callback URI / Redirect URL*: `https://rafii.io/api/oauth/x/callback` (optionally Website URL `https://rafii.io`)
   - Google Cloud Console (YouTube OAuth client) → APIs & Services → Credentials → OAuth 2.0 Client ID (Web) → *Authorized redirect URIs*: `https://rafii.io/api/oauth/youtube/callback`. Also Google Auth Platform → Branding → *Authorized domains*: add `rafii.io`. This may require verifying rafii.io in Google Search Console, and with sensitive YouTube scopes branding changes may trigger re-verification.
   - TikTok for Developers → app → Products → Login Kit → *Redirect URI* (Web): `https://rafii.io/api/oauth/tiktok/callback`. Also App details → URL properties: add and verify `https://rafii.io/`. Edits to a live app may need resubmission for review.
   - Discord Developer Portal → app → OAuth2 → *Redirects*: `https://rafii.io/api/oauth/discord/callback`
4. **Dial console** (only when moving the phone base URL, step 5): self-hosted audio `wsUrl` = `wss://rafii.io/api/phone/dial/media`. Do this at the same time as `RAFII_PHONE_PUBLIC_BASE_URL=https://rafii.io`.
5. Nothing to change in Stripe or Resend today: neither is configured in prod.

## 9. What could log users out or break connected accounts

| Risk | Trigger | Impact | Mitigation |
|---|---|---|---|
| Bluesky grants fail | Changing `POSTRIFF_PUBLIC_BASE_URL` without a pin | Every Bluesky connection needs reconnecting within about 15 min | §3.2 pin. Count first (unverified). |
| New connects fail | Base switched before a provider console lists rafii.io | Connect/reconnect error for that provider; existing tokens fine | §8.3 first, or §3.3 override |
| Passkey sign-in fails on rafii.io | RP ID is still the old host | Users fall back to Google/email | Hide the button on non-RP hosts (§10) |
| All sign-in passkeys invalid | Changing the RP ID | Users re-register | Planned step with notice |
| WebAuthn-only MFA users locked out on rafii.io | Factor hostname binding | Cannot reach AAL2 on rafii.io | Add TOTP on the old host first; keep the old host live |
| Other sessions signed out | Verifying a newly enrolled MFA factor (Supabase behavior) | That user's old-host and other-device sessions end | Expected; tell them |
| "Signed out" on rafii.io | Host-only cookies | One sign-in on rafii.io; old sessions remain | Expected; not a revocation |
| Founder Control 404 on rafii.io | `RAFII_CONTROL_ORIGINS` lacks rafii.io | Founder uses the old host | Step 0.3 |
| Phone readiness broken | Changing `RAFII_PHONE_PUBLIC_BASE_URL` without the Dial console | Calls blocked | Keep it unchanged (c) |
| Webhooks, Bluesky metadata, old email links, push clicks | Blanket redirect or removing the old domain | Silent failures | Never redirect or remove the old domain |

**Not verified (needs an approved read):** counts of active Bluesky connections, verified WebAuthn MFA factors and sign-in passkeys in production; the current Supabase passkey RP ID and origins; the current Supabase Site URL and Redirect URLs (last recorded 2026-10-02); current values of `RAFII_CONTROL_ORIGINS`, `POSTRIFF_VAPID_SUBJECT` and `RAFII_PHONE_PUBLIC_BASE_URL`; email template contents. My production DB read was denied by this session's permission classifier and I did not retry it.

## 10. Code changes A could make (none made here)
1. Bluesky origin pin (`atproto_oauth.py` mount/`__init__`/`begin`/`exchange`, plus a test in `tests/test_hosted_wave1_connectors.py`).
2. Optional `POSTRIFF_OAUTH_<ID>_CALLBACK_ORIGIN` in `OAuthService.callback_uri` (`oauth.py:195-199`), validated as fixed HTTPS, never from the request.
3. Passkey gating: offer passkey sign-in, registration and phone proof only when `window.location.hostname` equals a new public `NEXT_PUBLIC_PASSKEY_RP_ID` (`web/src/lib/auth/passkeys.ts:21-23`). That covers the callers `auth-form.tsx:91`, `sign-in-form.tsx:53`, `passkeys-card.tsx`, `verify-call.tsx:28` and `agent-call-security.tsx:16`.
4. `web/src/config/site.ts:7` fallback set to `https://rafii.io`. `scripts/validate_postriff_hosted_preview.py:26` accepts rafii.io as production.
5. Optional: page-level `alternates.canonical`, so pages served on the old host declare rafii.io canonical.
