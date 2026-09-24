---
documentId: help_ts_automation_not_publishing
sourceType: troubleshooting
title: An automation did not publish
summary: Policy, approval, capability and ownership reasons an automation's post stayed a draft.
routeFamilies: [automations, queue]
locales: [en]
productVersion: 2026.09
effectiveFrom: 2026-09-24
visibility: workspace
owner: product
topic: ts-automation
keywords: [automation, didn't publish, not posted, skipped, draft only, auto publish, 自動化, 冇出, 冇發佈, 跳過]
---
# An automation did not publish

Ask Rafii "why wasn't the Friday post published?" to get the answer from the automation's own run history. Common reasons:

## The policy only prepares drafts, or waits for review

A drafts-only automation never publishes; a review automation waits for your approval of each post before its publish time. An approval after the publish time is refused as expired.

## The owner has not allowed auto-publishing

Auto-publishing starts only after an owner allowed it for that exact automation. If the automation changed, or the owner who allowed it is no longer an owner, its posts wait for approval.

## A safety check failed

An auto post is published only when its draft has no unknown details, every warning can be acknowledged automatically, its sources are covered, any quote is verified, the text fits the platform and Instagram has an image. Otherwise the post waits for review with the reason.

## The platform cannot publish here

X and Xiaohongshu have no publishing connection yet, and a disconnected or unreviewed account cannot publish. See [Capability levels](/app/help/help_capability_levels).

## The run was skipped

A run whose publish time passed while Rafii was down is skipped rather than drafted late, and a run over its cost limit is held.
