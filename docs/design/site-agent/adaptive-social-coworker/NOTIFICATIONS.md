# Notification platform: contract, runbook, deliverability

Spec §14–§18. The code lives in `src/postriff_phase2/notifications/`. The generated event and template tables are in [NOTIFICATION_CATALOG.md](NOTIFICATION_CATALOG.md).

## Flow

```text
authoritative state / explicit emit (inside the domain transaction)
  → pr_notification_events (dedupe: scope_key + dedupe_key)
  → planner (pure code: recipients by permission, urgency, channels, quiet hours, digest, mute, unsubscribe, rate limits)
  → pr_notification_deliveries (one per event × person × channel; unique; idempotency_key)
  → in-app: delivered at creation (the notification centre)
  → email / push: claimed by the cron worker → commit → send → fenced completion
```

### Where events come from

**Derived events.** `detector.from_state` and `detector.from_database` read authoritative state. They cover publishing jobs, reviews, channels, automation runs, weekly plans, learning proposals, subscriptions, trials, budgets and engagement. `detector.security_events` reads the audit log. The detector runs in two places:
- the `repository.effects` hook, inside the same transaction as every command;
- the cron scan, for changes the workers make outside `repository.command`.

The cron scan checks every workspace whose revision changed since its last scan (`pr_notification_scan`), and re-checks any workspace not scanned for an hour, so billing, trial and token-expiry conditions reach idle workspaces too.

**Turning v2 on (baseline).** A workspace's first scan records the events its state already implies without notifying anyone, unless the workspace was created in the last 10 minutes. The very first cron run treats the last day's security audit rows the same way. Their dedupe keys are then spent, so enabling the flag never mails people about months-old failures or repeats alerts the legacy mailer already sent. Only conditions that arise after the baseline notify.

**Explicit events.** New coworker features call `NotificationService.emit(cur, …)` in their own transaction. The Weekly Operator emits `campaign.week_ready` and `campaign.blocked`, Source → Campaign emits `campaign.drafts_ready`, performance emits `analytics.weekly_ready` (only when posts were published in the last 7 days) and `analytics.anomaly_detected`, and listening emits `opportunity.detected`.

**Automation parity.** For the legacy automation notices routed to v2, the detector emits `campaign.approval_required` when the worker records its review request (`notices.reviewSentAt`), again (its own key) when an approval was voided, and `publish.failed` for an item that failed without a job. `research.needs_input` covers source campaigns waiting on the person, and `asset.review_required` covers images Rafii generated that no post uses yet. `billing.subscription_active` is keyed on the subscription, so a renewal does not send it again. `trial_ended` stays with the legacy mailer.

**Publishing truth.**
- `publish.verified` fires only on job state `verified`. It never fires on `published` or `provider_accepted`.
- `publish.uncertain` fires on `uncertain`.
- `publish.failed` fires on `failed`.
- A `held` job produces `campaign.blocked`, because it needs a new approval.

## What a model never decides

The model never decides any of these:
- recipients (the permission class in the catalogue, re-checked against live memberships);
- urgency, channels and transactional status;
- security classification;
- dedupe, quiet hours, digest, mute, unsubscribe and rate limits.

The model's only role is the words in an in-app summary, where one exists.

## Preferences (`pr_notification_preferences`)

Each preference row is keyed by `(user_id, scope_key, category)`:
- `scope_key` is a workspace id, or `*` for the person's defaults;
- `category` is a catalogue category, or `*` for every category.

