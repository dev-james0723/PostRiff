-- Read-only: which pr_* tables exist? Expect the 001/002 set and NONE of: pr_invitations, pr_conversations, pr_oauth_transactions, pr_plan_terms, pr_notifications
select tablename from pg_tables where schemaname='public' and tablename like 'pr\_%' order by 1;
