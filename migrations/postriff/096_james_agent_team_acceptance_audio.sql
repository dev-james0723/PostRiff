-- Accept the explicit staging as-of-now identity; existing whole-day assets remain valid.
-- No rows, grants, RLS policies, retention or byte/duration bounds change.
begin;
alter table public.pr_agent_team_audio_assets
  drop constraint pr_agent_team_audio_assets_report_key_check;
alter table public.pr_agent_team_audio_assets
  add constraint pr_agent_team_audio_assets_report_key_check check (
    report_key ~ '^agent-team:v1:20[0-9]{2}-[0-9]{2}-[0-9]{2}:whole_day$'
    or report_key ~ '^agent-team:acceptance:v1:20[0-9]{2}-[0-9]{2}-[0-9]{2}:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:half_day$'
  );
commit;
