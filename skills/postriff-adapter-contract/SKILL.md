---
name: postriff-adapter-contract
description: The shared contract every PostRiff channel adapter inherits — asset rules, setup, browser fallback, approval and safety, draft payload mapping, and verification. Bound once per turn alongside whichever channel adapters the turn uses.
metadata:
  version: 1.0.0
---

# Channel adapter contract

Every `postriff-channel-*` adapter inherits this contract. An adapter adds what is
specific to its channel — purpose, audience and language, native formats, and
caption rules — and may override a section below by repeating its heading. An
override applies to that channel only; every other channel in the same turn still
follows the contract.

## 5. Asset rules

A writing run describes media; it never supplies it. In the variant's `notes`, name the media the native format needs, its intended source (real photo, screenshot, video frame or designed graphic) and useful alt text. The asset itself is attached when the user reviews the variant, and real bytes, rights, decoder checks, localization and visual review belong to the media workflow. Media that does not exist yet is an `unknowns` entry. A static image cannot satisfy a video format. Consider the reviewed Guizang catalog for visual choices, preserving its reference-only/license gate. Optional derivatives require explicit selection first.

## 6. API setup requirements

Use the API setup wizard for this exact account, destination and operation. Check current official documentation and permissions, then approved provider, controlled browser or manual handoff. No credentials or API endpoints are bundled here. A successful setup plan does not establish authorization; do not invent or call undocumented endpoints.

## 7. Browser fallback checkpoints

Use a dedicated profile and secret-blind private handoff for login/MFA/QR/consent. Require two post-auth identity signals, exact destination/native format, matching rendered copy/media, audience and timezone. Unknown landmarks or unexpected dialogs produce `ui_changed`. The current adapter contains no qualified browser selectors or final-submit action.

## 8. Approval and safety rules

Every result stays `draft_only`, with `publish_authorized=false`. No cross-account expansion, engagement, account creation, paid call or publication is implied. A future live route needs its own current qualification and exact content-bound approval. Preserve partial outcomes rather than claiming a campaign succeeded.

## 9. Draft payload mapping

Return the draft inside the run's output schema; this skill never issues an API request. The schema is authoritative and rejects extra fields: if it names a field differently from this section, follow the schema. Each variant carries `platform` (the destination's platform name), `language`, `text`, `sourceIds`, `unknowns` and `notes`; the run carries `warnings`.

- `text` is audience-facing copy and nothing else.
- A title, description, ordered slide text or other native field the format requires goes in `notes`, labelled (for example `Title: …`), never in `text`. The exception is a channel whose adapter says its title opens `text` (Xiaohongshu): there the title is the first line of `text`.
- `sourceIds` lists only the approved sources the text actually relies on.
- Anything the draft needed but did not have is an `unknowns` entry, kept out of `text`.

PostRiff resolves the adapter, current character limits and the channel's capability level through its hosted runtime (`src/postriff_phase2/channels.py`, `contracts.py`). A returned variant is a proposal: it becomes a scheduled job only through `review` and `approve_many` once the user approves the plan. Missing capability or limit data is a blocker, not permission to assume a value.

## 10. Verification checklist

Review exact account/destination, native surface, authored copy, ordered media, audience, source/rights, localization and current format constraints. After a separately approved manual publication, independently reopen the correct native surface and record matching post ID/permalink, rendered content and live/scheduled state. A local handoff, upload acknowledgment or wrong surface cannot count as publication. No live verification has been performed by this package.

## PostRiff runtime binding

PostRiff runs the adapter server-side; this package ships instructions only and bundles no Python, credentials or transport. Where a step above names a module, read it as the hosted equivalent in `src/postriff_phase2/` and report `runtime_dependency_missing` when the host does not expose it. Local draft handoffs are the whole scope: live transports, authenticated account connections and production acceptance belong to the connected-channel workflow and its own approval gate.
