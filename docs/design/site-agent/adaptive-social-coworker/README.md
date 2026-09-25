# Rafii Adaptive Social Coworker

This work implements `../RAFII_ADAPTIVE_SOCIAL_COWORKER_ENGINEERING_SPEC_2026-09-24.md`. It sits on top of the site agent (`../README.md`) and Agent Runtime v2 (`../agent-runtime/`), and preserves both.

| Document | What it is |
|---|---|
| [ARCHITECTURE_LOCK.md](ARCHITECTURE_LOCK.md) | WP0: repository facts, concurrency lock, package layout, decisions, deviations, migrations |
| [capability-ledger.json](capability-ledger.json) | Machine-readable James → Rafii migration ledger plus the capability inventory |
| [JAMES_MIGRATION_AUDIT.md](JAMES_MIGRATION_AUDIT.md) | What was generalised, excluded, deduplicated, or turned into tools and policies; the leak gate |
| `../../../../skills/rafii-registry.json` | The capability registry (single source of truth) |
| [API.md](API.md) | HTTP contract for notifications, push, weekly, research, source → campaign, overlays, performance, listening, engagement, attention, growth |
| [NOTIFICATIONS.md](NOTIFICATIONS.md) | Notification architecture, preference contract, delivery semantics, HTML email, Resend and deliverability runbook, Web Push architecture and runbook |
| [NOTIFICATION_CATALOG.md](NOTIFICATION_CATALOG.md) | Generated: every event with its defaults, and every email template's subject and preheader |
| [ADAPTIVE_LEARNING.md](ADAPTIVE_LEARNING.md) | Overlays (voice, brand, strategy), explicit vs inferred, evidence, confidence, decay, controls, performance hypotheses |
| [RESEARCH_AND_CAMPAIGNS.md](RESEARCH_AND_CAMPAIGNS.md) | Research Broker, provenance contract, FactPack, One Source → Full Campaign |
| [WEEKLY_OPERATOR.md](WEEKLY_OPERATOR.md) | Recipe, week, state machine, cycle, truthfulness |
| [ROLLOUT.md](ROLLOUT.md) | Flags, rollout order, rollback |
| [TEST_MATRIX.md](TEST_MATRIX.md) | Every requirement mapped to its test and command |
| [HANDOFF.md](HANDOFF.md) | Status, evidence, blockers, next action |
| [INTEGRATION.md](INTEGRATION.md) | The local integration with the Agent Runtime onto `consumer-saas`: commits, resolutions, verification |
| [`../../../postriff-migration-numbering.md`](../../../postriff-migration-numbering.md) | Migration number reservations, inventory, apply order, ai-routing checklist |
| `evidence/` | `verification.json` (generated), `pg-coworker.json`, `email-render.json`, email previews and screenshots |
