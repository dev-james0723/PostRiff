---
name: postriff-channel-x
description: Prepare and validate X drafts, or use the qualified free controlled-browser route for exact approved text posts and X-native scheduling.
---

# x adapter

This adapter adds what is specific to x. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. A section below that repeats one of those headings overrides the contract for this channel only. Its variants use `platform` `X`.

## 1. Channel purpose

One central claim in one post: shorter and sharper than the same idea on LinkedIn or Threads, never a clipped version of either.

## 2. Audience and expected language

Planning language: `en`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `x.post` | optional | No extra fields |
| `x.thread` | optional | `sequence` |

## 4. Caption/title/description rules

A PostRiff writing run returns one `x.post` per destination in `text`: a single post, not a thread. It must fit 280 characters by X's own count, the `characterLimit` the run sends: a CJK character or an emoji counts as two, a link as 23. Put the claim in the first line and cut everything that does not carry it: warm-up sentences, restated context, sign-offs and filler. At most one hashtag, and only when the person uses them. Do not invent personal experience or product facts. If the approved facts cannot be stated honestly within the limit, keep the strongest supported point, list what was left out in `unknowns`, and say so in `warnings`; never silently truncate. PostRiff drafts X posts for review, copy and export; it has no hosted X publisher, so a draft here is never a publishing promise.

## 6. API setup requirements

The free route uses X's own web composer and native scheduler through the companion's persistent browser session. It makes no X API calls and needs no developer credits or paid API plan. The companion owns the approval and idempotency ledger for that route; the hosted API never sees the session.

## 7. Browser fallback checkpoints

Reuse an existing `x.com` tab in the companion's controlled browser session, or create one there if absent. Never launch a separate Playwright Chrome/Edge profile and never copy cookies. Require the authenticated account menu and exact own-profile link before every write. Native scheduling uses `Schedule post`, labeled date/time controls, `Confirm`, the final `Schedule` control, and exact matching in `Scheduled posts`. Unknown landmarks produce `ui_changed`.

## 8. Approval and safety rules

Drafts stay `draft_only`. A browser submission requires a manifest hash bound to exact text, the exact connected account handle, public destination, and immediate or exact scheduled time. Persist `submitting` before the final click. After that click, an ambiguous result is `unknown` and must never be retried blindly. Replies, threads, media, engagement, account creation, paid calls, editing, deletion, and autonomous unapproved posting are outside this route.

## 10. Verification checklist

Review exact account/destination, native surface, authored copy, audience, localization, and schedule. For an immediate post, reopen the exact `x.com/<handle>/status/<id>` permalink and match author and text. For a scheduled post, reopen X's native Scheduled posts queue and match exact text and time. Local preview or a click alone is not success. No live post was created during installation.

## Controlled-browser route

Where the workspace has connected X through the desktop companion rather than the API, the companion reuses its signed-in browser tab, creates the exact approval hash, records the idempotency claim before the final click, and independently verifies the post or scheduled queue entry. The route makes no X API call and needs no paid API plan. It is available only to a workspace that has completed that connection; it is never assumed.
