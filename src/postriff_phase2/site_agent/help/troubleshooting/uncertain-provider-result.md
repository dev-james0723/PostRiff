---
documentId: help_ts_uncertain_result
sourceType: troubleshooting
title: A publishing result is uncertain
summary: The provider did not confirm; do not post again until it is reconciled.
routeFamilies: [queue, calendar]
locales: [en]
productVersion: 2026.09
effectiveFrom: 2026-09-24
visibility: workspace
owner: product
topic: ts-uncertain
keywords: [uncertain, not confirmed, unknown, reconcile, duplicate, posted twice, 唔確定, 未確認, 重複]
---
# A publishing result is uncertain

"Uncertain" means Rafii handed the post to the provider but the provider did not confirm what happened.

## What Rafii does

Rafii reconciles with the provider before it ever retries, so nothing is posted twice. The job keeps its provider reference and every attempt in its timeline.

## What you should do

Do not resubmit or post the same text by hand yet. Open the job in the [Queue](/app/queue) to see its timeline. Check the account on the platform itself: if the post is there, it will be marked verified once reconciled. If it stays uncertain, contact support with the job's details; do not start a new approval of the same post.
