---
name: postriff-channel-dcard
description: Prepare and validate dcard native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
---

# dcard adapter

This adapter adds what is specific to dcard. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Dcard`.

## 1. Channel purpose

Taiwan board-specific contribution, genuine identity and disclosure; no fabricated anonymous story.

## 2. Audience and expected language

Planning language: `zh-Hant`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `dcard.post` | optional | `board_ref`, `title`, `rules_ref`, `identity_mode`, `affiliation_disclosure` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Taiwan board-specific contribution, genuine identity and disclosure; no fabricated anonymous story. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.
