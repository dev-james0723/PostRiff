-- PENDING OWNER AUTHORIZATION. Do not run before approval of temporary migration-only privileges.
begin;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';
SELECT pg_advisory_xact_lock(hashtextextended('postriff-migrations',0));
DO $preflight$ BEGIN
IF (SELECT jsonb_object_agg(name,sha256) FROM postriff_private.schema_migrations) IS DISTINCT FROM '{"001_phase2.sql":"48250315280c51fb2d4c40de57eb332c80029ae5514da1b62482cbec367d9bcc","002_hosted_account_lifecycle.sql":"beb393985c4e58ec8255c9e9b27487d12bc96c29fa1560a243b247dc16be23a0","004_consumer_web_tenancy.sql":"9b9f44b41b9660bf82b47beafbc280803a68678079d0b7c9e28a5be2aaf948fa","005_consumer_web_ideas.sql":"baae632e07c0e30e1299838b8f32448771cb41eb5bc59e1b16211b049a93b78e","006_consumer_web_channels.sql":"43626c283cb3b16106411bb247b17b2a73a67c294a2bb1e82a537f99547650b3","007_consumer_web_billing.sql":"adff5e5d36ec6f8e3c253898d0843df972a151079f511a32457488b6ae9179de","008_billing_provider_notifications.sql":"20d3bb334a9a177f3428f063720ddafb556a91ec66f097f6ac1315a09fbabca1","009_account_security.sql":"e3fdcadc6f60802c6ebc5f296189d8b75c863da7406d7b6b3c99b2fded8f19dd","010_preference_learning.sql":"5193407e018f3249cdc99f937f7917d49aead56ad8d6f1a61ae38035c96fce4f","011_account_preferences.sql":"7b98bf8305813223a7bcf7235b57a089936291055aa4050f20138ac2883a12be","012_channel_pictures.sql":"bfc4a8c7126ca438a4496594b74aa9ab813c75b20686f4cc9b493188e29d37e3","013_locale_tags.sql":"fb1f45de7313f33f7b6f8803bb2d6c97ff168cdd9ff5e171cefb4c52f14e541f","014_billing_cost_visibility.sql":"b8bea33b74c29854e3cbaf9aff7d3e9bf67db45fd75bf90e2b08cb4a0bef8665","015_audit_visibility.sql":"35eea103e9e4d18eba28e093af6923f9228a01b06ddce240a3020faa0922dc44","016_api_tokens.sql":"2cfd4e6cd3170594aff082cda128e33988c02852a599824a2a1171995cd6e4d0","017_cli_reasoning.sql":"530769e7e970feb523f33604ad6ba30b7d441e21cfedb6959a8f8323dee27f55","018_raffi_planning.sql":"e9ccc13a444f6eec9f1f03860be967d22cc137ba3f5533e1d67ddf0acc31b9bb","019_research_requests.sql":"74ab96d77f01ca5f91c439d99d86740a47084b6ea46d6a846748e97c1a7f0446","020_credit_quotes.sql":"d23a0f3bf458c52dc34fd80653bdd8fcc79219d5c80f0195d8d737ff78a5af92","021_credit_purchases.sql":"d354474f5cbdb75c948a7ce12a4e13ad7ae419ebfb57544a09ef22a99add5895","022_credit_payment_lifecycle.sql":"0f34bc6ee71ed1b5fc9773ba4898591faca99b4b201ea4649b5051f864e3a069","023_time_savings.sql":"7a105a1a1d6d61fca317d767f67c9e672bc8e76b5e6c09a588ba4d189e2bf0a1","024_notification_core.sql":"f39a37ec099fc7928edccafca189c07ed39717585deac81312cefb09a15f46cc","025_coworker_evidence_growth.sql":"fc5f3e01ef93825e97bba21621ea834c4aba2622b9ac7504e2c872bd6b77f08e","030_agent_style.sql":"4a4e43810abafe0e0331f263c348623e0bc6c3f7eaedea010ece1404b4097e6a","031_chat_media.sql":"4403a1686045fe5a7ca2081ef57ebf136b7fd4cdd2a1f0768548dea240ab2a6c","032_productivity_connectors.sql":"c125a2d8354ab62a5df92b8dea425392c449d85540ba5c52ce5a21a9de799ea1","033_phone_mode.sql":"1c05526ab7c83660b4890bb978006697cd248fd7f997fdf90966828468662352","034_unified_notifications.sql":"df29f5f056955d74098b6de470250cc8013e8b9e683be0ae75ad5d3e7412f717","035_growth_metric_reads.sql":"e742c119c496d4e9ed9863bb8e176b103467315b4f1504e454319694f5a620b1","036_dial_phone_provider.sql":"d0c9ccd280c96e33b2ff75d52a3746fdb523b364547f4b51c377b5a5d2b7f554","040_social_trend_intelligence.sql":"fbabec3c66efc22927e9c2974c3c08b6cda122a4272bf1c63dd50c7c13f5f9c0","042_phone_inbound.sql":"78a23c99f1b876426fa4aa5193da67f2e9941901baee89502004ae84f9131554","043_phone_duration.sql":"a798b67d66a3664cb9010c7ae15d38707d537fd494591b336805058e326a9a7a","045_phone_caller_identity.sql":"1d672f5df62ae9209671d1b8505fe3729a6e6713e22a840b8db8edb0f76e1014","049_rafii_control_foundation.sql":"b4cdabf7cc9b8f63d83fd7897a5214f147c3a08d0bdd6e235507f82b12a7f322","051_rafii_control_read_workflow.sql":"67731fae74a5c0d4fcb1750318467ec8e2678efd5b7498aff3cb744340fea3e2","052_rafii_control_investigations.sql":"27736fa262bcd341161b7dcdd7b41860d27fa73682f8d140d8da9543232544d5","053_rafii_control_business_workspace.sql":"a1c475adeadecaabb6c4a69ce5ae84ba5beec525d2458de11975ae6011e8d60e","054_rafii_control_founder_views.sql":"d848748bf0f1c8f198979ac367522e3d9665be503d5d6a22279f1a5f5c1033d3","055_rafii_control_founder_contact.sql":"80155f9b67b774bc4a2ed7b9ef867c1d5fb1e2a64208ccfcc0e405d1c98983c1","056_rafii_control_founder_capabilities.sql":"e3410d4c920ec4c02da8e609bdec7a1fdfdbaeb89ceca489d7bb5a2a22646714","057_founder_billing_events.sql":"92b2c3f1ebb860ce769a6f76d0a059a120cabdfc04a9723a1748d68ef63cdcd3","058_founder_ai_usage.sql":"117d83f3c0a2e5ff9bc8223dd97e6be023cd89ee695ffad296aeb0419e4dd53e","059_founder_product.sql":"d3b733d493f946fd3b92643180209ae138bab7b93a8d8f6c801a4864fe3f1f77","060_founder_reliability.sql":"9be2086bfc10433025f62663911580a6bc67b3c46c9ac385226657b28e3d6532","062_founder_admin_actions.sql":"0826d0d1c5e6a90e64731e183f980e17babcd1c0bff3c22ec82e492b7d6ab7f7","063_founder_revenue_views.sql":"89008cf43248e3947f43b567870d77845e7493916121c5bf6c495c38a5f99541","064_founder_ai_views.sql":"856508ca28d016190ed7fcccb76d8a72bfb63abd4ecfaa8b6aeda94f7623b14d","065_founder_product_views.sql":"6a5a58e3af954e0f986660e595995cbdbea08be15f3539ca6cd026ec8f6d2c7a","066_founder_ops_views.sql":"98b48430f52d008672cc7b4e409b3305249364a33142df2d437f22fa223c41b7","067_founder_comms_views.sql":"5fdb3ee0b46054567d57e64dd0e3577c51d1eb5a70f30420f624d774ee912514","068_founder_actions_views.sql":"456f712ddf568d0c059d15b4701294a425794aaa065e4f785a245fa1a64163dc","069_founder_ops_bootstrap.sql":"0e6cf0780bed232cee33871985897b8252714cc5821b1a8d8be7772e3120dfc3","070_founder_ops_settings.sql":"b874c083f6a906b4332a84bb723f1371ffc5f04f7a9a3337b935e7c83f9c4a2c","071_founder_engineering_evidence.sql":"05b5acdf89f167d702fd44caa7ed5c4c6f755c278766a4055ea4e2d30a068720"}'::jsonb THEN RAISE EXCEPTION 'Migration ledger changed; reconcile before applying'; END IF;
END $preflight$;
DO $permissions$ BEGIN
 IF current_user <> 'postgres' OR NOT EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid JOIN pg_roles u ON u.oid=m.member JOIN pg_roles g ON g.oid=m.grantor WHERE r.rolname='rafii_control_business_projection' AND u.rolname='postgres' AND g.rolname='postgres' AND NOT m.admin_option AND NOT m.inherit_option AND NOT m.set_option) THEN RAISE EXCEPTION 'Migration permission baseline changed'; END IF;
 IF has_schema_privilege('rafii_control_business_projection','rafii_control','CREATE') THEN RAISE EXCEPTION 'Projection CREATE baseline changed'; END IF;
 PERFORM set_config('rafii_control.migration_members_before',(SELECT jsonb_agg(jsonb_build_array(roleid,member,grantor,admin_option,inherit_option,set_option) ORDER BY roleid,member,grantor)::text FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='rafii_control_business_projection')),true);
 PERFORM set_config('rafii_control.migration_acl_before',(SELECT jsonb_agg(jsonb_build_array(a.grantor,a.grantee,a.privilege_type,a.is_grantable) ORDER BY a.grantor,a.grantee,a.privilege_type,a.is_grantable)::text FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a WHERE n.nspname='rafii_control'),true);
