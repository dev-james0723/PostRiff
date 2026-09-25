# Feature flags, rollout and rollback

Flags are defined in `src/postriff_phase2/coworker/flags.py`. They use the same rules as `agent_runtime_v2/config._flag`:
- a flag is off unless its value is `1`, `true`, `yes` or `on`;
- values are read from the hosted app's isolated environment;
- the browser learns them only through `GET …/coworker/status`, never through `NEXT_PUBLIC_*`.

With every flag off, the coworker features do nothing:
- the legacy emails are unchanged;
- the writer binds the same set of skills (with the flag on it adds the Humanizer packs and the active workflow's skill);
- the cron's coworker step returns `{"status": "disabled"}` without building anything;
- the feature routes answer `404 feature_disabled`. Exceptions: `GET …/coworker/status` and `GET …/coworker/research/providers` always answer;
  `GET …/coworker/growth` is an ungated owner/admin read (API.md); `GET …/coworker/experiments/{name}` answers `200 {enabled:false}`.

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
   - Production has no migration ledger, so `scripts/postriff_migrate.py` refuses it. Staging and production use a one-off runner pinned to each file's sha256, as 018, 019 and 020–022 were applied, never that script.
   - Apply 024, then 025, before any build containing this code is deployed against that database: account deletion deletes from their tables whatever the flags say.
   - A production-shaped rehearsal passed on 2026-09-25 (no ledger, no 014–017, with 018–022; both files applied twice).
   - Numbering and inventory: `docs/postriff-migration-numbering.md`. 020–022 are the production credit migrations, 023 is retired, 024–025 are these, and 026–029 are reserved for ai-routing.
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

## Production readiness (2026-09-25)

A static review of every flag against production as the release executor reported it on 2026-09-25:
- no `AI_GATEWAY_API_KEY` and no local CLI, so the writer is the deterministic template writer (no model; it charges nothing);
- `POSTRIFF_CREDITS_ENABLED` unset;
- no `RAFII_*` flag set;
- `OPENAI_API_KEY` set; no Resend key and no VAPID keys. Exa's MCP endpoint and Jina Reader need no key, so research does not depend on one;
- `POSTRIFF_RESEARCH`: not confirmed. Unset means on (`research.py:66-67`), and only Preview forces it to `0` (`deployment.py:52-55`). The research verdicts below assume it is unset;
- 024 and 025 applied before the coworker build is deployed.

Each verdict was checked by a second, adversarial reader. Nothing was run live.

| Flag | Verdict | Why | What unblocks it |
|---|---|---|---|
| `RAFII_SKILL_REGISTRY_V2_ENABLED` | Waits on an owner decision | No crash, no new egress and no credit bypass. But on single-destination English drafts it adds about 8.7k characters of skill text, which raises paid cost and the credit ceiling by about 13–15%. That can hold automations whose limit is near their ceiling (`ideas.py:1005-1009`). With the template writer it changes nothing. | Owner approves the cost change, after staging (Order, step 2). |
| `RAFII_NOTIFICATIONS_V2_ENABLED` | In-app only, after PR #9 | Without a Resend key or VAPID keys, email and push rows are planned as suppressed: nothing is sent, and no backlog or dead alarm fires. PR #9 fixes the security link, the unread count and the copy that promised email. On first load, the Overview attention panel lists every earlier failure. | PR #9, then an owner decision. Preview refuses this flag, so production is its first live run. |
| `RAFII_WEB_PUSH_ENABLED` | Pointless | Needs notifications v2 and all three VAPID keys; the opt-in says push isn't available. | A VAPID keypair and owner approval for push egress. |
| `RAFII_ADAPTIVE_SKILLS_ENABLED` | Pointless | Owner notes are stored but never reach the writer. Their only reader is the agent tool `overlay_context`, which needs Agent v2 and specialists. | Wire notes into the writer, or turn it on with the Agent Runtime. |
| `RAFII_WEEKLY_OPERATOR_ENABLED` | Blocked | With the template writer, every weekly draft is template text. Credit-policy autonomy is undecided. PR #9 fixes three things: the cron's credit binding (a `TypeError` whenever credits are on), the per-minute rewrite of a blocked week, and one recipe's error stopping the others. | A model writer (`AI_GATEWAY_API_KEY`), the credit-policy decision, and PR #9. |
| `RAFII_RESEARCH_BROKER_ENABLED` | Blocked; keep off | For workspaces whose owner allowed web research, `POST research/search` sends the query to Exa and reads pages through Jina, with no metering or rate limit. It also opens source-to-campaign, which shares Weekly's credit decision. (With `POSTRIFF_RESEARCH=0` it would do nothing.) | The owner's research decision, including a review of the agent's `research_fetch`. |
| `RAFII_CREATIVE_AGENT_ENABLED` | Pointless | A deterministic planner. No screen calls its route; its agent tool needs Agent v2 and specialists. | The Agent Runtime. |
| `RAFII_PERFORMANCE_LEARNING_ENABLED` | Pointless | Nothing in production writes `pr_metric_observations` (only the dev harness ingests insights). | Production insights ingestion. |
| `RAFII_LISTENING_ENABLED` | Blocked; keep off | For a workspace with a watchlist and research consent, the cron searches Exa every minute while holding the workspace row lock, and bumps the revision every minute. (With `POSTRIFF_RESEARCH=0` it skips every workspace.) | The research decision and a cron fix: search outside the lock, write only when a watchlist actually ran. |
| `RAFII_ENGAGEMENT_COPILOT_ENABLED` | Pointless | Its only screen is inside the Weekly page. Comments are fetched once per post, when it is verified. | Weekly, or an Inbox surface, and periodic comment fetching. |
| `RAFII_GROWTH_EXPERIMENTS_ENABLED` | Pointless | No page calls the experiments route. | A page that renders the positioning copy. |

Turning on any flag starts the coworker cron step every minute. Each step checks its own flag, and `retention_sweep` always runs. That sweep is harmless, but it scans all of `pr_product_events`: there is no `expires_at` index. With `RAFII_PERFORMANCE_LEARNING_ENABLED` on, the step also runs one query on `pr_metric_observations`, which is empty in production.

The Agent Runtime's own flags, in `consumer-saas` since PR #7:
- `RAFII_AGENT_V2_ENABLED`: blocked. No credit wiring: reservations carry no credit authority, and the hold is not a spending cap. No Preview isolation: its config reads raw `os.environ`.
- `RAFII_SPECIALISTS_ENABLED`: blocked, because it needs Agent v2. It also enables paid image generation.
- `RAFII_VOICE_ENABLED`: blocked, because it needs Agent v2.
- `RAFII_IMAGE_AGENT_ENABLED`: gates nothing.
- `RAFII_PROACTIVE_V2_ENABLED`: read nowhere.

With `OPENAI_API_KEY` set, the runtime uses OpenAI directly unless `RAFII_AGENT_PROVIDER=gateway` (`agent_runtime_v2/config.py:111`).
