---
name: postriff-channel-discord
description: Prepare and validate discord native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
---

# discord adapter

This adapter adds what is specific to discord. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Discord`.

## 1. Channel purpose

Exact server/channel/forum context; no mass mentions or announcement crosspost by default.

## 2. Audience and expected language

Planning language: `en`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `discord.message` | optional | `guild_ref`, `channel_ref`, `allowed_mentions` |
| `discord.forum_post` | optional | `guild_ref`, `channel_ref`, `title`, `allowed_mentions` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Exact server/channel/forum context; no mass mentions or announcement crosspost by default. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.
