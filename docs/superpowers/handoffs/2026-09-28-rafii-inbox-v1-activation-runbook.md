# Rafii Inbox v1 activation runbook

Status: source candidate. No production activation is implied by this document.

## Scope and support

Inbox v1 covers comments and individually approved replies on verified Threads connections. It does not cover DMs, mentions, Instagram comments, bulk moderation, or cross-platform identity. A connected account is not sufficient evidence for Inbox Direct; the account must have current `comments_read` or `reply` Direct capability, a usable credential, and reviewed Threads provider configuration.

The source has three separate switches, all empty/off by default in `.env.example`:

- `RAFII_ENGAGEMENT_COPILOT_ENABLED`: existing deterministic triage appears in Inbox; the existing AI writer can suggest a draft.
- `RAFII_INBOX_SYNC_ENABLED`: the hosted cron selects at most two due Threads connections per tick and calls the same bounded refresh used by the manual button. The manual button does not require this switch.
- `RAFII_INBOX_REPLY_SEND_ENABLED`: the hosted worker may claim only new or explicitly reconfirmed exact approvals. Leave off until the separate live mutation approval.

Migration `047_inbox_operational_sync.sql` adds durable sync state, permalink and reply dispatch fields and allows `held` receipts. It is additive and must go through the normal production migration gate. No migration was applied to production by this implementation handoff.

## Staging and read-only validation

1. Merge reviewed source while the reply send switch stays off.
2. Apply migration 047 through the normal release gate, verify forced RLS and service-role access, and compare the deployed SHA to the reviewed commit.
3. In a separately authorized preview/staging environment with a reviewed Threads app and a test account, verify `comments_read` Direct, the exact account identity, granted scopes, and the previous publish/analytics levels after reconnect. Do not infer support from connector presence.
4. Use **Check for new comments** on one known published Threads post. Confirm `lastSyncAt` comes from server data, 429/provider errors show unavailable, repeated pages do not duplicate comments, and deleted/absent comments are not tombstoned without proof.
5. If read-only results are correct, enable `RAFII_ENGAGEMENT_COPILOT_ENABLED` in staging. Check Needs reply, Review and FYI; suggestions must save drafts and never send. Verify spam/abusive comments have no default AI suggestion.
6. Enable `RAFII_INBOX_SYNC_ENABLED` in staging only after manual refresh is stable. Inspect provider rate limits, due selection, overlap cooldown and sync receipts. Disable it on abnormal load or repeated errors.
7. Keep `RAFII_INBOX_REPLY_SEND_ENABLED` off. Confirm an approval records `requiresReconfirmation=true` and no provider POST occurs.

## Separately approved live reply activation

These steps require explicit owner approval for the target account, exact reply content, provider access and live social mutation. This implementation handoff does not grant it.

1. Confirm the production migration, current capability and app-review evidence, error monitoring and rollback switch.
2. Enable `RAFII_INBOX_REPLY_SEND_ENABLED` for the controlled environment.
3. Reopen one previously approved but unsent reply, show the saved exact manifest and reconfirm it. Old approvals do not replay automatically.
4. Observe one fenced worker claim, `submitting` receipt before provider I/O, provider container/publish result, and an authoritative read-back before calling the reply verified.
5. Inspect duplicate attempts and worker errors. A crash or inconclusive provider result stays `uncertain` and must not be automatically resent. Disable the send flag immediately on an anomaly.

## Rollback and limits

Turning off the send switch stops new claims; already `submitting` operations are never blindly retried. Turning off scheduled sync leaves manual refresh available. Turning off engagement hides triage but preserves comments and receipts. Do not reverse the additive migration to roll back an app release; retain historical replies and sync evidence.

Threads reply read-back checks the exact provider reply id, parent comment, text and owner. If the bounded first page does not prove the reply, the receipt remains `submitted`; absence from that page is not failure or permission to resend. Provider deletion is not inferred from an incomplete page or transient error. Push/email engagement delivery follows existing notification preferences and is not activated by this runbook.
