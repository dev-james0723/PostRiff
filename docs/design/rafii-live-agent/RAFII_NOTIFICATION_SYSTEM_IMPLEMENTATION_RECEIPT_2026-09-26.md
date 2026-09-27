# Rafii Unified Notification System — implementation receipt

Date: 2026-09-26 local time (verification logs also cross into 2026-09-27 UTC).

## Outcome and execution boundary

Implemented locally on `feat/rafii-live-agent` in `/Users/ouxianxing/Documents/James-Au-Studio-live-agent`, against unchanged HEAD `d0c68e16457317cbd4950c24fea3e6d7d0a51462`. Notification V2 now supports separate `in_app`, `email`, `push`, `sms` and existing `phone` channels on the same event/delivery ledger. Required local functional, database, web and email rendering checks passed. This is an uncommitted local implementation, not a deployment or release.

No real SMS, customer email, customer Push, PSTN call, production migration, secret change, deployment, merge, commit or push occurred. Provider calls in acceptance tests used fake transports or injected synthetic HTTP responses. Browser weather/Live/Manager interactions used the existing local harness stand-ins.

The initial write-lease conflict was respected. Implementation started only after that owner released the lease; this session acquired its own cooperative lease (`rafii-unified-notifications`, session `01a0e02d-cb9a-7d91-96a0-2f9ff91b2517`, lease reference `9fe04a4bc51d`) and renewed it during work. No takeover, reset, stash or overwrite of another session's product work was used.

Applicable root `AGENTS.md` / `CLAUDE.md`, `web/AGENTS.md` / `web/CLAUDE.md`, and the user-supplied operating instructions were read. The engineering plan and agent handoff governed implementation. The four pre-existing notification/phone plan and handoff files retain their original SHA-256 values; `.claude/skills/` was left untouched. The existing dirty canonical notification documentation's mandatory email design gate was preserved and extended. Phone backend/provider/storage code is unchanged. The only Phone UI edit refreshes the notification-preferences query after its existing verification/settings operation. [Preservation evidence](evidence/notifications/preservation.json).

## Files changed

[changed-files.json](evidence/notifications/changed-files.json) is the exact path inventory, including generated previews, screenshots and verification logs, excluding pre-existing untouched untracked files. Main implementation paths:

- Migration and reservation: `migrations/postriff/034_unified_notifications.sql`, `docs/postriff-migration-numbering.md`, `tests/phase2/rls.sql`.
- SMS: new `src/postriff_phase2/notifications/sms.py` and `sms_delivery.py`.
- Shared event/router/queue: `notifications/catalog.py`, `planner.py`, `store.py`, `service.py`, `delivery.py`, `detector.py`.
- Routes, flags, cleanup and operations: `coworker/http.py`, `coworker/flags.py`, `deployment.py`, `account_deletion.py`, `operational_signals.py`, `.env.example`.
- Existing Python email renderers: `notifications/email_render.py`, `src/postriff_phase2/email.py`.
- Web: `app-shell.tsx`, new `deep-link-acknowledgement.tsx`, `notification-settings.tsx`, `phone-settings.tsx`, `web/src/lib/coworker/api.ts` / `types.ts`.
- Local QA: `scripts/postriff_dev_hosted.py`, `rafii_email_previews.py`, `rafii_email_render_check.cjs`, `rafii_coworker_verify.py`; new SMS unit/PG/browser tests and browser fixture; affected notification/email/campaign/Billing expectations. Product policy `rafii.policy.notification-planning` is version 1.2.0 with its checked hash lock in `skills/rafii-registry.json`; no installed skill was edited.
- Canonical [NOTIFICATIONS.md](../site-agent/adaptive-social-coworker/NOTIFICATIONS.md), generated [NOTIFICATION_CATALOG.md](../site-agent/adaptive-social-coworker/NOTIFICATION_CATALOG.md), current preview catalogue and render evidence.

Temporary Next dev additions to `web/tsconfig.json` were removed; it matches HEAD. Test-generated unrelated agent-runtime evidence was copied into this task's evidence directory, then restored to its original tracked content. The local harness and Next dev server were stopped after QA.

## Architecture and policy

The preserved pipeline is authoritative domain state/event → `pr_notification_events` → deterministic planner/Attention Router → preferences/consent/urgency/quiet hours/mute/rate limits → shared delivery ledger → Notification Centre and durable receipts. No LLM decides recipients, severity, security classification, consent, routing, escalation timing, quiet-hour bypass, dedupe or limits.

SMS defaults off. Important only requires explicit versioned SMS consent and the current verified/encrypted Phone Mode binding. Verification and calling permission never grant text consent. Account-change texts need a separate opt-in. Number replacement, unverified identity or deletion invalidates consent through a database trigger. Provider STOP blocks SMS and cancels unsent texts without changing Phone/Email/Push. START only unblocks provider messaging; fresh application opt-in remains necessary.

