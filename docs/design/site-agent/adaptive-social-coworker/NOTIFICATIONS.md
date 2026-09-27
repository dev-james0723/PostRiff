# Rafii unified attention and notification platform

Spec §14–§18. The code lives in `src/postriff_phase2/notifications/`. The generated event and template tables are in [NOTIFICATION_CATALOG.md](NOTIFICATION_CATALOG.md).

## Flow

```text
authoritative state / explicit emit (inside the domain transaction)
  → pr_notification_events (dedupe: scope_key + dedupe_key)
  → deterministic planner / Attention Router (permission, urgency, consent, quiet hours, mute, rate and cost limits)
  → pr_notification_deliveries (one per event × person × channel; unique; idempotency_key)
  → in-app: delivered at creation (the notification centre)
  → email / push / sms: claimed by the cron worker → commit → send → fenced completion
  → phone: existing Phone Mode worker, sharing the same event/delivery ledger
  → durable receipts / acknowledgements → Rafii Notification Centre
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
- consent, routing, escalation timing, dedupe, quiet-hour bypass, digest, mute, unsubscribe, retries and rate/cost limits.

The model's only role is the words in an in-app summary, where one exists.

## Preferences (`pr_notification_preferences`)

Each preference row is keyed by `(user_id, scope_key, category)`:
- `scope_key` is a workspace id, or `*` for the person's defaults;
- `category` is a catalogue category, or `*` for every category.

The fields are `in_app`, `email_mode` (immediate, digest or off), `push_mode` (immediate or off), `sms_mode` (important_only or off), `smart_escalation`, `digest_frequency` (daily, weekly or off), `quiet_start`/`quiet_end` (minutes after midnight in `time_zone`, falling back to the profile's zone), `muted_until` and `email_unsubscribed`. Every field is nullable: null means "not set in this row", so a broader row or the catalogue default decides. An explicit `email_unsubscribed = false` on a narrower scope therefore re-subscribes it even when a broader row unsubscribes. SMS defaults to off; Smart escalation defaults to on but cannot enable SMS or grant consent.

Resolution takes the first non-null value for each field, most specific first:
1. (workspace, category)
2. (workspace, `*`)
3. (`*`, category)
4. (`*`, `*`)
5. the catalogue default

Transactional events (`billing.*`, `security.*`) always send email. Email unsubscribe and mute do not apply to them; security Email/Push can break quiet hours. SMS always requires its own consent, obeys mute and quiet hours, and never inherits transactional exceptions.

Quiet hours work like this:
- They defer push, and routine (info or action) email, until the end of the window in the person's time zone. The time is resolved on the actual date, so DST changes are handled.
- Critical email (a failure, an uncertain publish, a reconnect) is not held back.
- Critical push waits for the end of quiet hours.
- Security Email/Push breaks through. All SMS, including security, waits.

Rate limits: after 6 immediate pushes or 12 immediate emails per person per hour, email goes to the digest and push is suppressed. Critical and security push is exempt. Nothing is dropped silently: a suppressed row keeps its reason.

## Delivery semantics

**Queue.** Postgres rows with `FOR UPDATE SKIP LOCKED` and `lease_owner`/`lease_until`. A claim commits before any network call, and completion is fenced on `(id, lease_owner)`.

**Idempotency.** The idempotency key is `delivery.idempotency_key`. It is sent to Resend as the `Idempotency-Key` header and as a `delivery_id` tag. After a crash following a claim, the lease expires, the row is re-claimed and it is resent with the same key, so Resend dedupes it. A push repeat carries the same `Topic`, so it replaces the earlier notice on the device.

**Retries.** Transient failures (5xx, 429, a timeout or a lost response) retry with backoff `min(60 s · 2^(attempt−1), 6 h)` plus 0–29 s of deterministic jitter. There are at most 6 attempts for email and 5 for push. After that the delivery is `dead`.

SMS has a stricter uncertainty fence: at most 3 attempts, only after known rejection before acceptance (for example HTTP 429). A lost response, ambiguous 5xx/408, malformed accepted response, or crash after the committed dispatch marker becomes terminal `uncertain`. It is never blindly resent. Phone retains its existing one-attempt call policy.

**Other outcomes.**
- Preferences are re-checked when the message is about to go out. An unsubscribe, a bounce or complaint suppression, a mute, or a channel switched off after the delivery was planned completes it as `suppressed` with the reason; transactional notices ignore these, as at planning time.
- A permanent failure (a provider 4xx, or a push 404/410) is `failed`. A push 404/410 also revokes the subscription. A push service's redirect is never followed (the VAPID header must not travel).
- An unconfigured transport is `suppressed` with that reason. It is never reported as sent.
- A person who has left the workspace gets `cancelled`.
- An expired event is `cancelled`.

**Domain isolation.** Delivery rows and their transactions are separate from domain state, so a failed or dead delivery never rolls back domain work. This is tested (N05, N10).

**Digest.** At the digest time (09:00 local, daily or on Monday), all of a person's due digest deliveries are claimed together. One email is sent with an idempotency key over the included rows, and each of them becomes `sent` with the same `digest_id`. Rows that no longer apply are completed as `cancelled` (left the workspace, expired) or `suppressed` (opted out), never as sent. A digest whose claim expired after a crash is recovered on its own, with the same rows, so the same key and body go to the provider. The provider webhook applies a digest's outcome to all its rows.

**Stable bodies.** An unsubscribe link's expiry is based on when the delivery was created, not when it is sent, so a retry renders the same body under the same Idempotency-Key (Resend refuses a different body under a key it has seen).

**Legacy bridge.** With `RAFII_NOTIFICATIONS_V2_ENABLED` on, `Mailer._deliver` refuses the kinds v2 owns, returning `routed_to_notifications_v2`. Invitations and the welcome email stay direct. With the flag off, existing direct delivery behavior remains available; its HTML now uses the same branded Python components and its subjects/preheaders exclude private automation names and arbitrary plan labels.

**Operations.** `operational_signals.snapshot` reports `notificationBacklog` (due for more than 10 minutes), `notificationDead24h` and a separate aggregate `sms` object when v2 is on. SMS metrics include overdue backlog, failed/dead/uncertain deliveries, suppressed/deferred quiet-hour rows, acknowledged cancellations, dispatch counts, segments and known provider cost. Unknown cost is held at its configured reservation for budget enforcement. These aggregates contain no message body, number or address.

## Text messages and durable escalation

`sms` is a first-class channel on the existing `pr_notification_events` → `pr_notification_deliveries` pipeline. `phone` continues to mean a voice call. No second inbox, outbox or raw phone-number store exists.

`RAFII_SMS_ENABLED=0` and `RAFII_SMS_ESCALATION_ENABLED=0` are the safe deployment defaults. Notification V2 must also be enabled. Sending and escalation are server-controlled; isolated Preview environments force both off. Fake local harnesses explicitly enable them with injected fake transports.

### Consent and the shared identity

`pr_sms_consents` is server-only, forced-RLS storage keyed by person. It contains the verified Phone Mode binding hash, opt-in status/version/source, timestamps, separate security-SMS permission and provider STOP state. The encrypted number remains exclusively in `pr_phone_numbers`; the existing Phone Mode vault decrypts it only immediately before egress. Phone verification, call consent and enabling Call Rafii do not grant text consent.

Account → Notifications exposes Push, Email, Text messages (Off / Important only), Smart escalation, Quiet hours and Digest frequency. Selecting Important only explicitly submits consent version `rafii-sms/1`. The UI shows only the last four digits and links to the existing Phone Mode verification flow when needed. Account-change texts require a second explicit setting.

A database trigger invalidates consent and suppresses unsent SMS when the binding changes, becomes unverified or is deleted, even when the change happens outside PhoneService. STOP immediately marks SMS opted out and cancels unsent texts, including when sending flags are off or there was no earlier consent. It leaves Phone, Email and Push preferences alone. START can remove the provider block; it never re-grants application consent. The person must explicitly opt in again.

### Deterministic policy and timing

The catalogue and durable event carry `sms_policy`: `off | escalate | immediate`. Initial `escalate` classes are `publish.failed`, `publish.uncertain`, `channel.reconnect_required`, `billing.payment_failed`, time-sensitive `campaign.approval_required`, and separately consented `security.account_change`. Every other current class is off. `immediate` is supported but no initial event uses it.

Approval becomes time-sensitive only from an authoritative scheduled publish deadline within the next 24 hours. The event expires at that deadline. A later hourly scan can emit a distinct timely occurrence when an existing distant approval enters that window; presentation payloads cannot declare urgency.

- With an eligible pending Push delivery, critical/security fallback is due 10 minutes after its planned Push time; time-sensitive action fallback is due after 30 minutes.
- When Push is unavailable, explicit Important only consent permits immediate eligible SMS, subject to quiet hours and all remaining checks.
- Push-first fallback requires both Smart escalation and the server escalation flag. Turning either off before egress suppresses an already scheduled fallback, even if the Push subscription later disappears.
- The fallback is a durable `sms` delivery with future `next_attempt_at` and `sms_escalation=true`. There is no in-memory timer. Quiet hours can move the due time further; a due time beyond event expiry suppresses it.

At egress, the worker locks the existing identity/consent/event/delivery and re-checks current membership and permission, expiry, authoritative resolution, acknowledgement, consent/version/current verified binding, preference, security opt-in, quiet hours, mute and limits. Per-person limits are 2 texts per rolling hour and 4 per rolling 24 hours. Critical/security messages do not bypass them. Dedupe remains the existing unique event/person/channel contract.

Copy is fixed and localized in `notifications/sms.py` for the four shipped locales (yue uses Hong Kong written Chinese). It contains a static Rafii reason, same-origin HTTPS `/app?notification=…` link and STOP instruction. It never interpolates domain payloads, draft text, DMs, credentials, email addresses or full phone numbers. Maximum copy length is 2 GSM-7/UCS-2 segments; an overly long origin/copy fails closed.

### Provider adapter and prerequisites

`FakeSMSTransport` is used for local acceptance; its receipts retain only delivery references and segment counts. `TwilioSMSTransport` is a separate Messaging adapter using the existing account credential pattern, with its own `TWILIO_SMS_FROM_NUMBER` or `TWILIO_SMS_MESSAGING_SERVICE_SID`. It does not route through the voice-call provider.

Real egress requires an HTTPS `POSTRIFF_PUBLIC_BASE_URL`, configured account/auth/sender, positive `RAFII_SMS_USD_MICRO_PER_SEGMENT` and `RAFII_SMS_DAILY_USD_MICRO`, and `RAFII_SMS_PROVIDER_DAILY_LIMIT` (default 100). The worker serializes provider-cap/budget checks with a PostgreSQL advisory lock and commits the dispatch marker, binding hash, segment estimate and cost reservation before the external call. Signed receipts can replace the estimate with bounded numeric segments/USD cost where supplied. There is no live billing-price polling; the configured estimate must conservatively cover the destination and provider charges. Deletion removes personal delivery rows, so this queue budget is not an immutable provider billing ledger.

Configure the provider's status callback at `/api/notifications/sms/webhook/{delivery_id}` and inbound messaging URL at `/api/notifications/sms/inbound`, matching the exact public origin used for signature verification. HMAC signatures, account identity, delivery binding and lifecycle values are checked; receipt replays are deduped in the shared provider-event ledger. Inbound handling returns empty TwiML and sends no application-generated reply. Sender registration, regional compliance, provider-managed opt-out replies, actual pricing and real delivery require separate owner verification. No live message was sent during implementation.

## Cross-channel acknowledgement and resolution

`pr_notification_acknowledgements` is a forced-RLS server-only row per `(event_id, user_id)`. In-app read/acted/dismissed, authenticated Email/Push/SMS deep-link navigation and relevant domain resolution persist acknowledgement and cancel that person's unsent escalation. Acknowledgement of a digest's primary deep link applies to its included events that the person can still access. Read-all acknowledges the returned in-app events. Email open pixels and provider click telemetry never count as acknowledgement.

The existing Push service worker keeps its architecture. Its safe same-origin deep link now carries a non-secret delivery reference. After authentication, the app calls the workspace-scoped acknowledgement endpoint; ownership and live membership are checked server-side. Knowing a delivery UUID does not grant access or permission to acknowledge another person's event.

Repository effects, cron scan and the SMS egress boundary independently re-check authoritative publish/review/channel/automation/billing state. Resolution records `resolved_at`, acknowledges recipients and cancels unsent texts. Cancellation applies to pending/claimed rows whose dispatch has not started; a provider call already begun cannot be recalled. Events remain in the unified Notification Centre, with channel status and receipts in the same durable delivery ledger.

Migration [034_unified_notifications.sql](../../../../migrations/postriff/034_unified_notifications.sql) was chosen after inspecting all 44 registered worktrees and their migration numbers. It retains `phone`, adds SMS/event policy/preferences/consent/acknowledgements, indexes and forced RLS, and invalidates consent on identity changes. Profile/event foreign-key cascades and account deletion remove SMS consent, acknowledgements, deliveries and associated provider receipts.

This backend requires the 034 schema even while SMS flags are off. Apply the migration in the separately approved target environment before deploying this code; there is no fallback for an unmigrated Notification V2 schema.

## HTML email

`notifications/email_render.py` provides the shared Python components and renderer. Every Notification V2 template is rendered in 4 locales: en, zh-Hant-HK (also used for Cantonese/yue), zh-Hant and zh-Hans, and every message has a plain-text twin. The existing direct account/legacy mailer also uses the branded shell and retains its current English copy. Preview/test coverage is generated from both current renderer catalogues rather than a hard-coded template count.

### Mandatory Rafii email design gate

Every new or modified HTML email must use all design skills on the implementation host that are actually applicable to HTML email, brand composition, static visual hierarchy, accessibility and render QA. On the current Mac this includes `react-email` and `design-partner`, plus `frontend-design`, `redesign-existing-projects`, `brandkit` and `high-end-visual-design` where their guidance remains email-safe. Re-scan installed skills at execution time and record the relevant skills used in the implementation receipt. Do not mechanically invoke unrelated design/video/game skills.

Email-client compatibility wins over web-only design advice. The renderer must remain safe for real email clients: no JavaScript, no motion dependency, no fragile backdrop-filter/glass requirement, no critical web-font dependency, and no runtime migration merely because a React Email skill is available.

Every HTML email must visibly and intentionally contain both:
- the current approved Rafii logo/wordmark, sourced from `web/src/components/marketing/wordmark.tsx` or an exact email-safe export/translation of that mark;
- approved Rafii character art from `web/public/raffi/`.

Do not invent a new Rafii logo. Use `web/src/styles/rafii.css` and `docs/design/reference/rafii-v9/` as brand truth. The character should be a restrained brand accent; substantive content and the CTA must remain usable if remote images are blocked.

All current templates/locales must pass the existing light/dark, 600/375, Chromium/WebKit and axe render checks plus brand-presence and image-blocked degradation checks. Browser previews are evidence, not a claim of Gmail/Outlook certification.

The rules:
- Exactly one primary CTA, with an absolute https deep link built from an `/app…` path. Anything else, including `javascript:` or an external URL, falls back to `/app`.
- Everything is HTML-escaped.
- Subjects and preheaders are one line and carry no private content.
- `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` are sent for non-transactional mail. The link carries a signed token (HMAC, 180 days).
- Dark mode is tolerated through `color-scheme` plus a `prefers-color-scheme` style block.
- Every rendered email is under 102 KB, so Gmail doesn't clip it.
- The redesigned renderer declares template version `rafii-email/1.1.0` (previously `rafii-email/1.0.4`).

The shared header translates the approved 28px inverted R mark and visible Rafii wordmark into table/inline CSS and uses the approved `avatar-128.png` at a restrained 48px. Neutral surfaces, an editorial system-serif headline, generous spacing and one black primary CTA keep the message first. No external font, JavaScript, motion or glass effect is needed. With images and style blocks blocked, the text wordmark, headline, body and CTA remain usable.

Previews are in `evidence/email/`: 25 Notification V2 templates × 4 locales plus 13 current direct English templates (113 previews). `scripts/rafii_email_render_check.cjs` runs every preview in Chromium/WebKit, light/dark, 600/375px, with images enabled and blocked/style-block degradation. It checks all applicable axe WCAG 2 A/AA rules, overflow, visible headline/wordmark, approved character presence, actual local asset resolution, one usable CTA, same-origin HTTPS links, clipping size and plain-text twin. Results and representative screenshots are in `evidence/email-render.json` and `evidence/email-shots/`; the implementation receipt records the actual completed run. This is browser QA, not Gmail/Outlook client verification.

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

**Native scope.** No native APNs/FCM rewrite was introduced; the existing Web Push implementation remains in place.

**Keys.**
- Generate VAPID keys with `python -c "from postriff_phase2.notifications.push import generate_vapid_keys as g; print(g())"`.
- Set `POSTRIFF_VAPID_PUBLIC_KEY`, `POSTRIFF_VAPID_PRIVATE_KEY` (a secret; pin it in preview) and `POSTRIFF_VAPID_SUBJECT` (`mailto:` or `https:`).
- Rotating keys invalidates existing subscriptions, so people must opt in again.

**First live test (needs authorization).** One owner-controlled browser, in staging, with `RAFII_WEB_PUSH_ENABLED=1`. There is no cost. To roll back, turn the flag off.

## Retention

- Event payloads carry presentation fields only (ids, platform, short reason, link). Addresses are never stored, and bodies are never stored.
- Deliveries and events belong to their workspace (cascade on workspace deletion).
- Person-level rows are removed by account deletion (push subscriptions, preferences, deliveries, SMS consent, acknowledgements, delivery-associated provider receipts, person-scoped events, product events and experiment assignments).
- Product events expire after 400 days; the coworker cron deletes expired rows in bounded batches.