END $permissions$;
GRANT rafii_control_business_projection TO postgres WITH SET TRUE GRANTED BY postgres;
GRANT rafii_control_business_projection TO postgres WITH INHERIT TRUE GRANTED BY postgres;
GRANT CREATE ON SCHEMA rafii_control TO rafii_control_business_projection;
-- Full-activation candidate. 088 was free in current source/open PRs on 2026-10-02.
-- Recheck the staging/production ledger before application. No old migration is replayed.

alter table rafii_control.founder_settings add column if not exists policy_revision integer not null default 0;
alter table rafii_control.founder_contact_policy drop constraint if exists founder_contact_policy_daily_cap_check;
alter table rafii_control.founder_contact_policy add constraint founder_contact_policy_daily_cap_check check(daily_cap between 0 and 100);
alter table rafii_control.founder_contact_policy drop constraint if exists founder_contact_policy_concurrent_cap_check;
alter table rafii_control.founder_contact_policy add constraint founder_contact_policy_concurrent_cap_check check(concurrent_cap between 0 and 10);
alter table rafii_control.founder_contact_policy drop constraint if exists founder_contact_policy_budget_usd_micro_daily_check;
alter table rafii_control.founder_contact_policy alter column budget_usd_micro_daily drop not null;
alter table rafii_control.founder_contact_policy add constraint founder_contact_policy_budget_usd_micro_daily_check check(budget_usd_micro_daily between 0 and 10000000000);

