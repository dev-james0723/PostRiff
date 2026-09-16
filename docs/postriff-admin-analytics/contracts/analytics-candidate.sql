-- Design-only vertical-slice DDL. Never auto-run against an existing database.
-- Preconditions: public.pr_workspaces(id uuid), public.pr_memberships(workspace_id,user_id,role,status), public.pr_profiles(user_id,deleted_at), auth.uid().
-- Initial test harness creates these synthetic prerequisites in a disposable database.
create schema pr_analytics;
revoke all on schema pr_analytics from public;

create table pr_analytics.admin_memberships (
 principal_id uuid primary key,
 role text not null check(role in ('platform_owner','ops_analyst','support_operator')),
 status text not null check(status in ('active','revoked')),
 version bigint not null default 1 check(version>0)
);
create table pr_analytics.accounts (
 workspace_id uuid not null references public.pr_workspaces(id),
 id uuid not null,
 provider text not null check(provider in ('youtube','instagram','linkedin')),
 provider_account_id text not null check(length(provider_account_id) between 1 and 500),
 consent_epoch bigint not null default 1 check(consent_epoch>0),
 status text not null check(status in ('active','revoked','unqualified')),
 primary key(workspace_id,id),
 unique(workspace_id,provider,provider_account_id)
);
create table pr_analytics.account_grants (
 workspace_id uuid not null,
 account_id uuid not null,
 principal_id uuid not null,
 consent_epoch bigint not null,
 can_read boolean not null default false,
 can_export boolean not null default false,
 expires_at timestamptz not null,
 primary key(workspace_id,account_id,principal_id),
 foreign key(workspace_id,account_id) references pr_analytics.accounts(workspace_id,id) on delete cascade
);
create table pr_analytics.posts (
 workspace_id uuid not null,
 account_id uuid not null,
 id uuid not null,
 provider_post_id text not null check(length(provider_post_id)>0),
 published_at timestamptz,
 origin text not null check(origin in ('postriff_published','postriff_export_linked','native_imported','unknown')),
 primary key(workspace_id,account_id,id),
 unique(workspace_id,account_id,provider_post_id),
 foreign key(workspace_id,account_id) references pr_analytics.accounts(workspace_id,id) on delete cascade
);
create table pr_analytics.metric_points (
 id uuid primary key,
 workspace_id uuid not null,
 account_id uuid not null,
 object_key text not null,
 metric_key text not null,
 metric_version integer not null check(metric_version>0),
 grain text not null check(grain in ('day','period','lifetime','snapshot')),
 period_key text not null,
 dimensions_hash text not null check(length(dimensions_hash)=64),
 source_kind text not null check(source_kind in ('provider_api','native_export','manual_entry','first_party')),
 execution text not null check(execution in ('live','synthetic')),
 unique(workspace_id,account_id,id),
 unique(workspace_id,account_id,object_key,metric_key,metric_version,grain,period_key,dimensions_hash,source_kind,execution),
 foreign key(workspace_id,account_id) references pr_analytics.accounts(workspace_id,id) on delete cascade
);
create table pr_analytics.metric_revisions (
 id uuid primary key,
 workspace_id uuid not null,
 account_id uuid not null,
 point_id uuid not null,
 fetch_id uuid not null,
 value numeric(30,8),
 value_status text not null check(value_status in ('measured','not_connected','scope_missing','not_supported','not_applicable','pending_provider','suppressed','stale','error','deleted','unavailable')),
 observed_at timestamptz not null,
 period_start timestamptz,
 period_end timestamptz,
 evidence_ref text not null,
 check((value_status='measured' and value is not null) or (value_status<>'measured' and value is null)),
 check(value is null or value::text not in ('NaN','Infinity','-Infinity')),
 check((period_start is null and period_end is null) or (period_start is not null and period_end is not null and period_end>period_start)),
 unique(point_id,fetch_id),
 foreign key(workspace_id,account_id,point_id) references pr_analytics.metric_points(workspace_id,account_id,id) on delete cascade
);
-- Candidate current view: production normalizer still enforces metric-kind/policy/consent/version.
create view pr_analytics.current_metrics with (security_invoker=true) as
 select distinct on (point_id) r.* from pr_analytics.metric_revisions r
 order by point_id,observed_at desc,id desc;

create table pr_analytics.event_outbox (
 event_id uuid primary key,
 workspace_id uuid not null references public.pr_workspaces(id),
 operation_id uuid not null,
 semantic_kind text not null,
 aggregate_revision bigint not null check(aggregate_revision>0),
 execution text not null check(execution in ('live','synthetic')),
 payload_hash text not null check(length(payload_hash)=64),
 occurred_at timestamptz not null,
 unique(workspace_id,operation_id,semantic_kind,aggregate_revision)
);

create function pr_analytics.can_read_account(w uuid,a uuid) returns boolean
 language sql stable security definer set search_path='' as $$
 select exists (
  select 1 from pr_analytics.accounts ac
  join pr_analytics.account_grants g on g.workspace_id=ac.workspace_id and g.account_id=ac.id
  join public.pr_memberships m on m.workspace_id=ac.workspace_id and m.user_id=g.principal_id
  join public.pr_profiles p on p.user_id=m.user_id and p.deleted_at is null
  where ac.workspace_id=w and ac.id=a and ac.status='active'
   and g.principal_id=auth.uid() and g.can_read and g.expires_at>now()
   and g.consent_epoch=ac.consent_epoch and m.status='active'
 );
$$;
revoke all on function pr_analytics.can_read_account(uuid,uuid) from public;
grant usage on schema pr_analytics to authenticated;
grant execute on function pr_analytics.can_read_account(uuid,uuid) to authenticated;

alter table pr_analytics.accounts enable row level security;
alter table pr_analytics.posts enable row level security;
alter table pr_analytics.metric_points enable row level security;
alter table pr_analytics.metric_revisions enable row level security;
create policy scoped_accounts on pr_analytics.accounts for select to authenticated using(pr_analytics.can_read_account(workspace_id,id));
create policy scoped_posts on pr_analytics.posts for select to authenticated using(pr_analytics.can_read_account(workspace_id,account_id));
create policy scoped_points on pr_analytics.metric_points for select to authenticated using(pr_analytics.can_read_account(workspace_id,account_id));
create policy scoped_revisions on pr_analytics.metric_revisions for select to authenticated using(pr_analytics.can_read_account(workspace_id,account_id));
grant select on pr_analytics.accounts,pr_analytics.posts,pr_analytics.metric_points,pr_analytics.metric_revisions,pr_analytics.current_metrics to authenticated;
-- No browser write privileges, no direct admin/grants/outbox access.
create index scoped_post_date on pr_analytics.posts(workspace_id,account_id,published_at desc,id);
create index scoped_metric_window on pr_analytics.metric_points(workspace_id,account_id,metric_key,period_key);
create index latest_revision on pr_analytics.metric_revisions(point_id,observed_at desc);
