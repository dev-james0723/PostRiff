# Adaptive learning contract (spec §9; architecture lock A1, P1)

## Global skills never change for one workspace

- Product skills are in `skills/` and classified in `skills/rafii-registry.json`. They are versioned and hashed, and are immutable at runtime.
- `SkillLibrary` and `skill_compiler` only read them. Nothing in the product writes a skill file.
- A content change without a version bump fails `scripts/rafii_skill_registry.py --check`.
- Workspaces personalise through overlays only.
- `skill_registry.validate_overlay` refuses any overlay aimed at a `protected` capability (every policy), or whose rule key names approval, publishing, permissions, billing, tenancy, security, rights, usage limits, budget, egress or consent, destructive actions, verification, HITL or proposals.

## Three kinds of memory

| Memory | What it holds | Where | Can change a draft's wording? |
|---|---|---|---|
| Voice | How the person writes: approved voice revision (`speaker`), learned `writing_preference` items, explicit voice notes | `state.speaker`, `state.learning`, `state.coworker.overlays.items` | Yes, within scope |
| Brand / content | Who the brand is: Brand Brain (`brandHub`), terminology, claims, explicit brand notes | `state.brandHub`, `state.coworker.overlays.items` | Yes, within scope |
| Strategy | What appears to work for this account | `pr_strategy_hypotheses` (migration 025) | **No.** It is never injected as identity or a rule. It is shown as a hypothesis, with sample sizes, and can only become an experiment by an owner's decision |

## Overlay item shape (the `coworker.overlays` view)

Each overlay item carries:
- identity and type: `id`, `memoryType` (voice or brand), `origin` (explicit or inferred), `kind` (note or learned), `source`;
- content: `statement`, and `scope {platform, language, contentTypeId, audience}`;
- status: `status` (active, paused, disabled, expired or retired);
- evidence: `evidenceIds`, `counterEvidenceIds`, `confidence` (0–1), `lastSupportedAt`, `expiresAt`;
- history: `replaces`, `since`, `revision`.

**Explicit vs inferred.**
- Explicit means the person said it: a note in the personalization page, a chat instruction or a setting. Explicit items have confidence 1.0 and never decay.
- Inferred means derived from behaviour: edit distance, accepted, rejected or ignored drafts, selected variants and images. These come through preference learning's consolidation (`learning_extract`): minimum support, a counter-evidence ratio and a 45-day half-life. An inferred item becomes active only after the owner accepts the proposal.

**Confidence of an inferred item.**
- It starts at `0.4 + 0.1 × support` (capped at 0.95).
- It is scaled down by the share of counter-evidence.
- It decays with a 90-day half-life from `lastSupportedAt`.
- An inferred item with no new support for 180 days is `expired`: it is not used, but it stays inspectable.

**Precedence.**
- Explicit outranks inferred.
- Within each, higher confidence comes first.
- When an explicit and an inferred item share the same rule key and scope, only the explicit one is used.

**Scope.**
- A platform-scoped item applies only when that platform is in the task. A LinkedIn preference never reaches Instagram.
- A language-scoped item applies only to matching locales.
- A content-type or audience scope applies only to that type or audience.

**Egress.** Overlays reach a cloud model only with the owner's cloud-memory decision (`memory.egress`). Otherwise the compiled context says they are withheld.

## Controls (all owner-level, audited, re-read and verified)

- **Inspect** (`GET coworker/overlays`): voice, brand and strategy, plus revisions and history.
- **Add or edit** an explicit note: `POST overlays/notes`, `PATCH overlays/notes/{id}`. Each edit bumps the item's revision and keeps the previous statement in the history.
- **Disable, enable or retire.**
  - For a note: `overlays/{id}/status`.
  - For a learned item: preference learning's own `update_version` (pause, resume or retire), so the writer's memory projection honours it. There is no parallel ledger.
- **Reset** (`overlays/reset`):
  - `notes` clears the explicit notes (the history is kept);
  - `learned` runs preference learning's `learning_reset`, which deletes that workspace's learning tables;
  - `all` does both.
  The global skills are untouched either way.
- **Export** (`GET overlays/export`): JSON of every item, its revision history and the hypotheses.

## Signals learned from

Preference learning's events (`pr_learning_events`: edited, update accepted, rejected with reasons, approved with edit distance, cancelled, published, chat instruction, proposal decided) cover:
- accepted, rejected and edited drafts, edit distance and rejection reasons;
- per-platform differences;
- campaign edits.

The Weekly Operator adds `accept`, `reject`, `redo` and `skip` per slot, recorded in the week's history. Engagement reply drafts are rows in `pr_reply_drafts` with `origin = copilot`, and their approval is the existing reply approval.

## Performance becomes hypotheses, never identity (`coworker/performance.py`)

**Inputs.** Only posts the application verified as published (job state `verified`) count, along with their `pr_metric_observations`. The comparison stays inside one cohort: the same provider, language, content type and metric definition version.

**Dimensions compared.**
- opening: question or statement;
- length: under or over 280 characters;
- CTA: present or absent;
- visual: image or text only;
- day: weekend or weekday;
- time: morning or later.

Day and time are read in the post's own scheduled time zone (`manifest.timing.timeZone`), not UTC.

**When a hypothesis is created.** Only when each arm has at least 5 measured posts and the medians differ by at least 20%.

**Confidence.**
- `high` needs n ≥ 20 per arm, a difference of at least 30%, and counter-evidence of at most a quarter of the posts.
- `moderate` needs n ≥ 10.
- Anything else is `low`.

**Wording.** Always "… may … for this account (… posts per group; not proven to cause it)".

**What is kept.** `causal = false` is enforced by a DB CHECK: a causal row is refused. Each hypothesis also keeps sample sizes, the date range, evidence and counter-evidence job ids, and an expiry 60 days after its last support. When the direction flips, the old hypothesis is `rejected` and a new revision replaces it.

**Guards.**
- Unavailable metrics are never zero.
- One viral post does not create a rule, because the medians are robust. This is tested.

**Owner decisions.** `experiment`, `dismissed` or `rejected`. None of them writes voice or learned preferences.

**Weekly summary and anomalies.** `analytics.weekly_ready` counts only posts published in the last 7 days and is not sent when there were none. `analytics.anomaly_detected` fires for a post from the last 7 days whose primary metric is at most a quarter, or at least four times, the median of at least 5 earlier measured posts in its like-for-like group; the message says one post is worth a look, not a pattern.

## Isolation

- Every overlay, hypothesis and learning row is keyed by workspace. The compiler receives exactly one workspace's state. There is no cross-user or cross-workspace learning. Tested: compiler cross-workspace test, PG O01, T01.
- Performance never infers sensitive personal attributes: its dimensions are about post form and timing only.