-- Legacy observations are unknown. Do not fabricate their availability time.
alter table public.pr_product_events add column if not exists recorded_at timestamptz;
alter table public.pr_product_events alter column recorded_at set default now();
grant select(recorded_at) on public.pr_product_events to rafii_control_business_projection;
create or replace view rafii_control.business_product_observations with(security_barrier=true) as
 select id::text as id,workspace_id::text as "workspaceId",event,occurred_at as "occurredAt",recorded_at as "recordedAt"
 from public.pr_product_events;

-- Only fixed counts/error classes are exposed. Recoverable rows remain in the
-- original tenant's audit, inaccessible to Control logins or Founder agents.
grant select(meta,subject) on public.pr_audit_events to rafii_control_business_projection;
create or replace view rafii_control.business_telemetry_health with(security_barrier=true) as
 select a.at as "observedAt",a.workspace_id::text as "workspaceId",
 case when a.kind='telemetry.product_events' then 'product_events' else 'ai_call_events' end as writer,
 case when a.meta->>'state' in ('recorded','failed','suspended') then a.meta->>'state' else 'unknown' end as state,
 case when a.meta->>'attempted' ~ '^[0-9]{1,3}$' then (a.meta->>'attempted')::integer else 0 end as attempted,
 case when a.meta->>'recorded' ~ '^[0-9]{1,3}$' then (a.meta->>'recorded')::integer else 0 end as recorded,
 case when a.meta->>'errorClass' ~ '^[A-Za-z][A-Za-z0-9_]{0,63}$' then a.meta->>'errorClass' end as "errorClass",
 a.meta->>'recoverable'='true' as recoverable,
 exists(select 1 from public.pr_audit_events r where r.kind='telemetry.recovered' and r.subject=a.id::text) as recovered
 from public.pr_audit_events a where a.kind in ('telemetry.product_events','telemetry.ai_call_events');

