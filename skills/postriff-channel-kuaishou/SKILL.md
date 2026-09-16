---
name: postriff-channel-kuaishou
description: Prepare and validate kuaishou native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
---

# kuaishou adapter

This adapter adds what is specific to kuaishou. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Kuaishou`.

## 1. Channel purpose

Mainland short-video creator surface; never inherit Douyin qualification.

## 2. Audience and expected language

Planning language: `zh-Hans`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `kuaishou.video` | video | `creator_ref`, `cover_ref`, `sound_rights` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Mainland short-video creator surface; never inherit Douyin qualification. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.
