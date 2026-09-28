-- WP01/02/10: additive durable trend spine. No provider calls, publication or default budgets.
-- 036-039 belong to other workstreams. Apply against this branch's 035 schema baseline.
begin;
create table public.pr_trend_scopes (
 scope_key text primary key, workspace_id uuid references public.pr_workspaces(id) on delete cascade,
 enabled boolean not null default true,
 check ((workspace_id is not null and scope_key='workspace:'||workspace_id::text)
     or (workspace_id is null and scope_key ~ '^shared:[a-z0-9][a-z0-9_.-]{0,95}$'))
);
create table public.pr_trend_entitlements (
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 scope_key text not null references public.pr_trend_scopes(scope_key) on delete cascade,
 operations text[] not null, expires_at timestamptz not null, revoked_at timestamptz,
 primary key(workspace_id,scope_key), check (cardinality(operations)>0)
);
create table public.pr_trend_provider_contracts (
 provider_id text not null, version text not null, operations text[] not null,
 valid_from timestamptz not null, expires_at timestamptz not null, revoked_at timestamptz,
 available_at timestamptz not null default clock_timestamp(),
 manifest jsonb not null check(jsonb_typeof(manifest)='object' and octet_length(manifest::text)<=65536),
 primary key(provider_id,version), check(valid_from<expires_at)
);
create table public.pr_trend_source_policies (
 scope_key text not null references public.pr_trend_scopes(scope_key) on delete cascade,
 provider_id text not null, version text not null, provider_contract_version text not null,
 operations text[] not null, rights jsonb not null check(jsonb_typeof(rights)='object'),
 readiness text not null default 'access_pending', valid_from timestamptz not null, expires_at timestamptz not null,
 revoked_at timestamptz, max_retention_seconds integer not null check(max_retention_seconds>0),
 available_at timestamptz not null default clock_timestamp(),
 manifest jsonb not null check(jsonb_typeof(manifest)='object' and octet_length(manifest::text)<=65536),
 primary key(scope_key,provider_id,version),
 foreign key(provider_id,provider_contract_version) references public.pr_trend_provider_contracts(provider_id,version),
 check(valid_from<expires_at)
);
create table public.pr_trend_method_versions (
 method_id text not null, version text not null, artifact_digest text not null check(artifact_digest ~ '^[a-f0-9]{64}$'),
 config jsonb not null check(jsonb_typeof(config)='object' and octet_length(config::text)<=65536),
 qualification text not null check(qualification in ('shadow','qualified','withdrawn')),
 created_at timestamptz not null default now(), revoked_at timestamptz, primary key(method_id,version)
);
create table public.pr_trend_nodes (
 scope_key text not null references public.pr_trend_scopes(scope_key) on delete cascade,
 node_id uuid not null, node_kind text not null,
 available_at timestamptz not null, retention_until timestamptz not null,
 validity text not null default 'valid' check(validity in ('valid','revoked','purged','stale')),
 primary key(scope_key,node_id), check(available_at<retention_until)
);
create index pr_trend_nodes_expiry on public.pr_trend_nodes(retention_until) where validity<>'purged';
create table public.pr_trend_observations (
 scope_key text not null, observation_id uuid not null, provider_id text not null,
 source_identity text not null, source_identity_digest text not null check(source_identity_digest ~ '^[a-f0-9]{64}$'),
 revision_identity text not null, revision_sequence bigint not null check(revision_sequence>=0),
 kind text not null check(kind in ('raw_post','owned_post','aggregate_metric','search_lead','trend_seed')),
 operation text not null check(operation in ('create','update','delete')),
 event_at timestamptz, received_at timestamptz not null, available_at timestamptz not null,
 retention_until timestamptz not null, coverage_epoch text not null,
 source_policy_version text not null, provider_contract_version text not null,
 rights jsonb not null check(jsonb_typeof(rights)='object'),
 payload jsonb not null check(jsonb_typeof(payload)='object' and octet_length(payload::text)<=131072),
 schema_version text not null, time_basis text not null, provenance jsonb not null, deletion_key text not null,
 payload_digest text check(payload_digest ~ '^[a-f0-9]{64}$'),
 native_item_id text, author_key text, author_status text, canonical_url text,
 aggregate_start timestamptz, aggregate_end timestamptz, metric_id text, metric_unit text,
 metric_value numeric, metric_null_reason text, population text, aggregation_semantics text,
 purged_at timestamptz,
 primary key(scope_key,observation_id),
 unique(scope_key,provider_id,source_identity_digest,revision_identity),
 unique(scope_key,provider_id,source_identity_digest,revision_sequence),
 foreign key(scope_key,observation_id) references public.pr_trend_nodes(scope_key,node_id) on delete cascade,
 foreign key(scope_key,provider_id,source_policy_version) references public.pr_trend_source_policies(scope_key,provider_id,version),
 foreign key(provider_id,provider_contract_version) references public.pr_trend_provider_contracts(provider_id,version),
 check(received_at<=available_at and available_at<retention_until),
 check(kind<>'owned_post' or scope_key like 'workspace:%'),
 check(purged_at is not null or operation='delete' or kind not in ('raw_post','owned_post') or native_item_id is not null),
 check(kind<>'aggregate_metric' or (native_item_id is null and author_key is null)),
 check(purged_at is not null or operation='delete' or kind<>'aggregate_metric' or
   (aggregate_start<aggregate_end and metric_id is not null and metric_unit is not null and (metric_value is not null or metric_null_reason is not null)
    and (metric_value is null or metric_value::text not in ('NaN','Infinity','-Infinity')) and population is not null and aggregation_semantics is not null))
);
create index pr_trend_observations_provider_time on public.pr_trend_observations(provider_id,scope_key,available_at);
create index pr_trend_observations_delete on public.pr_trend_observations(scope_key,provider_id,source_identity_digest);
create table public.pr_trend_source_heads (
 scope_key text not null, provider_id text not null, source_identity_digest text not null,
 revision_sequence bigint not null, observation_id uuid not null,
 primary key(scope_key,provider_id,source_identity_digest),
 foreign key(scope_key,observation_id) references public.pr_trend_observations(scope_key,observation_id) on delete cascade
);
create table public.pr_trend_dependencies (
 scope_key text not null, node_id uuid not null, input_scope_key text not null, input_node_id uuid not null,
 primary key(scope_key,node_id,input_scope_key,input_node_id),
 foreign key(scope_key,node_id) references public.pr_trend_nodes(scope_key,node_id) on delete cascade,
 foreign key(input_scope_key,input_node_id) references public.pr_trend_nodes(scope_key,node_id),
 check((scope_key,node_id)<>(input_scope_key,input_node_id))
);
create index pr_trend_dependencies_reverse on public.pr_trend_dependencies(input_scope_key,input_node_id);
create table public.pr_trend_input_manifests (
 scope_key text not null, manifest_id uuid not null, digest text check(digest ~ '^[a-f0-9]{64}$'),
 recipe jsonb not null default '{}' check(jsonb_typeof(recipe)='object' and octet_length(recipe::text)<=65536),
 document_digest text,
 decision_cutoff timestamptz not null, input_count integer not null check(input_count>=0),
 primary key(scope_key,manifest_id),
 foreign key(scope_key,manifest_id) references public.pr_trend_nodes(scope_key,node_id) on delete cascade
);
create table public.pr_trend_manifest_chunks (
 scope_key text not null, manifest_id uuid not null, ordinal integer not null check(ordinal>=0),
 digest text, payload jsonb not null check(jsonb_typeof(payload)='object' and octet_length(payload::text)<=65536),
 primary key(scope_key,manifest_id,ordinal),
 foreign key(scope_key,manifest_id) references public.pr_trend_input_manifests on delete cascade
);
create table public.pr_trend_manifest_inputs (
 scope_key text not null, manifest_id uuid not null, ordinal integer not null check(ordinal>=0),
 input_scope_key text not null, input_node_id uuid not null,
 primary key(scope_key,manifest_id,ordinal), unique(scope_key,manifest_id,input_scope_key,input_node_id),
 foreign key(scope_key,manifest_id) references public.pr_trend_input_manifests(scope_key,manifest_id) on delete cascade,
 foreign key(input_scope_key,input_node_id) references public.pr_trend_nodes(scope_key,node_id)
);
create table public.pr_trend_trust_receipts (
 scope_key text not null, receipt_id uuid not null, schema_version text not null check(schema_version='rafii.trend-trust-receipt.v2'),
 manifest_id uuid not null, method_id text not null, method_version text not null,
 decision_cutoff timestamptz not null, payload jsonb not null check(jsonb_typeof(payload)='object' and octet_length(payload::text)<=131072),
 verification_state text not null default 'pending' check(verification_state in ('pending','verified','mismatch','inputs_expired','inputs_deleted','policy_revoked','method_unavailable')),
 verification_record jsonb not null default '{}', verified_at timestamptz,
 primary key(scope_key,receipt_id),
 foreign key(scope_key,receipt_id) references public.pr_trend_nodes(scope_key,node_id) on delete cascade,
 foreign key(scope_key,manifest_id) references public.pr_trend_input_manifests(scope_key,manifest_id),
 foreign key(method_id,method_version) references public.pr_trend_method_versions(method_id,version)
);
create table public.pr_trend_projections (
 scope_key text not null, kind text not null, object_id uuid not null, revision bigint not null check(revision>0),
 projection_id uuid not null, manifest_id uuid not null, receipt_id uuid,
 method_id text not null, method_version text not null, decision_cutoff timestamptz not null,
 available_at timestamptz not null, retention_until timestamptz not null,
 payload jsonb not null check(jsonb_typeof(payload)='object' and octet_length(payload::text)<=131072),
 context_digest text, draft_id text, draft_revision text,
 primary key(scope_key,kind,object_id,revision), unique(scope_key,projection_id),
 foreign key(scope_key,projection_id) references public.pr_trend_nodes(scope_key,node_id) on delete cascade,
 foreign key(scope_key,manifest_id) references public.pr_trend_input_manifests(scope_key,manifest_id),
 foreign key(scope_key,receipt_id) references public.pr_trend_trust_receipts(scope_key,receipt_id),
 foreign key(method_id,method_version) references public.pr_trend_method_versions(method_id,version),
 check(available_at<retention_until),
 check(kind not in ('opportunity','lab','watch','whitespace','exposure') or scope_key like 'workspace:%')
);
create index pr_trend_projections_list on public.pr_trend_projections(scope_key,kind,available_at desc,object_id,revision desc);
create index pr_trend_projections_search on public.pr_trend_projections using gin(to_tsvector('simple',coalesce(payload->>'canonical_topic','')));
create index pr_trend_projections_dimensions on public.pr_trend_projections(scope_key,kind,(payload->>'platform'),(payload->>'language'),available_at desc);
create index pr_trend_projections_draft on public.pr_trend_projections(scope_key,draft_id,draft_revision) where draft_id is not null;
create table public.pr_trend_watches (
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 watch_id uuid not null, idempotency_key text not null, created_by uuid not null, revision bigint not null default 1,
 deletion_key text,
 payload jsonb not null check(jsonb_typeof(payload)='object' and octet_length(payload::text)<=16384),
 enabled boolean not null default true, created_at timestamptz not null default now(),
 primary key(workspace_id,watch_id), unique(workspace_id,idempotency_key)
);
create table public.pr_trend_deletion_tombstones (
 scope_key text not null references public.pr_trend_scopes(scope_key) on delete cascade,
 provider_id text not null, source_identity_digest text not null,
 deletion_sequence bigint not null check(deletion_sequence>=0), reason_code text not null,
 revoked_at timestamptz not null default now(), purge_deadline timestamptz not null,
 primary key(scope_key,provider_id,source_identity_digest)
);
create table public.pr_trend_deletion_tasks (
 scope_key text not null, provider_id text not null, source_identity_digest text not null,
 state text not null default 'queued' check(state in ('queued','done')), updated_at timestamptz not null default now(),
 primary key(scope_key,provider_id,source_identity_digest),
 foreign key(scope_key,provider_id,source_identity_digest) references public.pr_trend_deletion_tombstones on delete cascade
);
create table public.pr_trend_author_tombstones (
 provider_id text not null, author_digest text not null, revoked_at timestamptz not null,
 purge_deadline timestamptz not null, primary key(provider_id,author_digest)
);
create table public.pr_trend_runtime_guard (
 singleton boolean primary key default true check(singleton), reads_ready boolean not null default true,
 restore_generation bigint not null default 0, tombstone_digest text
);
insert into public.pr_trend_runtime_guard(singleton) values(true);
create table public.pr_trend_provider_cursors (
 scope_key text not null references public.pr_trend_scopes(scope_key) on delete cascade,
 provider_id text not null, partition_key text not null, generation bigint not null default 0,
 cursor_value jsonb not null default '{}', coverage_state text not null default 'partial' check(coverage_state in ('partial','complete','gap')),
 updated_at timestamptz not null default now(), primary key(scope_key,provider_id,partition_key)
);
create table public.pr_trend_jobs (
 scope_key text not null references public.pr_trend_scopes(scope_key) on delete cascade,
 job_id uuid not null, kind text not null, provider_id text, source_policy_version text,
 idempotency_key text not null, payload jsonb not null check(jsonb_typeof(payload)='object' and octet_length(payload::text)<=65536),
 state text not null default 'queued' check(state in ('queued','leased','running','retry_wait','succeeded','failed_terminal','cancelled','outcome_unknown')),
 due_at timestamptz not null default now(), priority integer not null default 0,
 attempts integer not null default 0, max_attempts integer not null default 3 check(max_attempts between 1 and 10),
 lease_owner text, lease_until timestamptz, lease_generation bigint not null default 0,
 cancellation_requested boolean not null default false, error_code text,
 reservation_id uuid, created_at timestamptz not null default now(),
 primary key(scope_key,job_id), unique(scope_key,idempotency_key),
 foreign key(scope_key,provider_id,source_policy_version) references public.pr_trend_source_policies(scope_key,provider_id,version),
 check((provider_id is null)=(source_policy_version is null))
);
create index pr_trend_jobs_due on public.pr_trend_jobs(state,priority desc,due_at);
create index pr_trend_jobs_lease on public.pr_trend_jobs(lease_until) where state in ('leased','running');
create table public.pr_trend_ingestion_batches (
 scope_key text not null, provider_id text not null, partition_key text not null, batch_key text not null,
 job_id uuid not null, fence bigint not null, previous_generation bigint not null, next_generation bigint not null,
 item_count integer not null check(item_count>=0), digest text not null, terminal_page boolean not null,
 committed_at timestamptz not null default now(), primary key(scope_key,provider_id,partition_key,batch_key),
 foreign key(scope_key,job_id) references public.pr_trend_jobs(scope_key,job_id),
 foreign key(scope_key,provider_id,partition_key) references public.pr_trend_provider_cursors,
 check(next_generation=previous_generation+1)
);
create table public.pr_trend_budget_limits (
 budget_key text primary key, dimension text not null check(dimension in ('system','provider','workspace','run')),
 period_start timestamptz not null, period_end timestamptz not null,
 cap_micro_usd bigint not null check(cap_micro_usd>=0), settled_micro_usd bigint not null default 0,
 reserved_micro_usd bigint not null default 0, unknown_micro_usd bigint not null default 0,
 check(period_start<period_end), check(settled_micro_usd>=0 and reserved_micro_usd>=0 and unknown_micro_usd>=0)
);
create table public.pr_trend_budget_reservations (
 scope_key text not null references public.pr_trend_scopes(scope_key) on delete cascade,
 reservation_id uuid not null, logical_call_id text not null, physical_attempt_id uuid not null,
 amount_micro_usd bigint not null check(amount_micro_usd>=0), actual_micro_usd bigint check(actual_micro_usd>=0),
 state text not null default 'reserved' check(state in ('reserved','dispatched','unknown','settled','released')),
 usage_event_id text, created_at timestamptz not null default now(),
 primary key(scope_key,reservation_id), unique(scope_key,physical_attempt_id)
);
alter table public.pr_trend_jobs add foreign key(scope_key,reservation_id) references public.pr_trend_budget_reservations(scope_key,reservation_id);
create table public.pr_trend_reservation_dimensions (
 scope_key text not null, reservation_id uuid not null, budget_key text not null references public.pr_trend_budget_limits,
 primary key(scope_key,reservation_id,budget_key),
 foreign key(scope_key,reservation_id) references public.pr_trend_budget_reservations on delete cascade
);
create table public.pr_trend_outbox (
 scope_key text not null references public.pr_trend_scopes(scope_key) on delete cascade,
 event_id uuid not null, event_key text not null, event_type text not null, node_id uuid,
 payload jsonb not null check(jsonb_typeof(payload)='object' and octet_length(payload::text)<=65536),
 created_at timestamptz not null default now(), primary key(scope_key,event_id), unique(scope_key,event_key),
 foreign key(scope_key,node_id) references public.pr_trend_nodes(scope_key,node_id)
);
create table public.pr_trend_outbox_consumers (
 consumer text not null, scope_key text not null, event_id uuid not null,
 state text not null check(state in ('leased','done','suppressed')), lease_owner text, lease_until timestamptz,
 lease_generation bigint not null default 1, completed_at timestamptz,
 primary key(consumer,scope_key,event_id), foreign key(scope_key,event_id) references public.pr_trend_outbox on delete cascade
);
create table public.pr_trend_source_health (
 scope_key text not null references public.pr_trend_scopes(scope_key) on delete cascade,
 provider_id text not null, status text not null check(status in ('healthy','partial','gap','unavailable','revoked')),
 observed_at timestamptz not null, next_allowed_at timestamptz, latency_ms integer check(latency_ms>=0),
 freshness_lag_seconds integer check(freshness_lag_seconds>=0), notes_code text not null,
 primary key(scope_key,provider_id)
);
create table public.pr_trend_opportunity_decisions (
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 scope_key text not null, object_id uuid not null, revision bigint not null, kind text not null default 'opportunity' check(kind='opportunity'),
 idempotency_key text not null, decision text not null check(decision in ('save','accept','dismiss','watch')),
 actor_id uuid not null, result jsonb not null default '{}', created_at timestamptz not null default now(),
 primary key(workspace_id,idempotency_key), unique(workspace_id,object_id,revision,decision),
 foreign key(scope_key,kind,object_id,revision) references public.pr_trend_projections(scope_key,kind,object_id,revision),
 check(scope_key='workspace:'||workspace_id::text)
);
-- Dependency authorization and cycle checks apply even to service-role writes.
create function postriff_private.trend_dependency_guard() returns trigger language plpgsql set search_path='' as $$
declare wid uuid;
begin
 perform pg_advisory_xact_lock(hashtextextended('pr-trend-dependency-graph',0));
 if new.scope_key<>new.input_scope_key then
  select workspace_id into wid from public.pr_trend_scopes where scope_key=new.scope_key;
  if wid is null or new.input_scope_key not like 'shared:%' or not exists(
   select 1 from public.pr_trend_entitlements where workspace_id=wid and scope_key=new.input_scope_key
   and revoked_at is null and expires_at>clock_timestamp() and 'derive_metrics'=any(operations)) then
   raise exception 'trend dependency scope denied' using errcode='42501';
  end if;
 end if;
 if exists(with recursive ancestors(s,n) as (
  select new.input_scope_key,new.input_node_id union
  select d.input_scope_key,d.input_node_id from public.pr_trend_dependencies d join ancestors a on (d.scope_key,d.node_id)=(a.s,a.n)
 ) select 1 from ancestors where (s,n)=(new.scope_key,new.node_id)) then
  raise exception 'trend dependency cycle' using errcode='23514';
 end if;
 return new;