-- Configuration is a durable, explicit approval record. Empty means no new
-- real email dispatch. Founder/customer scopes never share approval or quota.
create table if not exists public.pr_delivery_cutovers (
 audience text not null check(audience in ('founder','customer')),
 channel text not null check(channel in ('email','push')),
 revision integer not null check(revision>0),
 mode text not null check(mode in ('canary_only','new_events_only','disabled')),
 not_before timestamptz not null,
 approved_at timestamptz not null,
 operator_id uuid not null,
 recipient_user_ids uuid[] not null default '{}',
 max_messages integer not null check(max_messages between 0 and 10000),
 template_version text not null check(length(template_version) between 1 and 80),
 approval_ref text not null check(approval_ref ~ '^[A-Za-z0-9_-]{1,40}$'),
 primary key(audience,channel,revision),
 check(mode!='canary_only' or cardinality(recipient_user_ids)>0)
);
alter table public.pr_delivery_cutovers enable row level security;
alter table public.pr_delivery_cutovers force row level security;
revoke all on public.pr_delivery_cutovers from public,anon,authenticated;
grant select,insert on public.pr_delivery_cutovers to service_role;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_delivery_cutovers' and policyname='service_only') then
  create policy service_only on public.pr_delivery_cutovers for all to service_role using(true) with check(true);
 end if;
end $$;

do $$ declare n text; begin
 foreach n in array array['business_product_observations','business_telemetry_health'] loop
  execute format('alter view rafii_control.%I owner to rafii_control_business_projection',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role',n);
  execute format('grant select on rafii_control.%I to rafii_control_reader',n);
 end loop;
end $$;

-- Original-tenant support. Reader roles receive fixed metadata only.
create table if not exists public.pr_support_tickets (
 id uuid primary key,workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 created_by uuid not null,category text not null check(category in ('technical','billing','account','other')),
 status text not null default 'open' check(status in ('open','waiting_customer','resolved')),
 revision integer not null default 1 check(revision>0),
 created_at timestamptz not null default now(),updated_at timestamptz not null default now(),
 first_response_at timestamptz,resolved_at timestamptz
);
create table if not exists public.pr_support_messages (
 id uuid primary key default gen_random_uuid(),workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 ticket_id uuid not null references public.pr_support_tickets(id) on delete cascade,
 actor_id uuid not null,actor_role text not null check(actor_role in ('customer','founder')),
 body text not null check(length(body) between 1 and 8000),request_id uuid not null,fingerprint text not null,
 created_at timestamptz not null default now(),unique(workspace_id,request_id)
);
create index if not exists pr_support_tenant_recent on public.pr_support_tickets(workspace_id,updated_at desc);
alter table public.pr_support_tickets enable row level security;
alter table public.pr_support_tickets force row level security;
alter table public.pr_support_messages enable row level security;
alter table public.pr_support_messages force row level security;
revoke all on public.pr_support_tickets,public.pr_support_messages from public,anon,authenticated;
grant select,insert,update on public.pr_support_tickets to service_role;
grant select,insert on public.pr_support_messages to service_role;
do $$ declare n text; begin
 foreach n in array array['pr_support_tickets','pr_support_messages'] loop
  if not exists(select 1 from pg_policies where schemaname='public' and tablename=n and policyname='service_only') then
   execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)',n);
  end if;
 end loop;
