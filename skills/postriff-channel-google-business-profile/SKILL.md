---
name: postriff-channel-google-business-profile
description: Prepare and validate google-business-profile native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
---

# google-business-profile adapter

This adapter adds what is specific to google-business-profile. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Google Business Profile`.

## 1. Channel purpose

Exact business location and local relevance; Product Post is not a supported candidate here.

## 2. Audience and expected language

Planning language: `en`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `google-business-profile.update` | optional | `location_ref`, `cta` |
| `google-business-profile.event` | optional | `location_ref`, `title`, `start`, `end` |
| `google-business-profile.offer` | optional | `location_ref`, `title`, `start`, `end`, `terms` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Exact business location and local relevance; Product Post is not a supported candidate here. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.