end $$;
create trigger pr_trend_dependency_guard before insert or update on public.pr_trend_dependencies for each row execute function postriff_private.trend_dependency_guard();
create function postriff_private.trend_scope_readable(s text) returns boolean language sql volatile security definer set search_path='' as $$
 select exists(select 1 from public.pr_trend_scopes q where q.scope_key=s and q.enabled and (
   (q.workspace_id is not null and postriff_private.member(q.workspace_id)) or
   exists(select 1 from public.pr_trend_entitlements e where e.scope_key=s and e.revoked_at is null
    and e.expires_at>clock_timestamp() and 'retrieve'=any(e.operations) and postriff_private.member(e.workspace_id))))
$$;
create function postriff_private.trend_permits(rights jsonb,permission text,s text) returns boolean language plpgsql volatile set search_path='' as $$
begin
 return coalesce(rights->permission->>'state'='allow' and rights->permission->>'audience_scope'=s
  and length(rights->permission->>'policy_ref')>0 and (rights->permission->>'expires_at')::timestamptz>clock_timestamp(),false);
exception when others then return false;
end $$;
revoke all on function postriff_private.trend_permits(jsonb,text,text) from public,anon;
grant execute on function postriff_private.trend_permits(jsonb,text,text) to authenticated,service_role;
create function postriff_private.trend_node_valid(s text,n uuid) returns boolean language sql volatile security definer set search_path='' as $$
 with recursive ancestors(scope_key,node_id) as (
  select s,n union select d.input_scope_key,d.input_node_id from public.pr_trend_dependencies d join ancestors a using(scope_key,node_id)
 ) select exists(select 1 from public.pr_trend_nodes where scope_key=s and node_id=n)
 and (select reads_ready from public.pr_trend_runtime_guard where singleton)
 and not exists(select 1 from ancestors a
  left join public.pr_trend_nodes nd using(scope_key,node_id)
  left join public.pr_trend_scopes sc using(scope_key)
  left join public.pr_trend_observations o on (o.scope_key,o.observation_id)=(a.scope_key,a.node_id)
  left join public.pr_trend_source_policies p on (p.scope_key,p.provider_id,p.version)=(o.scope_key,o.provider_id,o.source_policy_version)
  left join public.pr_trend_provider_contracts c on (c.provider_id,c.version)=(o.provider_id,o.provider_contract_version)
  where nd.node_id is null or not sc.enabled or nd.validity<>'valid' or nd.available_at>clock_timestamp() or nd.retention_until<=clock_timestamp()
   or (o.observation_id is not null and (o.operation='delete' or o.purged_at is not null
    or p.revoked_at is not null or p.expires_at<=clock_timestamp() or p.valid_from>clock_timestamp() or not 'retrieve'=any(p.operations) or p.readiness<>'ready' or not postriff_private.trend_permits(p.rights,'retrieve',p.scope_key)
    or c.revoked_at is not null or c.expires_at<=clock_timestamp() or c.valid_from>clock_timestamp() or not 'retrieve'=any(c.operations) or not postriff_private.trend_permits(o.rights,'retrieve',o.scope_key)
    or exists(select 1 from public.pr_trend_author_tombstones a where a.provider_id=o.provider_id and a.author_digest=encode(sha256(convert_to(o.author_key,'UTF8')),'hex'))
    or exists(select 1 from public.pr_trend_deletion_tombstones t where (t.scope_key,t.provider_id,t.source_identity_digest)=(o.scope_key,o.provider_id,o.source_identity_digest)))) )
 and not exists(select 1 from ancestors a join public.pr_trend_observations o on(o.scope_key,o.observation_id)=(a.scope_key,a.node_id)
  join public.pr_trend_source_policies p on(p.scope_key,p.provider_id,p.version)=(o.scope_key,o.provider_id,o.source_policy_version)
  where exists(select 1 from public.pr_trend_nodes root where root.scope_key=s and root.node_id=n and root.node_kind<>'observation')
   and (not postriff_private.trend_permits(o.rights,'derive_metrics',o.scope_key)
    or not postriff_private.trend_permits(p.rights,'derive_metrics',o.scope_key)
    or not postriff_private.trend_permits(o.rights,'retain_derivatives',o.scope_key)
    or not postriff_private.trend_permits(p.rights,'retain_derivatives',o.scope_key)
    or (o.scope_key<>s and (not postriff_private.trend_permits(o.rights,'share_across_workspaces',o.scope_key)
       or not postriff_private.trend_permits(p.rights,'share_across_workspaces',o.scope_key)))))
 and not exists(select 1 from ancestors a join public.pr_trend_trust_receipts r on (r.scope_key,r.receipt_id)=(a.scope_key,a.node_id)
  join public.pr_trend_method_versions m on (m.method_id,m.version)=(r.method_id,r.method_version) where m.revoked_at is not null or m.qualification='withdrawn')
 and not exists(select 1 from ancestors a join public.pr_trend_projections p on (p.scope_key,p.projection_id)=(a.scope_key,a.node_id)
  join public.pr_trend_method_versions m on (m.method_id,m.version)=(p.method_id,p.method_version) where m.revoked_at is not null or m.qualification='withdrawn')
 and not exists(select 1 from ancestors a join public.pr_trend_dependencies d using(scope_key,node_id)
  join public.pr_trend_scopes q on q.scope_key=d.scope_key where d.scope_key<>d.input_scope_key and not exists(
   select 1 from public.pr_trend_entitlements e where e.workspace_id=q.workspace_id and e.scope_key=d.input_scope_key
    and e.revoked_at is null and e.expires_at>clock_timestamp() and 'derive_metrics'=any(e.operations)))