end $$;
grant select(id,workspace_id,created_by,category,status,revision,created_at,updated_at,first_response_at,resolved_at)
 on public.pr_support_tickets to rafii_control_business_projection;
grant select(workspace_id,kind) on rafii_control.workspace_classifications to rafii_control_business_projection;
create or replace view rafii_control.business_support_tickets with(security_barrier=true) as
 select t.id::text,t.workspace_id::text as "workspaceId",t.category as title,t.category,t.status,t.revision,
 t.created_at as at,t.created_at as "createdAt",t.updated_at as "updatedAt",t.first_response_at as "firstResponseAt",t.resolved_at as "resolvedAt",
 'masked'::text as "identityVisibility"
 from public.pr_support_tickets t
 where not exists(select 1 from rafii_control.workspace_classifications c where c.workspace_id=t.workspace_id and c.kind in ('internal','test','demo'));
alter view rafii_control.business_support_tickets owner to rafii_control_business_projection;
revoke all on rafii_control.business_support_tickets from public,anon,authenticated,service_role;
grant select on rafii_control.business_support_tickets to rafii_control_reader;

-- Never hard-delete financial dispatch history. Workspace deletion cannot
-- cascade through a pending or completed financial action. The historical
-- tenant identifier has no cascading FK, so customer content can be removed
-- while the confirmed financial action stays recoverable.
create table if not exists public.pr_founder_refund_dispatches (
 action_id uuid primary key,workspace_id uuid not null,
 payment_intent_id text not null,amount_minor bigint not null check(amount_minor>0),currency text not null,
 operator_id uuid not null,created_at timestamptz not null default now(),
 state text not null check(state in ('prepared','uncertain','pending','requires_action','succeeded','failed','canceled')),
 refund_id text,result jsonb
);
alter table public.pr_founder_refund_dispatches enable row level security;
alter table public.pr_founder_refund_dispatches force row level security;
revoke all on public.pr_founder_refund_dispatches from public,anon,authenticated;
grant select,insert,update on public.pr_founder_refund_dispatches to service_role;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_founder_refund_dispatches' and policyname='service_only') then
  create policy service_only on public.pr_founder_refund_dispatches for all to service_role using(true) with check(true);
 end if;
end $$;

-- Immutable original-tenant financial history survives customer content
-- deletion. Current billing projections may change; every observed version and
-- deletion tombstone remains here, with its original timestamps in record.
-- The initial snapshot is explicitly observed-existing, never synthetic past
-- change history. No Founder reader role can read these raw financial rows.
create table if not exists public.pr_financial_history (
 id uuid primary key default gen_random_uuid(),workspace_id uuid,
 source_table text not null,operation text not null check(operation in ('observed_existing','INSERT','UPDATE','DELETE')),
 observed_at timestamptz not null default clock_timestamp(),record jsonb not null,
 fingerprint text not null,unique(source_table,operation,fingerprint)
);
alter table public.pr_financial_history enable row level security;
alter table public.pr_financial_history force row level security;
revoke all on public.pr_financial_history from public,anon,authenticated,service_role;
grant select,insert on public.pr_financial_history to service_role;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_financial_history' and policyname='service_only') then
  create policy service_only on public.pr_financial_history for all to service_role using(true) with check(true);
 end if;
end $$;
create or replace function public.pr_financial_history_immutable() returns trigger language plpgsql set search_path=pg_catalog as $$
begin raise exception 'Financial history is immutable' using errcode='42501'; end $$;
drop trigger if exists immutable_history on public.pr_financial_history;
create trigger immutable_history before update or delete on public.pr_financial_history for each row execute function public.pr_financial_history_immutable();
drop trigger if exists immutable_history_truncate on public.pr_financial_history;
create trigger immutable_history_truncate before truncate on public.pr_financial_history for each statement execute function public.pr_financial_history_immutable();
create or replace function public.pr_financial_history_capture() returns trigger language plpgsql security definer set search_path=pg_catalog,public as $$
declare value jsonb; begin
 value=case when TG_OP='DELETE' then to_jsonb(OLD) else to_jsonb(NEW) end;
 insert into public.pr_financial_history(workspace_id,source_table,operation,record,fingerprint)
 values((value->>'workspace_id')::uuid,TG_TABLE_NAME,TG_OP,value,encode(sha256(convert_to(value::text,'UTF8')),'hex')) on conflict do nothing;
 return case when TG_OP='DELETE' then OLD else NEW end;
