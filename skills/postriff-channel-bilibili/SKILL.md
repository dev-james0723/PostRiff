---
name: postriff-channel-bilibili
description: Prepare and validate bilibili native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
---

# bilibili adapter

This adapter adds what is specific to bilibili. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Bilibili`.

## 1. Channel purpose

Music and software experiments with community context and useful depth.

## 2. Audience and expected language

Planning language: `zh-Hans`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `bilibili.video` | video | `title`, `description`, `cover_ref`, `category` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Music and software experiments with community context and useful depth. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.
