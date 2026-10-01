-- RAFII Product Growth v2 · G1-INTAKE (PRD R-FWR-04): bounded raw-file intake.
-- A PDF or audio recording goes straight to private storage through a signed URL; the server verifies it, a durable
-- leased job extracts its text (or transcribes it through an approved, quoted route), the person reviews and corrects
-- that text, and only then does it become a canonical source. Additive and idempotent; apply after 050.
-- Rollback = RAFII_SOURCE_UPLOADS_ENABLED off (admission stops; retention and storage purges keep running).
begin;

create table if not exists public.pr_source_uploads (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  kind text not null check (kind in ('audio','pdf','transcript')),
  state text not null check (state in ('pending','committed','rejected','cancelled','deleted')),
  -- 'none': a pasted transcript file has no stored object. Deletion is two-phase through pr_source_upload_purges.
  object_state text not null check (object_state in ('none','awaiting','present','deleting','deleted')),
  bucket text check (bucket is null or bucket ~ '^[a-z0-9-]{3,63}$'),
  object_name text check (object_name is null or object_name ~ '^[0-9a-f]{32}\.(pdf|wav|mp3|m4a|ogg)$'),
  display_name text check (display_name is null or length(display_name) <= 200),
  declared_mime text check (declared_mime is null or length(declared_mime) <= 100),
  mime text check (mime is null or mime in ('application/pdf','audio/wav','audio/mpeg','audio/mp4','audio/ogg','text/plain')),
  sniffed_type text check (sniffed_type is null or sniffed_type in ('pdf','wav','mp3','m4a','ogg','srt','vtt','txt')),
  declared_bytes bigint check (declared_bytes is null or declared_bytes > 0),
  bytes bigint check (bytes is null or bytes >= 0),
  sha256 text check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$'),
  etag text check (etag is null or length(etag) <= 200),
  duration_seconds numeric(10,3) check (duration_seconds is null or duration_seconds >= 0),
  limits jsonb not null default '{}'::jsonb check (jsonb_typeof(limits) = 'object' and octet_length(limits::text) <= 2048),
  reason_code text check (reason_code is null or reason_code ~ '^[a-z][a-z0-9_]{0,59}$'),
  begin_key text check (begin_key is null or length(begin_key) between 8 and 80),
  begin_digest text check (begin_digest is null or begin_digest ~ '^[0-9a-f]{64}$'),
  created_by uuid not null,
  token_expires_at timestamptz,
  committed_at timestamptz,
  retain_until timestamptz,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, id)
);
create unique index if not exists pr_source_uploads_begin_key on public.pr_source_uploads (workspace_id, begin_key) where begin_key is not null;
create index if not exists pr_source_uploads_recent on public.pr_source_uploads (workspace_id, created_at desc, id desc);
create index if not exists pr_source_uploads_owner on public.pr_source_uploads (workspace_id, created_by, state);
create index if not exists pr_source_uploads_retention on public.pr_source_uploads (object_state, retain_until) where object_state in ('awaiting','present');

create table if not exists public.pr_source_upload_jobs (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  upload_id uuid not null,
  kind text not null check (kind in ('pdf_text','transcription','transcript_text')),
  state text not null check (state in ('queued','running','needs_review','completed','failed','cancelled','unsupported')),
  reason_code text check (reason_code is null or reason_code ~ '^[a-z][a-z0-9_]{0,59}$'),
  attempts integer not null default 0 check (attempts >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 3),
  lease_owner text check (lease_owner is null or length(lease_owner) <= 80),
  lease_until timestamptz,
  lease_generation integer not null default 0 check (lease_generation >= 0),
  cancel_requested boolean not null default false,
  progress jsonb not null default '{}'::jsonb check (jsonb_typeof(progress) = 'object' and octet_length(progress::text) <= 8192),
  idempotency_key text not null check (length(idempotency_key) between 8 and 120),
  pages_from integer check (pages_from is null or pages_from >= 1),
  pages_to integer check (pages_to is null or pages_to >= pages_from),
  -- Paid transcription only: quote accepted → reserved before any provider I/O; settled/released/unknown after.
  quote_state text not null default 'not_required' check (quote_state in ('not_required','required','reserved','settled','released','unknown')),
  quote jsonb not null default '{}'::jsonb check (jsonb_typeof(quote) = 'object' and octet_length(quote::text) <= 2048),
  reservation_id uuid,
  dispatched_at timestamptz,
  result_id uuid,
  current_revision integer not null default 0 check (current_revision >= 0),
  reviewed_revision integer check (reviewed_revision is null or reviewed_revision >= 0),
  source_id text check (source_id is null or length(source_id) <= 80),
  source_key text check (source_key is null or length(source_key) between 8 and 120),
  created_by uuid not null,
  due_at timestamptz not null default now(),
  review_expires_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint pr_source_upload_jobs_attempts check (attempts <= max_attempts),
  unique (workspace_id, id),
  unique (workspace_id, upload_id),
  unique (workspace_id, idempotency_key),
  foreign key (workspace_id, upload_id) references public.pr_source_uploads(workspace_id, id) on delete cascade
);
create index if not exists pr_source_upload_jobs_due on public.pr_source_upload_jobs (state, due_at, id) where state in ('queued','running');
create index if not exists pr_source_upload_jobs_review on public.pr_source_upload_jobs (review_expires_at) where state in ('queued','needs_review');
create index if not exists pr_source_upload_jobs_sources on public.pr_source_upload_jobs (workspace_id, source_id) where source_id is not null;