The deterministic initial policy is `escalate` for publish failed/uncertain, reconnect required, payment failed, timely approval required and separately consented account-change security events; all other current events are `off`. `immediate` is supported but unused by the initial catalogue. A timely approval is derived from a real scheduled publish deadline within 24 hours and expires at that deadline.

Push-first fallback is a persisted SMS delivery with future `next_attempt_at`: 10 minutes for critical/security, 30 minutes for time-sensitive action, measured from the planned Push time. Quiet hours can delay it further. Explicit Important only permits immediate eligible fallback when Push is unavailable. `sms_escalation` preserves the fallback's origin so disabling Smart escalation or its server flag suppresses it even if Push is subsequently removed. There is no in-memory timer.

Before egress, identity/consent/event/delivery locks serialize current membership/permission, expiry, resolution, acknowledgement, consent version/current binding, preference, security permission, quiet hours, mute and per-user/provider/cost checks. Limits are 2 texts per rolling hour, 4 per rolling 24 hours, maximum 2 segments, and a configurable provider daily cap (100 by default). Real transport requires positive configured per-segment and daily USD bounds. SMS never inherits transactional Email/Push quiet/mute exceptions.

SMS copy is fixed and localized in all four notification locales (yue maps to Hong Kong written Chinese). It uses a static reason and a same-origin HTTPS `/app?notification=…` link; it never interpolates private payloads, draft/DM text, credentials, addresses or full numbers. Phone identity is decrypted only at egress. Delivery rows, provider ledger, fake receipts and logged results retain references/hashes/bounded numeric accounting only.

A durable dispatch marker is committed before the provider call. Known rejection before acceptance can retry, at most 3 attempts. Unknown acceptance, timeout/ambiguous response or a crash after dispatch becomes terminal `uncertain`; expired claims with that marker are not resent. Signed callbacks can reconcile accepted/delivered/failed state without initiating a send. Replays dedupe in the existing provider-event ledger.

Per-event/person acknowledgement is durable. In-app read/acted/dismissed, authenticated Email/Push/SMS navigation, read-all and authoritative domain resolution cancel unsent escalation. Digest primary navigation acknowledges accessible included events. UUID references are not capabilities: server authentication, ownership and current membership still apply. Email open pixels/provider click telemetry do not acknowledge. Push encryption, endpoint allowlist, VAPID transport and service worker architecture are preserved. Native APNs/FCM work was not introduced.

## Migration

[034_unified_notifications.sql](../../../migrations/postriff/034_unified_notifications.sql) was selected after inspecting all 44 registered PostRiff worktrees; the actual highest forward migration was 033. [Pre-creation inventory](evidence/notifications/migration-inventory.json). A final re-scan found 034 only in this target worktree.

The forward migration retains `phone`, adds `sms` and terminal uncertainty, event SMS policy/time sensitivity/resolution, SMS preferences, versioned consent, durable acknowledgements, delivery binding/dispatch/escalation/segments/cost fields and queue/rate/ack indexes. Consent/acknowledgement tables use forced RLS with server-only grants. Binding invalidation and profile/event deletion cascades are covered; deletion also removes delivery-associated provider receipt rows. Full chain creation and forward reapplication succeeded on disposable PostgreSQL. No shared staging or production database was migrated.

## HTML email changes and skills actually applied

Installed skills were rescanned before HTML authoring and again before modifying the direct-mail shell. [Installed inventory](evidence/notifications/installed-skill-inventory.txt) and [exact selected paths, hashes and contributions](evidence/notifications/design-skills.json) record the gate. Identical aliases/provider duplicates count once; unrelated animation/video/game and other-brand campaign skills were not mechanically applied.

| Skill source | Contribution |
|---|---|
| `~/.agents/skills/react-email/SKILL.md` | Table layout, inline pixel styles, absolute PNG assets, system fonts, semantic HTML and plain-text twin; no React rewrite. |
| `~/.agents/skills/design-partner/SKILL.md` | Approved Rafii art direction, editorial hierarchy, restrained composition and actual render review. |
| `~/.agents/skills/frontend-design/SKILL.md` | Responsive spacing, typography and visual craft, restricted to email-safe CSS. |
| `~/.agents/skills/redesign-existing-projects/SKILL.md` | Preserve the working renderer, locale/CTA/Resend contracts and reuse a shared branded shell. |
| `~/.agents/skills/brandkit/SKILL.md` | Exact approved R/Rafii lockup, approved character, neutral identity and whitespace. |
| `~/.agents/skills/high-end-visual-design/SKILL.md` | Static editorial restraint and spacing only; motion/glass/web-font requirements excluded. |
| `~/.agents/skills/email-best-practices/SKILL.md` | Accessible email semantics, contrast, privacy-safe headers, unsubscribe and image degradation. |
| `~/.codex/plugins/cache/claude-cowork/design/1.2.0/skills/accessibility-review/SKILL.md` | Applicable WCAG 2 A/AA checks, semantic headline, decorative image alt and usable CTA. |
| Same plugin's `design-critique/SKILL.md` | Reviewed representative actual renders for hierarchy, calm critical content and blocked-image fallback. |
| Same plugin's `ux-copy/SKILL.md` | Plain Off/Important only consent, provider STOP status, escalation and quiet-hours explanation. |

