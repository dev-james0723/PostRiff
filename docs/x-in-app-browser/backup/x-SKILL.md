---
name: james-au-channel-x
description: Prepare and validate James Au's X drafts, or use the qualified free controlled-browser route for exact approved text posts and X-native scheduling.
---

# x adapter

## 1. Channel purpose for James

One central claim per post; preserve ordered thread sequencing.

## 2. Audience and expected language

Planning language: `en`, subject to the user's actual audience. Preserve James's real builder-musician angle; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `x.post` | optional | No extra fields |
| `x.thread` | optional | `sequence` |

## 4. Caption/title/description rules

Supply independently authored `copy` and any required title/description in `fields`. Do not invent personal experience or product facts. One central claim per post; preserve ordered thread sequencing. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.

## 5. Asset rules

Provide ordered `media` records with exactly `asset_ref`, `sha256`, `kind` and `alt_text`. Real bytes, rights, decoder checks, localization and visual review belong to the media-generation workflow. A static image cannot satisfy a video format. Consider the reviewed Guizang catalog for visual choices, preserving its reference-only/license gate. Optional derivatives require explicit selection first.

## 6. API setup requirements

The free route uses X's own web composer and native scheduler through Playwright. It makes no X API calls and needs no developer credits or paid API plan. The installed runtime is `/Users/ouxianxing/Documents/James-Au-Studio/src/james_au_social/x_browser.py`.

## 7. Browser fallback checkpoints

Use the dedicated profile under `~/Library/Application Support/JamesAuStudio/x-browser/chrome-profile`; never copy cookies from Codex or another browser. Login/MFA/CAPTCHA remain private handoffs. Require the authenticated account menu and exact own-profile link, then the `Post text` composer. Native scheduling uses `Schedule post`, labeled date/time controls, `Confirm`, the final `Schedule` control, and exact matching in `Scheduled posts`. Unknown landmarks produce `ui_changed`.

## 8. Approval and safety rules

Drafts stay `draft_only`. A browser submission requires a manifest hash bound to exact text, `@jamesaucreates`, public destination, and immediate or exact scheduled time. Persist `submitting` before the final click. After that click, an ambiguous result is `unknown` and must never be retried blindly. Replies, threads, media, engagement, account creation, paid calls, editing, deletion, and autonomous unapproved posting are outside this route.

## 9. Publish payload mapping

Run `python3 -B scripts/draft.py --input /absolute/path/draft.json` from this skill directory. Input requires exactly: `channel`, `native_format_id`, `account_ref`, `destination_ref`, `language`, `copy`, `media`, `fields`, `audience`. `channel` must be `x`. Native fields follow the table; extra fields are rejected. Optional `--output` creates a new local file exclusively and refuses overwrite.

Output maps these to an immutable-hashed manual handoff with ordered media and `native_fields`; it is **not an API request**. Module: `src/james_au_social/channel_adapters.py`. The project-root runtime is required until a portable candidate is installed. Missing runtime is a blocker, not permission to use an old version.

## 10. Verification checklist

Review exact account/destination, native surface, authored copy, audience, localization, and schedule. For an immediate post, reopen the exact `x.com/<handle>/status/<id>` permalink and match author and text. For a scheduled post, reopen X's native Scheduled posts queue and match exact text and time. Local preview or a click alone is not success. No live post was created during installation.

## Free Studio workflow

Open James Au Studio, choose X, then use **Free browser posting and scheduling**. Complete the one-time dedicated Chrome login, verify `@jamesaucreates`, enter exact text and optional schedule time, create the approval preview, and approve its hash. The browser only reaches the final Post or Schedule control after that exact approval.

## Portable runtime binding

This candidate embeds its exact Python runtime and focused tests under `runtime/` beside SKILL.md. Interpret project-root module/test commands above relative to this package's `runtime/`, not a temporary checkout or historical installed runtime. Channel `scripts/draft.py` automatically uses this copy. This package implements local workflows and draft handoffs only. It does not provide live transports, authenticated account connections or full V14 production acceptance.