-- Extraction output: immutable once written. A correction is a new revision, never an edit of this row.
create table if not exists public.pr_source_upload_results (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  job_id uuid not null,
  kind text not null check (kind in ('pdf_text','transcript')),
  text text not null check (length(text) <= 60000),
  char_count integer not null check (char_count between 0 and 60000),
  digest text not null check (digest ~ '^[0-9a-f]{64}$'),
  page_count integer check (page_count is null or page_count >= 0),
  pages_from integer,
  pages_to integer,
  pages jsonb not null default '[]'::jsonb check (jsonb_typeof(pages) = 'array' and octet_length(pages::text) <= 8192),
  duration_seconds numeric(10,3),
  injection_flags jsonb not null default '[]'::jsonb check (jsonb_typeof(injection_flags) = 'array' and octet_length(injection_flags::text) <= 4096),
  synthetic boolean not null default false,
  provider text check (provider is null or length(provider) <= 80),
  model text check (model is null or length(model) <= 120),
  created_at timestamptz not null default now(),
  unique (workspace_id, id),
  foreign key (workspace_id, job_id) references public.pr_source_upload_jobs(workspace_id, id) on delete cascade
);
create index if not exists pr_source_upload_results_job on public.pr_source_upload_results (workspace_id, job_id);

create table if not exists public.pr_source_upload_revisions (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  result_id uuid not null,
  revision integer not null check (revision >= 1),
  text text not null check (length(text) <= 60000),
  char_count integer not null check (char_count between 0 and 60000),
  digest text not null check (digest ~ '^[0-9a-f]{64}$'),
  idempotency_key text not null check (length(idempotency_key) between 8 and 80),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  unique (workspace_id, result_id, revision),
  unique (workspace_id, idempotency_key),
  foreign key (workspace_id, result_id) references public.pr_source_upload_results(workspace_id, id) on delete cascade
);

-- Storage deletions still to do. No workspace foreign key on purpose: the queue must outlive an account deletion,
-- whose cascade removes the upload rows (the trigger below records their objects first). Service role only.
create table if not exists public.pr_source_upload_purges (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  upload_id uuid not null,
  bucket text not null check (bucket ~ '^[a-z0-9-]{3,63}$'),
  object_name text not null check (object_name ~ '^[0-9a-f]{32}\.(pdf|wav|mp3|m4a|ogg)$'),
  reason text not null check (reason ~ '^[a-z][a-z0-9_]{0,39}$'),
  attempts integer not null default 0 check (attempts >= 0),
  last_error text check (last_error is null or length(last_error) <= 200),
  not_before timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create index if not exists pr_source_upload_purges_due on public.pr_source_upload_purges (not_before, id);

create or replace function postriff_private.source_upload_rows_immutable() returns trigger language plpgsql set search_path='' as $$
begin
  raise exception 'Source upload results and revisions are immutable' using errcode = '42501';
end $$;
create or replace trigger pr_source_upload_results_immutable before update on public.pr_source_upload_results
  for each row execute function postriff_private.source_upload_rows_immutable();
create or replace trigger pr_source_upload_revisions_immutable before update on public.pr_source_upload_revisions
  for each row execute function postriff_private.source_upload_rows_immutable();

-- Any removal of an upload row whose object may still exist (account deletion cascades included) queues its
-- storage deletion; a pending signed URL can still write until it expires, so that object is deleted again after.
create or replace function postriff_private.source_upload_purge_on_delete() returns trigger language plpgsql set search_path='' as $$
begin
  if old.object_name is not null and old.object_state in ('awaiting','present','deleting') then
    insert into public.pr_source_upload_purges(workspace_id, upload_id, bucket, object_name, reason, not_before)
      values (old.workspace_id, old.id, old.bucket, old.object_name, 'row_deleted', now());
    if old.object_state = 'awaiting' and old.token_expires_at is not null and old.token_expires_at > now() then
      insert into public.pr_source_upload_purges(workspace_id, upload_id, bucket, object_name, reason, not_before)
        values (old.workspace_id, old.id, old.bucket, old.object_name, 'row_deleted', old.token_expires_at + interval '1 hour');
    end if;
  end if;
  return old;
end $$;
create or replace trigger pr_source_uploads_purge_on_delete after delete on public.pr_source_uploads
  for each row execute function postriff_private.source_upload_purge_on_delete();
revoke all on function postriff_private.source_upload_rows_immutable() from public, anon, authenticated;
revoke all on function postriff_private.source_upload_purge_on_delete() from public, anon, authenticated;

-- Members read their workspace's rows (the API is the only writer); the purge queue is service-only.
do $$
declare t text;
begin
  foreach t in array array['pr_source_uploads','pr_source_upload_jobs','pr_source_upload_results','pr_source_upload_revisions'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('drop policy if exists tenant_read on public.%I', t);
    execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))', t);
    execute format('drop policy if exists trusted_write on public.%I', t);
    execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
end $$;
alter table public.pr_source_upload_purges enable row level security;
alter table public.pr_source_upload_purges force row level security;
revoke all on public.pr_source_upload_purges from public, anon, authenticated;
grant all on public.pr_source_upload_purges to service_role;
drop policy if exists service_only on public.pr_source_upload_purges;
create policy service_only on public.pr_source_upload_purges for all to service_role using (true) with check (true);

commit;