The existing Python renderer remains. Template version is now `rafii-email/1.1.0`, up from 1.0.4. Every current Notification V2 and direct-mail HTML uses an email-safe table/inline-CSS translation of the approved 28px inverted R plus visible Rafii wordmark, and the approved `avatar-128.png` at a restrained 48px. No new logo was invented. The design follows `wordmark.tsx`, `rafii.css` and the v9 reference: neutral surfaces, editorial system-serif headline, generous spacing and one black primary CTA. Images are decorative; text wordmark, headline, message and CTA survive blocked images/style-block removal. No JavaScript, animation, glass, backdrop filter or critical external font is required.

HTML escaping, exactly one primary CTA, same-origin links, plain-text twin, existing localized V2 copy, applicable signed one-click unsubscribe, graceful dark fallback, delivery idempotency and Resend behavior remain. Direct English account/legacy copy remains in its current locale; automation names and arbitrary plan labels now stay in the body rather than subject/preheader.

Coverage derives from the actual catalogues: 25 V2 templates × 4 locales plus 13 existing English direct templates = 113 previews. Maximum current HTML size is **8,639 bytes**, below the 102 KB clipping budget. Chromium/WebKit × 600/375px × light/dark × images enabled/blocked+style degradation produced **1,808/1,808 passing cases**, with all applicable axe WCAG 2 A/AA rules, no overflow, one visible usable CTA, HTTPS links, visible headline/wordmark, approved character source, real local PNG resolution and a valid plain-text twin. This does not certify actual Gmail or Outlook clients.

## Screenshots and evidence

All representative families have EN/HK screenshots across both engines, light/dark and desktop/mobile; mobile also has degraded-image/style renders. The canonical [email-render.json](../site-agent/adaptive-social-coworker/evidence/email-render.json) contains every checked case; [email/index.json](../site-agent/adaptive-social-coworker/evidence/email/index.json) contains the generated catalogue. Representative images:

- [Approval required](../site-agent/adaptive-social-coworker/evidence/email-shots/chromium.light.600.images.approval_required.en.png)
- [Publish failed](../site-agent/adaptive-social-coworker/evidence/email-shots/chromium.light.375.images.publish_failed.zh-Hant-HK.png)
- [Reconnect required](../site-agent/adaptive-social-coworker/evidence/email-shots/webkit.light.600.images.channel_reconnect.en.png)
- [Security](../site-agent/adaptive-social-coworker/evidence/email-shots/chromium.dark.375.images.security_alert.en.png)
- [Digest](../site-agent/adaptive-social-coworker/evidence/email-shots/webkit.light.600.images.digest.en.png)
- [Weekly performance](../site-agent/adaptive-social-coworker/evidence/email-shots/chromium.light.600.images.weekly_performance.en.png)
- [Phone notification / image-blocked fallback](../site-agent/adaptive-social-coworker/evidence/email-shots/webkit.light.375.degraded.phone_call_failed.zh-Hant-HK.png)
- [Account → Notifications mobile](evidence/notifications/chromium.light.375.settings.png), [provider STOP state](evidence/notifications/chromium.stop-settings.png), [existing Phone browser regression](evidence/notifications/rafii-phone-browser.png).

## Actual local verification

[validation.json](evidence/notifications/validation.json) records commands, results, execution state and evidence. Full output is retained alongside it.

