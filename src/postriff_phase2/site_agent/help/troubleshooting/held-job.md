---
documentId: help_ts_held_job
sourceType: troubleshooting
title: A scheduled post is held
summary: Something changed after approval, so the post needs a new review.
routeFamilies: [queue, calendar, channels]
locales: [en]
productVersion: 2026.09
effectiveFrom: 2026-09-24
visibility: workspace
owner: product
topic: ts-held
keywords: [held, on hold, stopped, blocked, paused post, 暫停, 擱置, 卡住, 被停]
---
# A scheduled post is held

A job is held when something changed after approval: the approver's permission, the draft, its sources or voice, the account's connection, the plan, or the approval window closed.

## What it means

Nothing publishes from a held job. It still counts toward the account's daily limit until it is cancelled.

## What to do

1. Open the job in the [Queue](/app/queue); its last event says what changed.
2. Fix the cause, for example reconnect the account on [Channels](/app/channels).
3. Prepare the draft again from [Queue → Drafts](/app/queue?view=drafts) and approve the new review.
4. Cancel the held job so it stops counting toward the daily limit.