$$;
revoke all on function postriff_private.trend_scope_readable(text),postriff_private.trend_node_valid(text,uuid),postriff_private.trend_dependency_guard() from public,anon;
grant execute on function postriff_private.trend_scope_readable(text),postriff_private.trend_node_valid(text,uuid) to authenticated,service_role;
grant usage on schema postriff_private to service_role;
do $$ declare t text; begin
 foreach t in array array['pr_trend_scopes','pr_trend_entitlements','pr_trend_provider_contracts','pr_trend_source_policies',
 'pr_trend_method_versions','pr_trend_nodes','pr_trend_observations','pr_trend_source_heads','pr_trend_dependencies',
 'pr_trend_input_manifests','pr_trend_manifest_inputs','pr_trend_manifest_chunks','pr_trend_trust_receipts','pr_trend_projections','pr_trend_watches',
 'pr_trend_deletion_tombstones','pr_trend_deletion_tasks','pr_trend_runtime_guard','pr_trend_provider_cursors','pr_trend_jobs',
 'pr_trend_ingestion_batches','pr_trend_budget_limits','pr_trend_budget_reservations','pr_trend_reservation_dimensions',
 'pr_trend_outbox','pr_trend_outbox_consumers','pr_trend_source_health','pr_trend_opportunity_decisions','pr_trend_author_tombstones'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('alter table public.%I force row level security',t);
  execute format('revoke all on public.%I from public,anon,authenticated',t);
  execute format('grant all on public.%I to service_role',t);
  execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)',t);
 end loop;
end $$;
-- Projection payload may contain permitted retained content not licensed for browser display.
-- Only the authenticated server's redacting TrendStore API exposes it; never direct PostgREST.
grant select on public.pr_trend_watches to authenticated;
create policy tenant_read on public.pr_trend_projections for select to authenticated using(
 postriff_private.trend_scope_readable(scope_key) and postriff_private.trend_node_valid(scope_key,projection_id));
create policy tenant_read on public.pr_trend_watches for select to authenticated using(postriff_private.member(workspace_id));
commit;