| Check | Actual result |
|---|---|
| Full Python unittest discovery | **1,496 passed**, 28.319s, exit 0. Includes Notification V2, Email, Push, Phone and 18 focused SMS methods. |
| Web contract/unit/locale tests | **387 passed**, 0 failed, exit 0. |
| Disposable PostgreSQL Notification V2/coworker | **35/35 passed**, including existing Push encrypted transport/revocation and actual digest deep-link acknowledgement. |
| Disposable PostgreSQL unified SMS | **7 passing groups**, including forward migration reapplication, forced RLS/server-only denial, cross-user isolation and deletion. |
| Existing Phone/Billing PostgreSQL | Both passed on clean individual clusters, exit 0. |
| Existing runtime/reference/campaign/deletion/quick-start PostgreSQL | Named regression groups passed; Agent style independently passed its 7 checks after shared-fixture collision was isolated. |
| Email render matrix | **1,808/1,808 passed**, no axe violations, overflow or asset/CTA/link failures. |
| Unified settings/Push acknowledgement browser | **Chromium and WebKit passed**: shared verification without SMS consent, explicit opt-in, masked identity, strong Push navigation cancellation, STOP state, Phone still enabled, mobile/desktop/light/dark, axe; zero call requests. |
| Existing Phone browser | Passed actual UI/SQL/fake Phone/Live/Manager flow, including second-draft save and web refresh, publish approval, hangup, schedule, revoke, mobile and applicable axe checks; zero real calls. |
| Existing Voice/phone-responsive/weather browser | **55/55 passed**, using local stand-ins. |
| Typecheck / lint / Next build | Passed; lint **805 files, 0 errors, 0 warnings**. Typecheck also passed after removing temporary dev-only tsconfig additions. |
| Product capability registry | Passed: 90 registered, 0 orphans, no James-leak findings; notification policy hash/version lock valid. |
| `git diff --check` / preservation | Passed; original dirty plan/handoff hashes and Phone backend preserved. |

Focused SMS verification covers: off defaults; verified/calling identity alone insufficient; explicit consent/current version; 10/30-minute Push-first queue timing; immediate no-Push Important texts; disabled escalation at egress after Push removal; acknowledgement/resolution/expiry; membership/permission changes; quiet hours/mute; serialized hourly/daily limits; event/delivery dedupe; separate `sms`/`phone`; deterministic localized copy/segment limits/same-origin links; fake accepted, delivered, failed and uncertain lifecycle; committed-marker crash recovery without resend; known rejection retry; signed STOP before/after consent and START without re-consent; replay; provider/cost fail-closed bounds; bounded cost/segment receipts; no plaintext in persisted rows/receipts; RLS and account cleanup.

Concrete failures found during verification were repaired: digest CTA incorrectly passed a string where the helper required a row; old Push URL expectations omitted the new reference; mark-all fixtures needed event IDs; switch label semantics hid the new accessible switch; and the existing Voice browser needed the installed psycopg Python on PATH. Intermediate diagnostic logs are retained and explicitly superseded by final passing logs. A shared-cluster Agent style fixture collision was confirmed by its clean isolated pass. The intermediate Phone invocation lacked `POSTRIFF_TEST_DSN`; its correctly configured isolated rerun passed.

**Additional offline secret scan:** exit 1, scanning 1,646 files, with one unexpected match at unchanged `src/postriff_phase2/phone/providers/fake.py:12`: the fixed non-production fake signing key. This is a reviewed pre-existing fixture false positive, not a discovered live secret or a finding introduced by this implementation. Phone code and the existing allowlist were deliberately preserved. [Exact redacted scan result](evidence/notifications/secrets.log).

## Limitations, real-provider prerequisites and unverified behavior

- No actual Gmail/Outlook client test, carrier delivery, real Twilio SMS/PSTN, customer Email/Push, native APNs/FCM or production behavior was exercised. Browser rendering and synthetic acceptance are identified as such.
- Before separately authorized real SMS use: configure server-only account/auth credentials, an approved SMS sender or Messaging Service, verified HTTPS public origin, exact signed status/inbound URLs, regional sender registration/provider opt-out configuration, conservative destination-aware cost estimates and positive per-segment/daily caps. Flags remain off by default. Existing Phone verification flags/service configuration are prerequisites for the shared verification flow.
- Provider segments/USD price are stored only when supplied as valid bounded numeric receipt fields; there is no live price/billing reconciler. The configured reservation covers unknown cost. Account deletion removes personal delivery rows, so queue accounting is not an immutable provider billing ledger.
- STOP/acknowledgement/resolution cancel dispatches that have not begun. An already started provider request cannot be recalled. Unknown acceptance deliberately needs reconciliation rather than automated resend.
- Regional STOP replies/START behavior and callback timing/field availability were verified with signed synthetic fixtures only. The app's inbound handler itself returns empty TwiML and sends no reply.
- Long configured origins that make localized copy exceed two segments fail closed. No raw phone number is collected by Notification settings; only Phone Mode owns verification/storage.
- No shared staging/production migration or secret change was performed. The additional unchanged fake-fixture secret-scan finding remains documented for its existing owner.
- The new backend requires migration 034 even with SMS flags off. A separately approved release must migrate its target schema before deploying this code; compatibility with an unmigrated Notification V2 schema is not provided.

Token Pilot continuity was resumed and maintained locally. Provider usage/cost attribution is unavailable because of session/project telemetry identity mismatch; usage, monetary savings and a no-Pilot baseline remain **unknown**, never zero or fabricated.
