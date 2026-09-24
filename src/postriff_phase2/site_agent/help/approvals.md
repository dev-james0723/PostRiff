---
documentId: help_approvals
sourceType: workflow_playbooks
title: Exact approvals
summary: Why approving freezes the exact post, and what a digest and a receipt are.
routeFamilies: [queue, calendar, agent]
locales: [en]
productVersion: 2026.09
effectiveFrom: 2026-09-24
visibility: workspace
owner: product
topic: approvals
keywords: [approve, approval, review, digest, manifest, receipt, publish, 審批, 批准, 審核, 發佈, 收據]
---
# Exact approvals

Rafii publishes only posts that a person with the approve permission approved exactly as they will go out.

## What a review contains

A review freezes the text, the media (by hash), the account, the capability level and the time into a manifest with a digest.

## Approving

Approving that digest is the only way a post enters the queue. Changing anything (text, media, account, time) needs a new review. The same draft prepared twice for the same account and time is the same post: once one review is approved, the other schedules nothing.

## Approving one version is not approving the next

If the draft, its sources, the voice profile or the account's connection changes after approval, the job is held and needs a new review. An approval never carries over to a later edit.

## Receipts

Every publication records the provider's reference and confirmation. Uncertain outcomes are reconciled before any retry; do not resubmit an uncertain publication.

## Chat is not approval

A plan card, a preview or a "yes" typed to Rafii does not approve anything. Approving happens on the review itself, in the [Queue](/app/queue) or on a plan card's approve step, and it is recorded.
