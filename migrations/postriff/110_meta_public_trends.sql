-- Candidate only: independent Meta public grants and durable provider quota ledger.
-- Apply after 006 and 040. This migration grants no Meta rights or network access.
begin;

create table public.pr_trend_meta_authorizations (
 authorization_id uuid primary key,
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 connection_id text not null,
 provider_id text not null check(provider_id in ('threads','instagram','facebook')),
 operation text not null,
 source_policy_version text not null check(length(source_policy_version) between 1 and 256),
 review jsonb not null check(jsonb_typeof(review)='object' and octet_length(review::text)<=32768),
 selection jsonb not null check(jsonb_typeof(selection)='object' and octet_length(selection::text)<=32768),
 quota_rules jsonb not null check(jsonb_typeof(quota_rules)='object' and octet_length(quota_rules::text)<=4096),
 ciphertext_digest text not null check(ciphertext_digest ~ '^[a-f0-9]{64}$'),
 consent_at timestamptz not null,
 expires_at timestamptz not null,
 revoked_at timestamptz,
 foreign key(workspace_id,connection_id) references public.pr_encrypted_credentials(workspace_id,connection_id) on delete cascade,
 unique(workspace_id,provider_id,source_policy_version),
 check((provider_id,operation) in (('threads','keyword_search'),('instagram','hashtag_discovery'),('facebook','page_public_posts'))),
 check(isfinite(consent_at) and isfinite(expires_at) and expires_at>consent_at),
 check(revoked_at is null or isfinite(revoked_at))
);
create index pr_trend_meta_authorizations_connection on public.pr_trend_meta_authorizations(workspace_id,connection_id);

-- No workspace or raw query/account fields: removing a tenant, credential, grant,
-- or policy must not reset a provider's rolling account/app quota. Service code
-- uses one advisory transaction lock per bucket before count + reservation.
create table public.pr_trend_meta_quota_events (
 event_id uuid primary key default gen_random_uuid(),
 bucket_digest text not null check(bucket_digest ~ '^[a-f0-9]{64}$'),
 subject_digest text not null check(subject_digest ~ '^[a-f0-9]{64}$'),
 authorization_id uuid references public.pr_trend_meta_authorizations(authorization_id) on delete set null,
 rule_ref text not null check(length(rule_ref) between 1 and 512),
 reserved_at timestamptz not null default clock_timestamp() check(isfinite(reserved_at))
);
create index pr_trend_meta_quota_bucket_time on public.pr_trend_meta_quota_events(bucket_digest,reserved_at,subject_digest);
create index pr_trend_meta_quota_authorization on public.pr_trend_meta_quota_events(authorization_id) where authorization_id is not null;

-- Browser selections are immutable, authenticated requests, never grant edits.
create function postriff_private.trend_meta_discovery_creator_active(wid uuid,actor uuid)
 returns boolean language sql volatile security definer set search_path='' as $$
 select exists(select 1 from public.pr_memberships m join public.pr_profiles p on p.user_id=m.user_id
  join public.pr_workspaces w on w.id=m.workspace_id where m.workspace_id=wid and m.user_id=actor
  and m.status='active' and m.role in ('owner','editor') and p.deleted_at is null
  and not w.state ? 'accountDeletion')
