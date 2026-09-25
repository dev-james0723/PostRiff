# Feature flags, rollout and rollback

Flags are defined in `src/postriff_phase2/coworker/flags.py`. They use the same rules as `agent_runtime_v2/config._flag`:
- a flag is off unless its value is `1`, `true`, `yes` or `on`;
- values are read from the hosted app's isolated environment;
- the browser learns them only through `GET …/coworker/status`, never through `NEXT_PUBLIC_*`.

With every flag off, the coworker features do nothing:
- the legacy emails are unchanged;
- the writer binds the same set of skills (with the flag on it adds the Humanizer packs and the active workflow's skill);
- the cron's coworker step returns `{"status": "disabled"}` without building anything;
- the routes answer `404 feature_disabled`.

| Flag | Turns on | Egress | Preview |
|---|---|---|---|
| `RAFII_SKILL_REGISTRY_V2_ENABLED` | The writer adds the Humanizer packs by language and the active workflow's skill. Agent instruction hooks add compiled knowledge. Trace provenance includes overlay revisions. | none new | allowed |
| `RAFII_NOTIFICATIONS_V2_ENABLED` | Events, the planner, deliveries, the centre, HTML email, the digest, the provider webhook. Legacy senders route v2-owned kinds to it. | Resend (existing processor) | **refused** |
| `RAFII_WEB_PUSH_ENABLED` | The push opt-in, subscriptions and the push channel. It also needs the VAPID keys and notifications v2. | browser push services (FCM, Mozilla, Apple, WNS) | **refused** |
| `RAFII_ADAPTIVE_SKILLS_ENABLED` | The personalization page and controls, and the `overlay_context` tool | none | allowed |
| `RAFII_WEEKLY_OPERATOR_ENABLED` | Recipes, week plans, the review page, the cron preparation, Source → Campaign (text inputs) | the writer route (existing) | allowed |
| `RAFII_RESEARCH_BROKER_ENABLED` | The research tools, URL sources, research evidence | Exa, Jina (existing processors; the owner's research consent is still needed) | **refused** |
| `RAFII_CREATIVE_AGENT_ENABLED` | Creative plans (deterministic) and the `creative_plan` tool | none (image generation stays the runtime's own flag and ledger) | allowed |
| `RAFII_PERFORMANCE_LEARNING_ENABLED` | Hypotheses, the cron refresh, `analytics.weekly_ready` | none | allowed |
| `RAFII_LISTENING_ENABLED` | Watchlists and opportunities (through the broker) | Exa, Jina | **refused** |
| `RAFII_ENGAGEMENT_COPILOT_ENABLED` | Triage and suggested-reply drafts. Sending is still the existing approved reply path. | none | allowed |
| `RAFII_GROWTH_EXPERIMENTS_ENABLED` | Experiment assignment and exposure logging | none | allowed |

`deployment.isolated_environment` refuses a preview whose egress flags are on, and pins `RESEND_WEBHOOK_SECRET`, `POSTRIFF_VAPID_PRIVATE_KEY` and `POSTRIFF_NOTIFICATION_SIGNING_KEY` in the staging secret-fingerprint set. That stops a preview from inheriting production values.

**What ships whatever the flags say.** These parts are not flag-gated, so turning flags off does not undo them:
- the de-personalised `skills/postriff-*` text (for example `human-voice-pass.md` no longer carries one person's voice anchor), with the version bumps listed in `JAMES_MIGRATION_AUDIT.md`. Every writer run records the new skill versions and hashes;
- `SkillLibrary.load` refusing skills without a `postriff-` or `rafii-` prefix, and the hosted bundle excluding `skills/james-au-*`;
- the widened `pr_reply_drafts` origin check and the new tables (unused while their flags are off).
- account deletion also removes the person's rows from the 024/025 tables (push subscriptions, notification preferences, deliveries, person-scoped events, product events, experiment assignments), whatever the flags. **So 024 and 025 must be applied to a database before this code is deployed against it**; otherwise account deletion fails and rolls back.

Rolling those back means reverting the `skills/postriff-*` changes (and `skills.py`), not a flag.

## Order (each step needs owner authorization; none has been done)

1. **Migrations.** `024_notification_core.sql` and `025_coworker_evidence_growth.sql` are forward-only and idempotent. They have only run on local disposable databases.
   - `scripts/postriff_migrate.py --apply-local` refuses a non-local host, and its docstring reserves remote execution for the separately reviewed runner. Staging and production use that reviewed runner (or the owner's reviewed procedure), never this script.
   - `postriff_migrate.plan` refuses a database whose ledger has migrations the running branch lacks. So 024/025 go to a shared staging database only after this branch is merged or rebased into every branch that deploys there; otherwise those branches can no longer migrate.
   - Re-check numbering first: `raffi/launch-final` holds 020–022 and `ai-routing` holds 020–023 (not in this branch).
   - Production comes only after staging is verified.
2. **Registry v2, adaptive skills, creative, performance, growth.** Turn these on in staging; they have no new egress. Watch the writer's recorded `skillOmissions` for budget pressure.
3. **Notifications v2.** Staging first, with the Resend webhook configured and the DNS health check passing (see NOTIFICATIONS.md). Then an owner-only production cohort. Watch `operations.counts.notificationBacklog` and `notificationDead24h` in the cron log.
4. **Weekly Operator.** An owner cohort first. It drafts with the workspace's writer and budget. Watch `weekly_plan.ready`, `weekly_plan.reviewed` and the draft approval rate.
5. **Web push.** After notifications v2 is stable, and after VAPID keys are generated and stored.
6. **Research broker and listening.** Only for workspaces whose owner has already given research consent.
7. **Growth experiments.** The positioning A/B (`positioning_2026_10`), with deterministic 50/50 assignment. Decide from `trial_to_paid` and 30/60/90-day paid retention by arm (`scripts/rafii_growth_report.py`, read-only, which reports the definitions with the numbers), not from generation volume.
   - **PARTIAL:** assignment and exposure exist (`GET …/coworker/experiments/positioning_2026_10`), but no page renders the positioning copy yet, so nobody is exposed. Wiring it into the marketing or onboarding surface is a separate change to shared pages.

## Rollback

- **Turn the flag off.** That feature returns to the pre-coworker path immediately (the unconditional parts above stay). The data stays, but unused:
  - rows in `pr_notification_*`, `pr_research_evidence`, `pr_strategy_hypotheses`, `pr_product_events` and `pr_experiment_assignments`;
  - keys under `state.coworker`.

  Nothing reads them while the flag is off, and the legacy email path resumes for the v2-owned kinds.
- **Push.** Turning the flag off stops sending. Subscriptions can be revoked in bulk with `UPDATE pr_push_subscriptions SET revoked_at=now(), revoked_reason='rollback'`.
- **Schema.** There is no down migration, by the repository's convention. Dropping the new tables would need a new forward migration and an owner decision.
- **`pr_reply_drafts`.** Its widened origin check (`copilot`) is additive, so rows written with origin `copilot` stay valid.

## What must be true before calling a flag "on in production"

- Its gates pass in CI on Python 3.12 with `openai-agents` installed, so no test is silently skipped.
- Its first live check has been done with the owner's authorization. The checks and costs are listed in the handoff.