end $$;
revoke all on function public.pr_financial_history_capture(),public.pr_financial_history_immutable() from public,anon,authenticated,service_role;
do $$ declare n text; begin
 foreach n in array array['pr_usage_ledger','pr_subscription_events','pr_subscription_snapshots','pr_invoices','pr_credit_orders','pr_credit_subscription_grants','pr_credit_refunds','pr_credit_disputes','pr_founder_refund_dispatches'] loop
  if to_regclass('public.'||n) is not null then
   execute format('insert into public.pr_financial_history(workspace_id,source_table,operation,record,fingerprint) select (to_jsonb(r)->>''workspace_id'')::uuid,%L,''observed_existing'',to_jsonb(r),encode(sha256(convert_to(to_jsonb(r)::text,''UTF8'')),''hex'') from public.%I r on conflict do nothing',n,n);
   execute format('drop trigger if exists financial_history_capture on public.%I',n);
   execute format('create trigger financial_history_capture after insert or update or delete on public.%I for each row execute function public.pr_financial_history_capture()',n);
  end if;
 end loop;
end $$;
-- The three direct account templates without V2 equivalents use an encrypted
-- original-tenant outbox. No raw mail body or destination reaches Control.
create table if not exists public.pr_transactional_mail (
 id uuid primary key,workspace_id uuid references public.pr_workspaces(id) on delete cascade,
 user_id uuid references public.pr_profiles(user_id) on delete cascade,kind text not null check(kind in ('invitation','welcome','trial_ended')),
 semantic_key text not null unique check(semantic_key ~ '^[a-f0-9]{64}$'),
 recipient_hash text not null check(recipient_hash ~ '^[a-f0-9]{64}$'),
 payload_cipher text not null,key_id text not null,
 occurred_at timestamptz not null,expires_at timestamptz not null,
 status text not null default 'queued' check(status in ('queued','dispatching','provider_accepted','delivered','uncertain','suppressed','cancelled','failed','bounced','complained')),
 lease_until timestamptz,provider_ref text,failure_code text,delivered_at timestamptz,
 created_at timestamptz not null default now(),updated_at timestamptz not null default now()
);
alter table public.pr_transactional_mail enable row level security;
alter table public.pr_transactional_mail force row level security;
revoke all on public.pr_transactional_mail from public,anon,authenticated;
grant select,insert,update,delete on public.pr_transactional_mail to service_role;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_transactional_mail' and policyname='service_only') then
  create policy service_only on public.pr_transactional_mail for all to service_role using(true) with check(true);
 end if;
end $$;

GRANT rafii_control_business_projection TO postgres WITH INHERIT FALSE GRANTED BY postgres;
GRANT rafii_control_business_projection TO postgres WITH SET FALSE GRANTED BY postgres;
REVOKE CREATE ON SCHEMA rafii_control FROM rafii_control_business_projection;
DO $restore$ BEGIN
 IF current_setting('rafii_control.migration_members_before')::jsonb IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_array(roleid,member,grantor,admin_option,inherit_option,set_option) ORDER BY roleid,member,grantor) FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='rafii_control_business_projection')) THEN RAISE EXCEPTION 'Migration memberships did not restore'; END IF;
 IF current_setting('rafii_control.migration_acl_before')::jsonb IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_array(a.grantor,a.grantee,a.privilege_type,a.is_grantable) ORDER BY a.grantor,a.grantee,a.privilege_type,a.is_grantable) FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a WHERE n.nspname='rafii_control') THEN RAISE EXCEPTION 'Migration schema ACL did not restore'; END IF;
END $restore$;
INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES('088_founder_activation_integrity.sql','a900d721a735322e680ad448973dce9e1b2b83d13fce5a0962c20b10e71c546c');
commit;
