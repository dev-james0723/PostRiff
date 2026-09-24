---
documentId: help_ts_awaiting_approval
sourceType: troubleshooting
title: A post has not published and is waiting for approval
summary: Waiting for approval is not a failure; nothing publishes until the exact post is approved.
routeFamilies: [queue, calendar, automations]
locales: [en]
productVersion: 2026.09
effectiveFrom: 2026-09-24
visibility: workspace
owner: product
topic: ts-awaiting-approval
keywords: [not published, didn't publish, waiting, approval, needs review, pending, 未發佈, 冇出, 等審批, 等批准]
---
# A post has not published and is waiting for approval

If a post never went out, first check whether it was ever approved. A draft or a review that is waiting is not a failed post.

## What you see

- In the Queue, a review marked "needs review" is waiting for someone with the approve permission.
- In Queue → Drafts, a draft that was never scheduled has no publish time at all.
- For an automation with the review policy, each post waits for approval before its publish time.

## What to do

Open the review in the [Queue](/app/queue), check the exact text, media, account and time, and approve it. If the publish time has already passed, the review window closed: prepare the draft again with a new time.

## Why Rafii waits

Silence never approves. A post publishes only after a person approves that exact version, or, for an owner's auto-publishing automation, only when every safety check passes.
