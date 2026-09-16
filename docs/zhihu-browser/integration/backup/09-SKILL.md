---
name: james-au-social-orchestrator
description: Use when starting or operating the James Au social suite, including first-run channel onboarding, research, content generation, scheduling, publishing, verification, or analysis.
license: MIT
metadata:
  status: v14-first-run-update-candidate
  project-contract: james-au-social-media-suite-design-revision-14
---

# James Au social orchestrator

Use this as the suite entry point. Load the bundled James Au Social Content Engine first; if it is missing, stop with `missing_brand_dependency`.

Read [references/routing-and-safety.md](references/routing-and-safety.md) when routing a request or interpreting execution state.

## First invocation

Check the durable onboarding state before assuming any account is connected. If no state exists, run `scripts/first_run.py` with an owner-only store and ask exactly the single question it returns. The flow must confirm the batch identity, freeze a selected-channel snapshot, offer Codex automation or `Not now`, and record the intended operation level. A recommended email is not a confirmed identity. `Select all 33` means assessment only.

An `assessment_ready` result triggers read-only inventory of the selected channels. Load `james-au-api-setup-wizard`, `james-au-security-and-approval`, the relevant channel adapters, and `james-au-browser-auth-and-session` only when needed. Show an exact setup manifest before any provider mutation. Ask for approval scoped to its hash, actions, identities, scopes, costs, and handoffs.

After approval, complete only the listed reversible non-secret setup work. Pause in `private_handoff` for login, OAuth consent, MFA, QR, CAPTCHA, passkeys, legal, billing, or secret-bearing steps. Resume only after the user closes the sensitive surface. Require two independent identity signals, then a separate exact test-publish approval and independent verification before calling a channel `ready`.

An automation answer creates a candidate recipe and representative dry run only. Do not create a heartbeat, cron job, account connection, schedule, or publish authorization until the later activation approval. `Not now` creates nothing and is not asked again for that completed first-use flow.

## Normal operation

Identify setup, content generation, scheduling, publishing, verification, or analysis. Ask only the next blocking question and retain known answers. Build one canonical brief, then route only to selected, eligible adapters. Keep source speech, verified facts, James's view, platform drafts, media, approval, execution, and verification states separate. Report partial results per channel.

## Hard boundary

An installed wrapper does not activate a provider or connect an account. Never read raw credentials or cookies. Never create an account/app, submit consent, spend money, render remotely, upload, schedule, publish, delete, retry an ambiguous write, or report live success without the exact current gate and independent evidence required by V14.
