-- Local deterministic short audio, bound to one immutable private report version.
-- Existing database only; no bucket, cloud synthesis or paid storage service.
begin;
create table if not exists public.pr_agent_team_audio_assets (
  report_key text not null check (report_key ~ '^agent-team:v1:20[0-9]{2}-[0-9]{2}-[0-9]{2}:whole_day$'),
  fingerprint text not null check (fingerprint ~ '^[0-9a-f]{64}$'),
  report_version integer not null check (report_version between 1 and 9999),
  summary_hash text not null check (summary_hash ~ '^[0-9a-f]{64}$'),
  narration_hash text not null check (narration_hash ~ '^[0-9a-f]{64}$'),
  excerpt boolean not null,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  mime text not null check (mime = 'audio/wav'),
  producer text not null check (producer = 'macos_say_sinji'),
  observed_at timestamptz not null,
  byte_count integer not null check (byte_count between 44 and 2097152),
  duration_ms integer not null check (duration_ms between 1 and 45000),
  wav_data bytea not null check (octet_length(wav_data) = byte_count),
  created_at timestamptz not null default now(),
  primary key (report_key,fingerprint),
  foreign key (report_key,fingerprint) references public.pr_agent_team_reports(report_key,fingerprint)
);
alter table public.pr_agent_team_audio_assets enable row level security;
alter table public.pr_agent_team_audio_assets force row level security;
revoke all on public.pr_agent_team_audio_assets from public,anon,authenticated,service_role;
grant select,insert on public.pr_agent_team_audio_assets to service_role;
do $$ begin
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_agent_team_audio_assets' and policyname='service_read') then
    create policy service_read on public.pr_agent_team_audio_assets for select to service_role using(true);
  end if;
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_agent_team_audio_assets' and policyname='service_insert') then
    create policy service_insert on public.pr_agent_team_audio_assets for insert to service_role with check(true);
  end if;
end $$;
commit;
