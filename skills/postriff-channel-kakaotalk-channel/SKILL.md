---
name: postriff-channel-kakaotalk-channel
description: Prepare and validate kakaotalk-channel native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
---

# kakaotalk-channel adapter

This adapter adds what is specific to kakaotalk-channel. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `KakaoTalk Channel`.

## 1. Channel purpose

Exact Kakao Business Channel product; ordinary user Message API is not authorization.

## 2. Audience and expected language

Planning language: `ko`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `kakaotalk-channel.message` | optional | `business_channel_ref`, `sender_profile_ref`, `template_ref`, `consented_audience_ref` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Exact Kakao Business Channel product; ordinary user Message API is not authorization. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.
