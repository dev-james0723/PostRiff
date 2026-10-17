-- Reuse the native observation/scheduler tables. No body, reach or impressions.
begin;
alter table public.pr_metric_reads drop constraint if exists pr_metric_reads_provider_check;
alter table public.pr_metric_reads add constraint pr_metric_reads_provider_check check (provider in ('threads','instagram','mastodon'));
insert into public.pr_metric_definitions(provider,metric,native_name,definition_version,unit,scope,definition_url) values
 ('mastodon','likes','favourites_count','2026-09','count','instance-observed post','https://docs.joinmastodon.org/entities/Status/'),
 ('mastodon','reposts','reblogs_count','2026-09','count','instance-observed post','https://docs.joinmastodon.org/entities/Status/'),
 ('mastodon','replies','replies_count','2026-09','count','instance-observed post','https://docs.joinmastodon.org/entities/Status/')
on conflict (provider,metric,definition_version) do nothing;
create index if not exists pr_mastodon_metrics_retention on public.pr_metric_observations(observed_at,id) where provider='mastodon';
create index if not exists pr_mastodon_reads_retention on public.pr_metric_reads(updated_at,id) where provider='mastodon' and status in ('done','cancelled','dead','unavailable');
create index if not exists pr_mastodon_actions_retention on public.pr_mastodon_actions(created_at,id);
create index if not exists pr_mastodon_actions_recovery on public.pr_mastodon_actions(updated_at,id) where status='running';
commit;
