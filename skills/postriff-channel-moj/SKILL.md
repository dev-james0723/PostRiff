---
name: postriff-channel-moj
description: Prepare and validate moj native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
---

# moj adapter

This adapter adds what is specific to moj. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Moj`.

## 1. Channel purpose

Indian-language vertical video; independent job and audio rights, not a TikTok alias.

## 2. Audience and expected language

Planning language: `hi`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `moj.video` | video | `region`, `language_review_ref`, `sound_rights`, `cover_ref` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Indian-language vertical video; independent job and audio rights, not a TikTok alias. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.
