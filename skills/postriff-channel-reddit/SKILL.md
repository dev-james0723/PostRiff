---
name: postriff-channel-reddit
description: Prepare and validate Reddit drafts and approval-gated controlled-browser publishing route with exact account, destination and format bindings.
metadata:
  version: 1.0.0
---

# reddit adapter

This adapter adds what is specific to reddit. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. A section below that repeats one of those headings overrides the contract for this channel only. Its variants use `platform` `Reddit`.

## 1. Channel purpose

Exact subreddit rules, flair, moderator notices and self-promotion disclosure.

## 2. Audience and expected language

Planning language: `en`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `reddit.post` | optional | `subreddit`, `title`, `rules_ref`, `flair`, `promotion_disclosure` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Exact subreddit rules, flair, moderator notices and self-promotion disclosure. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.

## 7. Browser fallback checkpoints

Use credential-safe user-action checkpoints for login, MFA, QR, CAPTCHA, consent, and secret-reveal steps. Browser observation may continue for non-secret page state and validation errors. Never read, copy, retain, or expose passwords, MFA codes, CAPTCHA responses, cookies, OAuth tokens, or client secrets. Require two post-auth identity signals, exact destination/native format, matching rendered copy/media, audience and timezone. Unknown landmarks or unexpected dialogs produce `ui_changed`.

A qualified browser record for the connected account requires both `signed_in_preferences_account_link` and `owner_profile_edit_controls_and_canonical_url`. Record the route as `controlled_browser` and the observed driver separately. The composer route is publish-ready only when a current non-mutating test also confirms `identity_reverified`, `composer_loaded`, `community_selector_present`, `title_and_body_fields_present`, and `semantic_post_control_present`. This readiness does not authorize a Post click. Computer or Chrome may execute a future post only after re-verifying the signed-in username and obtaining approval for the exact community, title, body, media, timing, derivatives, and final Post action.

## 8. Approval and safety rules

Draft and preparation results stay `draft_only`, with `publish_authorized=false`. Route readiness permits PostRiff to prepare an approved browser publication for that exact connected account; it does not grant standing publication approval. No cross-account expansion, engagement, account creation, paid call, or publication is implied. Every live post needs exact content-bound approval, an idempotency key, ambiguous-outcome reconciliation, and independent permalink verification. Preserve partial outcomes rather than claiming a campaign succeeded.
