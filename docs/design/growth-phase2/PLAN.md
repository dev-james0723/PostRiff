# Rafii V3 Phase 2 — implementation contract

Source: approved [V3 plan](https://claude.ai/artifact/Rh24Gowc3Ni3xnVX9cGXcq), inspected 2026-09-27. User requested Phase 2 plus a less monotonous UI. Base is Phase 1 commit `8cf2351`, isolated in `codex/rafii-v3-phase2-20260927`. No Phase 3 Radar, live provider action, publishing, paid model call, push, deployment or production migration is included.

## Product changes

- Growth Studio combines three distinct views: publication field notes, audience topic cards, and creator calibration evidence. Warm paper, forest-green actions, peach/yellow accents, editorial type, a petal motif and restrained reduced-motion-aware transitions extend the Rafii visual system. Home, Analytics and Inbox link into the workflow. Existing Post Doctor and Genome panels adopt the same presentation.
- Postmortems compare frozen advice with native metrics in the same account/platform/language/format/window/definition cohort. Suggestions remain associations. Conflicting lessons cannot be approved. An owner explicitly adds a versioned lesson to Genome; limited lessons do not enter model memory as supported rules. Original publication evidence remains inspectable in Genome.
- Audience Miner uses already-collected authorized Threads comments on verified owned posts, in 7/14/30-day windows, up to 40 comments per run and two runs/day. Contact-pattern redaction precedes classification; sensitivity uncertainty withholds excerpts from synthesis. Category/account clusters carry exact evidence bindings. A reviewed suggestion creates an ordinary idea source, never a reply or publication. Instagram remains unavailable pending connector and platform review.
- Personal calibration uses at least 50 comparable frozen predictions with official 24h observations, a chronological 70/30 split and held-out Spearman >= .2. Thresholds and relative weights come only from training data. Approval/restore is versioned and owner-only. It remains separate from writing-quality calibration and becomes stale when its evidence snapshot changes.
- Genome import and audience analysis use bounded decisions over permitted IDs, preserving route grants, time budgets and actual attempt accounting. Deterministic selection is the safe default. There is no browser scraping or new autonomous action authority.

## Release evidence still required

Local fixtures establish behavior, not market efficacy. A real evaluation needs at least three passing dimensions in a >=50-post comparable cohort; a preregistered, account-randomized shown/withheld study over at least 28 days with a >=5 percentile point estimate; and at least 20% of distinct suggestions developed into content. Review uncertainty, exclusions and missingness before calling the experiment successful. No real accounts were enrolled here.

`scripts/postriff_growth_phase2_gate.py /outside-repo/evidence.json` checks an export and rejects inconsistent assignment or duplicate evidence. `execution: synthetic` can never pass the release gates. The audience API reports retained distinct suggestions used as draft sources; the denominator includes suggestions that were not saved. This rolling signal is not a causal experiment or a complete historical cohort.

## Operations

Additive migration `038_growth_closed_loop.sql`; all new tables force RLS with service-only privileges and workspace deletion cascades. Reports expire after 12 months; comment judgments/clusters and stored audience run bodies expire after 90 days. Existing comment collection retains its own policy. Consent changes invalidate retained derived audience results. All new features default off behind `POSTRIFF_GROWTH`, `POSTRIFF_POSTMORTEM`, `POSTRIFF_AUDIENCE_MINER`; existing Genome/Post Doctor flags still apply. Exact consent routes and explicit per-run confirmation are required. Unknown provider costs remain unknown.

Enabling production requires applying the migration in a reviewed release, real connector grants and platform review, configured model routes, owner consent and quota checks. YouTube preparation is a separate unsubmitted candidate in `YOUTUBE_AUDIT_CANDIDATE.md`.