$$;
revoke all on function postriff_private.trend_meta_discovery_creator_active(uuid,uuid) from public,anon,authenticated;
grant execute on function postriff_private.trend_meta_discovery_creator_active(uuid,uuid) to service_role;
alter table public.pr_trend_meta_authorizations add unique(workspace_id,authorization_id,provider_id,source_policy_version);
create table public.pr_trend_meta_discovery_requests (
 request_id uuid primary key,
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 creator_id uuid not null,
 authorization_id uuid not null,
 provider_id text not null check(provider_id in ('threads','instagram','facebook')),
 source_policy_version text not null,
 selection jsonb not null check(jsonb_typeof(selection)='object' and octet_length(selection::text)<=2048),
 selection_digest text not null check(selection_digest ~ '^[a-f0-9]{64}$'),
 input_digest text not null check(input_digest ~ '^[a-f0-9]{64}$'),
 idempotency_key text not null check(length(idempotency_key) between 1 and 200),
 coverage_epoch text not null unique,
 job_id uuid not null,
 created_at timestamptz not null default clock_timestamp(),
 expires_at timestamptz not null,
 unique(workspace_id,creator_id,idempotency_key),
 foreign key(workspace_id,authorization_id,provider_id,source_policy_version)
  references public.pr_trend_meta_authorizations(workspace_id,authorization_id,provider_id,source_policy_version) on delete cascade,
 check(coverage_epoch='discovery:'||request_id::text),
 check(isfinite(created_at) and isfinite(expires_at) and expires_at>created_at),
 check(case provider_id
  when 'threads' then selection ?& array['query','search_type'] and selection-array['query','search_type']='{}'::jsonb
    and jsonb_typeof(selection->'query')='string' and length(selection->>'query') between 1 and 160
    and selection->>'search_type' in ('TOP','RECENT')
  when 'instagram' then selection ? 'hashtag' and selection-'hashtag'='{}'::jsonb
    and jsonb_typeof(selection->'hashtag')='string' and length(selection->>'hashtag') between 1 and 80
  when 'facebook' then selection ? 'reviewed_page_id' and selection-'reviewed_page_id'='{}'::jsonb
    and jsonb_typeof(selection->'reviewed_page_id')='string' and selection->>'reviewed_page_id' ~ '^[0-9]{1,40}$'
  else false end)
);
create index pr_trend_meta_discovery_workspace on public.pr_trend_meta_discovery_requests(workspace_id,created_at desc);
create index pr_trend_meta_discovery_expiry on public.pr_trend_meta_discovery_requests(expires_at);
-- A native observation can occur in several request samples. Keep bounded ID
-- references separately so canonical observation dedup never overwrites lineage.
create table public.pr_trend_meta_discovery_results (
 request_id uuid primary key references public.pr_trend_meta_discovery_requests(request_id) on delete cascade,
 observation_ids uuid[] not null check(cardinality(observation_ids)<=1000 and array_position(observation_ids,null) is null),
 retrieved_at timestamptz not null default clock_timestamp() check(isfinite(retrieved_at)),
 completeness text not null check(completeness in ('partial','gap'))
);

create function postriff_private.trend_meta_discovery_immutable() returns trigger
 language plpgsql set search_path='' as $$
begin raise exception 'meta_discovery_immutable' using errcode='23514'; end $$;
create trigger pr_trend_meta_discovery_requests_immutable before update on public.pr_trend_meta_discovery_requests
 for each row execute function postriff_private.trend_meta_discovery_immutable();
create trigger pr_trend_meta_discovery_results_immutable before update on public.pr_trend_meta_discovery_results
 for each row execute function postriff_private.trend_meta_discovery_immutable();
revoke all on function postriff_private.trend_meta_discovery_immutable() from public,anon,authenticated;

do $$ declare t text; begin
 foreach t in array array['pr_trend_meta_authorizations','pr_trend_meta_quota_events',
   'pr_trend_meta_discovery_requests','pr_trend_meta_discovery_results'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('alter table public.%I force row level security',t);
  execute format('revoke all on public.%I from public,anon,authenticated',t);
  execute format('grant all on public.%I to service_role',t);
  execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)',t);
 end loop;
end $$;

create function postriff_private.trend_meta_authorization_immutable() returns trigger
language plpgsql set search_path='' as $$
begin
 if (to_jsonb(new)-'revoked_at') is distinct from (to_jsonb(old)-'revoked_at')
    or (old.revoked_at is not null and new.revoked_at is distinct from old.revoked_at) then
  raise exception 'meta_public_authorization_immutable' using errcode='23514';
 end if;
 return new;
end $$;
create trigger pr_trend_meta_authorizations_immutable before update on public.pr_trend_meta_authorizations
 for each row execute function postriff_private.trend_meta_authorization_immutable();