The fields are `in_app`, `email_mode` (immediate, digest or off), `push_mode` (immediate or off), `digest_frequency` (daily, weekly or off), `quiet_start`/`quiet_end` (minutes after midnight in `time_zone`, falling back to the profile's zone), `muted_until` and `email_unsubscribed`. Every field is nullable: null means "not set in this row", so a broader row or the catalogue default decides. An explicit `email_unsubscribed = false` on a narrower scope therefore re-subscribes it even when a broader row unsubscribes.

Resolution takes the first non-null value for each field, most specific first:
1. (workspace, category)
2. (workspace, `*`)
3. (`*`, category)
4. (`*`, `*`)
5. the catalogue default

Transactional events (`billing.*`, `security.*`) always send email. Unsubscribe and mute do not apply to them, and security events break quiet hours.

Quiet hours work like this:
- They defer push, and routine (info or action) email, until the end of the window in the person's time zone. The time is resolved on the actual date, so DST changes are handled.
- Critical email (a failure, an uncertain publish, a reconnect) is not held back.
- Critical push waits for the end of quiet hours.
- Security breaks through.

Rate limits: after 6 immediate pushes or 12 immediate emails per person per hour, email goes to the digest and push is suppressed. Critical and security push is exempt. Nothing is dropped silently: a suppressed row keeps its reason.

## Delivery semantics

**Queue.** Postgres rows with `FOR UPDATE SKIP LOCKED` and `lease_owner`/`lease_until`. A claim commits before any network call, and completion is fenced on `(id, lease_owner)`.

**Idempotency.** The idempotency key is `delivery.idempotency_key`. It is sent to Resend as the `Idempotency-Key` header and as a `delivery_id` tag. After a crash following a claim, the lease expires, the row is re-claimed and it is resent with the same key, so Resend dedupes it. A push repeat carries the same `Topic`, so it replaces the earlier notice on the device.

**Retries.** Transient failures (5xx, 429, a timeout or a lost response) retry with backoff `min(60 s · 2^(attempt−1), 6 h)` plus 0–29 s of deterministic jitter. There are at most 6 attempts for email and 5 for push. After that the delivery is `dead`.

**Other outcomes.**
- Preferences are re-checked when the message is about to go out. An unsubscribe, a bounce or complaint suppression, a mute, or a channel switched off after the delivery was planned completes it as `suppressed` with the reason; transactional notices ignore these, as at planning time.
- A permanent failure (a provider 4xx, or a push 404/410) is `failed`. A push 404/410 also revokes the subscription. A push service's redirect is never followed (the VAPID header must not travel).
- An unconfigured transport is `suppressed` with that reason. It is never reported as sent.
- A person who has left the workspace gets `cancelled`.
- An expired event is `cancelled`.

**Domain isolation.** Delivery rows and their transactions are separate from domain state, so a failed or dead delivery never rolls back domain work. This is tested (N05, N10).

**Digest.** At the digest time (09:00 local, daily or on Monday), all of a person's due digest deliveries are claimed together. One email is sent with an idempotency key over the included rows, and each of them becomes `sent` with the same `digest_id`. Rows that no longer apply are completed as `cancelled` (left the workspace, expired) or `suppressed` (opted out), never as sent. A digest whose claim expired after a crash is recovered on its own, with the same rows, so the same key and body go to the provider. The provider webhook applies a digest's outcome to all its rows.

**Stable bodies.** An unsubscribe link's expiry is based on when the delivery was created, not when it is sent, so a retry renders the same body under the same Idempotency-Key (Resend refuses a different body under a key it has seen).

**Legacy bridge.** With `RAFII_NOTIFICATIONS_V2_ENABLED` on, `Mailer._deliver` refuses the kinds v2 owns, returning `routed_to_notifications_v2`. Invitations and the welcome email stay direct. With the flag off, the old path is byte-for-byte unchanged.

**Operations.** `operational_signals.snapshot` reports `notificationBacklog` (due for more than 10 minutes) and `notificationDead24h` when v2 is on.

## HTML email

`notifications/email_render.py` provides the components EmailShell, Preheader, BrandHeader, ContextLabel, Headline, StatusPill, PrimaryCard, MetricsRow, PrimaryCTA, SecondaryAction, Footer and NotificationSettingsLink. There are 24 templates, each in 4 locales: en, zh-Hant-HK (also used for Cantonese/yue), zh-Hant and zh-Hans. Every message has a plain-text twin.

The rules:
- Exactly one primary CTA, with an absolute https deep link built from an `/app…` path. Anything else, including `javascript:` or an external URL, falls back to `/app`.
- Everything is HTML-escaped.
- Subjects and preheaders are one line and carry no private content.
- `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` are sent for non-transactional mail. The link carries a signed token (HMAC, 180 days).
- Dark mode is tolerated through `color-scheme` plus a `prefers-color-scheme` style block.
- Every rendered email is under 102 KB, so Gmail doesn't clip it.
- The template version is `rafii-email/1.0.3`.

Previews are in `evidence/email/`. The browser check (`scripts/rafii_email_render_check.cjs`) ran Chromium and WebKit, light and dark, at 600 and 375 px, with axe WCAG 2 A/AA: 768/768 pass. The result is in `evidence/email-render.json`, and the screenshots are in `evidence/email-shots/`.

## Resend setup and deliverability runbook (owner actions; nothing here has been run against production)

1. **Sender domain.** In Resend, add the sending subdomain (for example `notify.<domain>`) and publish the records Resend shows:
   - SPF: `v=spf1 include:amazonses.com ~all` on the subdomain;
   - DKIM: a TXT record at `resend._domainkey.<subdomain>`;
   - the MX record Resend lists for bounces.
2. **DMARC.** Publish a record on the organisational domain: `v=DMARC1; p=none; rua=mailto:dmarc@<domain>` for 2–4 weeks. Once the aggregate reports are clean, move to `p=quarantine` and then `p=reject`.
3. **Health check.** Run `python scripts/rafii_email_dns_check.py --domain notify.<domain>`. It does read-only public DNS lookups. It exits 1 on an error and warns on `p=none` or a missing `rua`.
4. **Webhook.** In Resend, create a webhook to `https://<app>/api/notifications/email/webhook` for `email.sent`, `email.delivered`, `email.bounced`, `email.complained`, `email.failed`, `email.opened` and `email.clicked`. Store its `whsec_…` secret as `RESEND_WEBHOOK_SECRET`, and pin it in the preview secret list (`deployment.isolated_environment`). How webhooks are handled:
   - They are verified with Svix (`svix-id`, `svix-timestamp`, `svix-signature`), with a 300 s tolerance and a constant-time compare.
   - Replays are duplicates, keyed on `pr_notification_provider_events`.
   - A bounce marks the delivery failed and suppresses future non-transactional email to that person.
   - A complaint unsubscribes the person.
   - Opens and clicks become product events.
5. **Environment.** Set `EMAIL_FROM` to a sender on that domain, and keep `RESEND_API_KEY` server-only.
6. **First live test (needs authorization).** Send one email to an owner-controlled address with `RAFII_NOTIFICATIONS_V2_ENABLED=1` in a staging deployment. The expected cost is one Resend email; free-tier limits apply. To roll back, turn the flag off.

## Web Push (spec §18)

**Opt-in.** Only an explicit click in Account → Notifications starts it. The browser's `Notification.requestPermission()` is never called on page load. After permission, `PushManager.subscribe({userVisibleOnly: true, applicationServerKey: VAPID public key})` runs, and the subscription is POSTed to `/push-subscriptions`.

**Storage.** The endpoint, `p256dh` and `auth` are encrypted with `CredentialVault` (Fernet, `POSTRIFF_CREDENTIAL_KEY`), plus `endpoint_sha256` for uniqueness. Rotating the credential key makes stored subscriptions unreadable: they are revoked (`key_rotated`), and the browser re-subscribes on the next opt-in.

**Endpoint allowlist.** Only https push services are accepted: FCM, Mozilla autopush, Apple (`web.push.apple.com`) and WNS. Anything else, including internal addresses, is refused at subscribe time and again at send time, so a subscription can never make the server call an arbitrary URL.

**Transport.** RFC 8291 aes128gcm and RFC 8292 VAPID (ES256 JWT, `aud` = the push service origin, `exp` ≤ 24 h), built on `cryptography` with no SDK. The headers are `TTL`, `Urgency`, `Topic` (the grouping key) and `Content-Encoding: aes128gcm`.

**Payload.** Only `{title, body (≤120 chars), url (same-origin /app… path), tag, category}`, at most 3 KB before encryption. It never contains draft text, DMs, analytics, credentials or secrets.

**Responses.** 201/202 is sent. 404/410 means gone, and the subscription is revoked. 429 is transient and honours Retry-After. 400/401/403 is config. 413 is permanent. No response is uncertain, and it is retried with the same Topic.

**Service worker.** `web/public/sw.js` handles `push` (showNotification with tag and data.url) and `notificationclick`, which opens only same-origin `/app…` URLs and focuses an existing client. It does no caching and no fetch interception. `vercel.json` serves `/sw.js` with `Cache-Control: no-cache`, `Service-Worker-Allowed: /` and a strict CSP.

**Revocation.** `DELETE /push-subscriptions/{id}` or `POST …/unsubscribe {endpoint}`, audited as `push.revoked`. Account deletion removes all of a person's subscriptions.

**Platform limits.** iOS and iPadOS deliver web push only to a web app added to the Home Screen (16.4+), so the settings page explains that instead of showing a broken button.

**Native later.** APNs and FCM would be new `PushTransport` implementations behind the same `NotificationService` contract.

**Keys.**
- Generate VAPID keys with `python -c "from postriff_phase2.notifications.push import generate_vapid_keys as g; print(g())"`.
- Set `POSTRIFF_VAPID_PUBLIC_KEY`, `POSTRIFF_VAPID_PRIVATE_KEY` (a secret; pin it in preview) and `POSTRIFF_VAPID_SUBJECT` (`mailto:` or `https:`).
- Rotating keys invalidates existing subscriptions, so people must opt in again.

**First live test (needs authorization).** One owner-controlled browser, in staging, with `RAFII_WEB_PUSH_ENABLED=1`. There is no cost. To roll back, turn the flag off.

## Retention

- Event payloads carry presentation fields only (ids, platform, short reason, link). Addresses are never stored, and bodies are never stored.
- Deliveries and events belong to their workspace (cascade on workspace deletion).
- Person-level rows are removed by account deletion (push subscriptions, preferences, deliveries, person-scoped events, product events and experiment assignments).
- Product events expire after 400 days; the coworker cron deletes expired rows in bounded batches.
