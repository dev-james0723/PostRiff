---
documentId: help_queue
sourceType: workflow_playbooks
title: Queue and drafts
summary: Drafts waiting to be scheduled, posts waiting for approval, and jobs with their receipts.
routeFamilies: [queue, calendar]
locales: [en]
productVersion: 2026.09
effectiveFrom: 2026-09-24
visibility: workspace
owner: product
topic: queue
keywords: [queue, drafts, schedule, job, waiting, in flight, held, verified, cancel, 佇列, 排隊, 草稿, 排程, 取消]
---
# Queue and drafts

The [Queue](/app/queue) has two tabs: Queue (approvals and jobs) and Drafts (everything not scheduled yet).

## Drafts

The Drafts tab holds every draft that is not scheduled yet: from Home, conversations and automations. Schedule… picks the account and time and prepares the exact post for approval. Set-aside drafts stay at the bottom of the list; editing one brings it back.

## Who does what

Preparing a review, approving it and cancelling a job need the approve permission. When a draft has a newer version waiting or unknown details to confirm, someone who can edit drafts does that first.

## Job states

Waiting → in flight → verified.

- Waiting: approved and not with the provider yet. It can still be cancelled.
- In flight: the worker handed the post to the provider.
- Uncertain: the provider did not confirm. Rafii reconciles before it ever retries, so nothing is posted twice.
- Held: something changed after approval; nothing publishes from a held job.
- Verified: the provider confirmed the post was published.
- Failed or cancelled: the job ended, with the reason it stopped.

## Cancelling

Hold to cancel a waiting or held job before the provider has it. Once a post is submitted, a cancel cannot recall it; the job is reconciled instead.

## Daily limits

Each account has a daily limit on approved posts (for example 150 for LinkedIn, 250 for Threads and 100 for Instagram). A held job counts toward it until it is cancelled.

## Receipts

Open any job for its timeline, every attempt and exactly what the provider confirmed.
