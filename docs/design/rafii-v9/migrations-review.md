# Production migrations review (2026-09-24)

Scope: what the code on `rafii-v9-integration` needs from the production database, what the repository
records say production has, and a read-only check to confirm it. Nothing here was run against
production; this review read only the repository.

## What production is known to have

The repository does not record an applied-migrations list for production. What it does record:

- `docs/codex-handoff-2026-09-19.md`: 010 (preference learning) **not applied** as of 19 Sep; 013 is a
  one-way rewrite of live data and needs James's go-ahead; 009 and 011 were outstanding and tied to
  Supabase dashboard settings.
- `docs/consumer-ready-mega-goal.zh-Hant.md`: the list of migrations applied in production "still needs
  item-by-item verification".
- Production has served the v9 release since 24 Sep (manual deploy, smoke-tested). That smoke test did not
  exercise suggestions or automations, so it does not prove 018 is present.

## What each migration is for, and what depends on it

| migration | kind | needed by | risk |
|---|---|---|---|
| 001–008 | tables, grants, RLS | everything (base schema) | additive; production could not serve without them |
| 009_account_security | table `pr_mfa_enforcement` | two-factor enforcement | additive; pairs with Supabase MFA settings |
| 010_preference_learning | 3 tables | preference learning (captures on every command) | additive |
| 011_account_preferences | 3 columns on `pr_profiles`, 2 indexes | Profile time zone, locale, new-device alerts (`/api/me`) | additive |
| 012_channel_pictures | table | account pictures in post previews | additive |
| 013_locale_tags | **updates rows** (`English`→`en`, `繁體中文`→`zh-Hant` in learning scopes) | worldwide languages on existing learned preferences | **one-way data rewrite; needs James's explicit go-ahead** |
| 014_billing_cost_visibility | replaces an RLS policy | owner-only raw ledger reads | policy change, reversible by re-creating the old policy |
| 015_audit_visibility | replaces an RLS policy | audit visible to admins and owners | policy change, reversible |
| 016_api_tokens | table | Account → API tokens | additive |
| 017_cli_reasoning | widens a check constraint | the five CLI reasoning levels on runs | additive in effect |
| 018_raffi_planning | 4 tables | **Automations and Rafii suggestions**: every save that touches a campaign, automation, run or suggestion writes these tables (`planning_store.sync` runs on every command) | additive |
| 019_research_requests | table | web research dispatch | additive |

Automations add no new migration: the Phase 1–3 work stores its fields in the JSON body columns of the
018 tables, uses `pr_notifications` (008) for "drafts ready" emails and reads `pr_metric_observations`
(007) for strong-post triggers.

**Consequence:** if 018 is not applied in production, saving an automation (or refreshing suggestions)
fails there. Deploying the Automations work should wait for the check below.

## Read-only check (for James to run in the Supabase SQL editor, or to approve me running it)

```sql
select 'table' as kind, table_name as name from information_schema.tables
 where table_schema = 'public' and table_name in ('pr_mfa_enforcement','pr_learning_events','pr_memory_proposals',
   'pr_memory_versions','pr_channel_pictures','pr_api_tokens','pr_campaigns','pr_recurring_tasks',
   'pr_recurring_occurrences','pr_suggestions','pr_research_requests')
union all
select 'profile column', column_name from information_schema.columns
 where table_schema = 'public' and table_name = 'pr_profiles' and column_name in ('time_zone','locale','alert_new_device')
union all
select 'policy', policyname from pg_policies
 where schemaname = 'public' and policyname in ('ledger_owner_read','audit_admin_read')
union all
select 'reasoning check', pg_get_constraintdef(oid) from pg_constraint where conname = 'pr_agent_runs_reasoning_check'
order by 1, 2;
-- 013 status: rows still using the old labels (a non-zero count means 013 has not run).
select count(*) as legacy_scope_rows from public.pr_memory_proposals where split_part(scope_key, '|', 5) in ('English', '繁體中文');
```

Everything missing from that output is a migration production still needs. Apply in number order;
each file states the migration it must follow.

## Recommended order once the check is back

1. Additive ones that current features already call: 018 (Automations, suggestions), then 019, 016,
   012, 011, 010, 017 — each only if missing.
2. The two policy changes, 014 and 015, if missing (they narrow who can read raw costs and audit).
3. 009 together with the Supabase MFA settings.
4. 013 last, only with James's explicit approval, after a backup (it rewrites existing rows).

## Production result (2026-09-24)

James approved the production release. The checks against the production database (Supabase project
`buoyhkbodnhzngaotoel`, Postgres 17.6) found the following.

- **018 was missing and is now applied and verified.**
  - All four tables were absent. It was applied with the exact reviewed file (sha256 `e9ccc13a…9bb`) through a one-off
    production-environment Vercel build that was never aliased.
  - The runner checked the prerequisites (`pr_workspaces`, `pr_profiles`, `postriff_private.member`, `gen_random_uuid`)
    and refused a partial state.
  - It then verified the columns, forced RLS, the `tenant_read` and `trusted_write` policies, grants (anon none,
    authenticated select, service_role insert) and both indexes.
  - A public PostgREST probe after the deploy answered 42501 (exists and is private) for all four tables.
  - Record: `.codex/rafii-v9-migration-018-20260924-1241/migration.json`.
- **The rest were read only and not applied**, because this release does not need them:
  - 016 (`pr_api_tokens`) and 019 (`pr_research_requests`) are missing (PGRST205). While 019 is missing, the cron's
    operations snapshot logs "unavailable" every minute.
  - The 014 and 015 policies are not present.
  - The 017 reasoning constraint is not widened.
  - There is no migration ledger table.
  - 013 has 0 legacy rows, so nothing is left for it to rewrite.
- The next step is unchanged from the recommended order above: 019, then 016, then the others, each additive except 013.