-- Current validity is independent of caller-supplied timestamps. Invalid JSON,
-- missing proof fields, malformed instants and changed custody all fail closed.
-- Plaintext token fingerprints are rechecked by the server vault on dispatch;
-- SQL binds reads to the immutable ciphertext digest and current scopes/account.
create function postriff_private.trend_meta_authorization_valid(id uuid) returns boolean
language plpgsql volatile security definer set search_path='' as $$
declare a record; proof jsonb; required jsonb; checked_at timestamptz:=clock_timestamp();
begin
 select g.*,c.provider as credential_provider,c.provider_account_id,c.scopes,
   c.access_ciphertext,c.key_id,c.access_expires_at,c.revoked_at as credential_revoked_at,w.state as workspace_state
 into a from public.pr_trend_meta_authorizations g
 join public.pr_encrypted_credentials c using(workspace_id,connection_id)
 join public.pr_workspaces w on w.id=g.workspace_id where g.authorization_id=$1;
 if not found then return false; end if;
 proof:=a.review;
 required:=case a.provider_id when 'threads' then '["threads_basic","threads_keyword_search"]'::jsonb
  when 'instagram' then '["instagram_basic"]'::jsonb
  when 'facebook' then '[]'::jsonb else null end;
 if a.revoked_at is not null or a.credential_revoked_at is not null or a.workspace_state ? 'accountDeletion'
    or exists(select 1 from public.pr_trend_source_health h
       where h.scope_key='workspace:'||a.workspace_id::text and h.provider_id=a.provider_id and h.status='revoked')
    or a.credential_provider<>'meta_public_'||a.provider_id
    or a.consent_at>checked_at or a.expires_at<=checked_at
    or a.access_expires_at is null or a.access_expires_at<=checked_at
    or length(a.access_ciphertext)=0 or length(a.key_id)=0
    or encode(sha256(convert_to(a.access_ciphertext,'UTF8')),'hex')<>a.ciphertext_digest then return false; end if;
 if jsonb_typeof(proof->'verified_scopes') is distinct from 'array'
    or jsonb_typeof(proof->'approved_scopes') is distinct from 'array'
    or jsonb_typeof(proof->'approved_features') is distinct from 'array'
    or jsonb_typeof(proof->'reviewed_page_ids') is distinct from 'array' then return false; end if;
 return coalesce(
  proof->>'review_id'=a.authorization_id::text
  and proof->>'scope_key'='workspace:'||a.workspace_id::text
  and proof->>'provider_id'=a.provider_id and proof->>'operation'=a.operation
  and proof->>'account_id'=a.provider_account_id and proof->>'account_id' ~ '^[0-9]{1,40}$'
  and proof->>'app_id' ~ '^[0-9]{1,40}$' and proof->>'token_fingerprint' ~ '^[a-f0-9]{64}$'
  and proof->'consent_current'='true'::jsonb
  and length(proof->>'review_ref') between 1 and 512 and length(proof->>'quota_rule_ref') between 1 and 512
  and (proof->>'verified_at')::timestamptz<=checked_at
  and checked_at<=(proof->>'verified_at')::timestamptz+interval '15 minutes'
  and checked_at<(proof->>'expires_at')::timestamptz
  and (proof->>'expires_at')::timestamptz<=a.access_expires_at
  and (proof->>'expires_at')::timestamptz<=a.expires_at
  and proof->'verified_scopes' @> to_jsonb(a.scopes) and to_jsonb(a.scopes) @> (proof->'verified_scopes')
  and jsonb_array_length(proof->'verified_scopes')=cardinality(a.scopes)
  and proof->'verified_scopes' @> required and proof->'approved_scopes' @> required
  and jsonb_typeof(proof->'quota_limit')='number' and (proof->>'quota_limit')::integer between 1 and 1000000
  and jsonb_typeof(proof->'quota_window_seconds')='number' and (proof->>'quota_window_seconds')::integer between 1 and 604800
  and a.quota_rules->(case a.provider_id when 'threads' then 'threads_keyword_search'
       when 'instagram' then 'instagram_distinct_hashtag_7d' else 'facebook_public_page_read' end)
      =jsonb_build_object('limit',(proof->>'quota_limit')::integer,'window_seconds',(proof->>'quota_window_seconds')::integer)
  and case a.provider_id
   when 'threads' then proof->>'login_kind'='threads_login' and proof->>'account_kind'='user'
     and proof->>'api_version'='v1.0'
     and length(a.selection->>'query') between 1 and 160 and a.selection->>'search_type' in ('TOP','RECENT')
   when 'instagram' then proof->>'login_kind'='facebook_login' and proof->>'account_kind' in ('business','creator')
     and proof->>'api_version'='v24.0'
     and proof->'approved_features' @> '["instagram_public_content_access"]'::jsonb
     and a.selection->>'ig_user_id'=a.provider_account_id and length(a.selection->>'hashtag') between 1 and 80
     and (proof->>'quota_limit')::integer<=30 and (proof->>'quota_window_seconds')::integer=604800
   when 'facebook' then proof->>'login_kind'='facebook_login' and proof->>'account_kind' in ('app','system_user')
     and proof->>'api_version'='v24.0'
     and proof->'approved_features' @> '["pages_public_content_access"]'::jsonb
     and proof->'reviewed_page_ids' @> jsonb_build_array(a.selection->>'reviewed_page_id')
     and a.selection->>'reviewed_page_id' ~ '^[0-9]{1,40}$'
     and proof->'page_public'='true'::jsonb and proof->'page_restricted'='false'::jsonb
   else false end,false);
exception when others then return false;
end $$;

-- Bind evidence to the exact reviewed policy AND provenance. An unrelated valid
-- grant, even within the same workspace, never repairs historical evidence.
create function postriff_private.trend_meta_observation_valid(s text,pid text,policy_version text,provenance jsonb)
 returns boolean language plpgsql volatile security definer set search_path='' as $$
