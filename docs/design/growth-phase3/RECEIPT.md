# V3 Stage 3 — Radar

**Status: local candidate implemented and validated. Production remains off.**

Worktree: `/Users/ouxianxing/Documents/James-Au-Studio-v3-stage3`
Branch: `codex/rafii-v3-stage3-20260927`
Base: Phase 2 `38a3a06`
Scope: [V3 artifact](https://claude.ai/artifact/Rh24Gowc3Ni3xnVX9cGXcq), retained Stage 3 requirements. Original dirty checkout preserved.

Radar now supports Quick/Deep scan review and confirmation, durable bounded source/model batches, inspectable references, conservative ranking and confidence, approved-Genome For You, and reviewed ideas saved into the existing workflow. Home and navigation link to `/app/radar`. A paid owner may separately opt into a lightweight daily watch when its feature flag is enabled. YouTube native references stay outside AI and ranking.

A scan reserves its allowance before dispatch. Replays do not duplicate source work; abandoned leases remain unknown. A model timeout does not trigger another provider attempt. Each external attempt rechecks permissions. Credits refund when fewer than three useful opportunities remain; unknown costs stay explicit; provider overage cannot increase the confirmed customer charge. Source/model consent revocation purges scan evidence. Retention and a trusted deletion hook are implemented. Monitoring rotates workspaces fairly, observes quiet hours and deduplicates in-app results. No draft or publication is created automatically.

## Verified locally

- Python regression: **1,685 passed**; Radar unit tests include source rights, query identity, duplicate/injection filtering, supported Genome fit, synthetic release rejection, bounded native verification and expired price configuration.
- Frontend regression: **293 passed**; TypeScript, lint and production build passed, including `/app/radar`.
- Disposable PostgreSQL: real services/migration/transactions with deterministic providers and models. Covers permissions, quotes, replay, multiple saved ideas, revocation during dispatch, expired leases, partial results, wallet holds/refunds/overage, monitoring/quiet hours/subscription revocation, native deletion caps, stale Genome bindings, RLS and retention with discovery disabled. The final bounded-judgment and monitoring-fairness changes were checked with this focused suite after the broader regression run.
- Existing Phase 2 PostgreSQL regression passed.
- Browser: actual app and backend with disposable data; Quick/Deep, evidence review, desktop and mobile saves, For You empty state, reload and Home entry. Checked 1440px, 390px and 320px, dark theme and reduced motion. No serious/critical axe violations or page errors.
- Migration number 039 checked against 133 local/remote refs and the active worktrees; no other 039 migration was found.

[Validation record](evidence/validation.json) · [PostgreSQL evidence](evidence/pg.log) · [Browser evidence](evidence/browser-result.json)
[Desktop](evidence/radar-desktop.png) · [Mobile](evidence/radar-mobile.png) · [Dark](evidence/radar-dark.png)

## Release boundaries

No real model/search billing, customer messages, public posting, production migration, push, PR or deployment occurred. Source and model responses in tests are explicitly synthetic. New credit prices were not activated. The implementation has real official API adapters, but live credentials, current pricing, source rights and production deletion-event ingestion still need operational verification. Provider-specific unavailable sources are stated in [Operations](OPERATIONS.md).

**Real Precision@5, weekly draft adoption and actual provider economics remain NOT_ESTABLISHED.** [Release-gate result](evidence/release-gates.json). Synthetic testing cannot establish those product outcomes. `scripts/postriff_radar_evaluate.py` accepts an independently reviewed real dataset when one exists.

The local feature is ready for code review and a separately authorized rollout. See [Operations](OPERATIONS.md) for flags, allowances, retention, source readiness and launch gates. Token Pilot enrollment is local; its untracked `.claude/skills/token-pilot` symlink is excluded from the product commit.
