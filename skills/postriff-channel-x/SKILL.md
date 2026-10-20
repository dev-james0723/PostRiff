---
name: postriff-channel-x
description: Prepare X drafts and propose exact customer-approved actions through Rafii's official X API connector.
metadata:
  version: 2.0.1
---

# X adapter

Use platform `X`. X has a Direct-only contract: every account action requires an authorized official X API execution path. This X-specific rule overrides alternative route choices in `postriff-adapter-contract`; all non-conflicting shared requirements still apply.

## Drafting

Preserve the creator's factual claims and recorded voice. A single `x.post` has `text`; an `x.thread` draft has the first post in `text` and later posts in `nativeFields.sequence`. A draft is preparation, never authorization or proof of publication.

Drafting is never a publishing promise. Use the account's verified native constraints. Standard posts use a 280-weighted-character baseline; always apply the supplied account limit and URL/emoji rules; do not silently truncate or assume Premium features. Keep qualifications and attribution. Do not invent personal experience.

## Connection and capability checks

Connect and reconnect through Rafii's official OAuth 2.0 flow with PKCE. Use the authenticated workspace's selected connection. Read the server capability catalogue for the exact operation, granted scopes, application entitlement, implemented handler and cost admission.

If X restricts an operation, display `Unavailable — X API restriction` and the documented reason. If Rafii lacks an implementation or current verification, state that actual limitation. Never present a missing implementation as an X prohibition.

Do not offer or execute X Assisted, Manual or browser publishing, native browser scheduling, cookie reuse or companion submission. A failed API request does not authorize another route.

## Customer approval and execution

An Agent can inspect the connection and propose a precise operation. It cannot approve its own proposal. The customer reviews the exact connected account, content, targets, media, timing and cost estimate in Rafii and explicitly approves the immutable request digest.

Rafii's durable queue dispatches approved scheduled work through the official API. Scheduling is a Rafii queue capability; do not claim an organic native X scheduling API. Likes and follows require direct user intent and must not become unattended bulk actions.

Bind execution to the workspace, account, current authorization generation, current customer permission and approved request. Reconnect, disconnect, cancellation or permission changes invalidate affected queued authority. Use durable cost admission before every billable request; a request counter is not a guaranteed invoice ceiling.

## Media approval

Propose `media.upload` with an existing workspace `asset_id` and optional `alt_text`. The customer approves that exact upload separately from the post. Only completed, unexpired, same-account media receipts can be attached; never accept an arbitrary media ID or remote URL as ownership evidence. The server needs explicit current upload price ceilings, not an assumed free transfer. A partial or uncertain upload does not authorize a retry or a post.

## Results

Report a provider receipt only after a real X API response with a validated operation-specific result. For published posts, reconcile the returned ID with the authorized account and approved content through an official read.

An ambiguous write stays uncertain. Do not blindly retry, fabricate an ID or convert a preview into a successful result. Preserve partial thread and media outcomes. Report missing analytics fields as unavailable or unknown.

## Native content formats

These are local draft schemas. Publishing requires the exact Direct workflow, account authorization and explicit customer approval.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `x.post` | optional | No extra fields |
| `x.thread` | optional | `sequence` |