declare reviewed_operation text;
begin
 if pid not in ('threads','instagram','facebook') then return true; end if;
 select p.manifest->>'operation' into reviewed_operation from public.pr_trend_source_policies p
  where (p.scope_key,p.provider_id,p.version)=(s,pid,policy_version);
 -- Owned analytics and separately licensed operations keep their own contracts.
 -- This gate applies only to these three public discovery operation identities.
 if (pid,reviewed_operation) not in (('threads','keyword_search'),('instagram','hashtag_discovery'),('facebook','page_public_posts'))
  then return true; end if;
 return exists(select 1 from public.pr_trend_source_policies p
   join public.pr_trend_meta_authorizations a on a.authorization_id::text=p.manifest->>'meta_authorization_id'
   where (p.scope_key,p.provider_id,p.version)=(s,pid,policy_version)
    and a.authorization_id::text=provenance->>'review_id'
    and a.workspace_id::text=substring(s from 11) and s='workspace:'||a.workspace_id::text
    and a.provider_id=pid and a.source_policy_version=policy_version
    and a.operation=p.manifest->>'operation'
    and jsonb_typeof(a.selection->'reviewed_policy')='object'
    and a.selection->'reviewed_policy'->>'policy_id'=p.manifest->>'id'
    and a.selection->'reviewed_policy'->>'version'=p.version
    and a.selection->'reviewed_policy'->>'scope_key'=p.scope_key
    and a.selection->'reviewed_policy'->>'provider_id'=p.provider_id
    and a.selection->'reviewed_policy'->>'operation'=p.manifest->>'operation'
    and a.selection->'reviewed_policy'->'rights'=p.rights
    and a.selection->'reviewed_policy'->'rights'=p.manifest->'rights'
    and jsonb_typeof(a.selection->'reviewed_policy'->'max_retention_seconds')='number'
    and (a.selection->'reviewed_policy'->>'max_retention_seconds')::integer>0
    and p.max_retention_seconds<=(a.selection->'reviewed_policy'->>'max_retention_seconds')::integer
    and (p.manifest->>'retention_seconds')::integer>0
    and (p.manifest->>'retention_seconds')::integer<=(a.selection->'reviewed_policy'->>'max_retention_seconds')::integer
    and postriff_private.trend_meta_authorization_valid(a.authorization_id));
exception when others then return false;
end $$;

-- Empty and queued samples have no observation node to supply these lifecycle
-- checks. One current predicate gates dispatch, receipts and physical cleanup.
create function postriff_private.trend_meta_discovery_request_valid(id uuid)
 returns boolean language sql volatile security definer set search_path='' as $$
 select coalesce((select g.reads_ready from public.pr_trend_runtime_guard g where g.singleton),false)
 and exists(select 1 from public.pr_trend_meta_discovery_requests r
  join public.pr_trend_scopes s on s.scope_key='workspace:'||r.workspace_id::text
  join public.pr_trend_source_policies p on (p.scope_key,p.provider_id,p.version)=
   (s.scope_key,r.provider_id,r.source_policy_version)
  join public.pr_trend_provider_contracts c on (c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
  where r.request_id=id and s.enabled and r.expires_at>clock_timestamp()
   and postriff_private.trend_meta_discovery_creator_active(r.workspace_id,r.creator_id)
   and p.revoked_at is null and p.readiness='ready' and p.valid_from<=clock_timestamp() and p.expires_at>clock_timestamp()
   and c.revoked_at is null and c.valid_from<=clock_timestamp() and c.expires_at>clock_timestamp()
   and array['retrieve','store_metrics','derive_metrics','retain_derivatives']::text[] <@ p.operations
   and array['retrieve','store_metrics','derive_metrics','retain_derivatives']::text[] <@ c.operations
   and not exists(select 1 from unnest(array['retrieve','store_metrics','derive_metrics','retain_derivatives']) op
     where not postriff_private.trend_permits(p.rights,op,p.scope_key))
   and postriff_private.trend_meta_observation_valid(p.scope_key,p.provider_id,p.version,
     jsonb_build_object('review_id',r.authorization_id::text)))
$$;
revoke all on function postriff_private.trend_meta_discovery_request_valid(uuid) from public,anon,authenticated;
grant execute on function postriff_private.trend_meta_discovery_request_valid(uuid) to service_role;

revoke all on function postriff_private.trend_meta_authorization_immutable(),
 postriff_private.trend_meta_authorization_valid(uuid),
 postriff_private.trend_meta_observation_valid(text,text,text,jsonb) from public,anon,authenticated;
grant execute on function postriff_private.trend_meta_authorization_valid(uuid),
 postriff_private.trend_meta_observation_valid(text,text,text,jsonb) to service_role;

-- Preserve every 040 trust clause; current Meta custody also gates every ancestor.
create or replace function postriff_private.trend_node_valid(s text,n uuid) returns boolean language sql volatile security definer set search_path='' as $$
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
    or not postriff_private.trend_meta_observation_valid(o.scope_key,o.provider_id,o.source_policy_version,o.provenance)
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

commit;
