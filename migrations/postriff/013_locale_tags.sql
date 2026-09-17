-- Languages per channel (docs/postriff-worldwide-languages-plan.md §6). Apply after 012.
--
-- Learned-preference scopes were keyed by the old language values English / 繁體中文; they are
-- locale tags now (en / zh-Hant). Scope keys read type|rule|polarity|platform|language|contentType.
-- Rewriting them here keeps a remembered rule applying, keeps a dismissal suppressing the same
-- proposal, and lets a new version replace the old one instead of sitting beside it.
--
-- Not rewritten, on purpose: pr_learning_events.scope (read through locales.canonical until its
-- 180-day TTL ends) and every hashed value (approval manifests, run artifacts), which keep the
-- language they were approved with.

begin;

create temporary table locale_tag_renames (legacy text primary key, tag text not null) on commit drop;
insert into locale_tag_renames values ('English', 'en'), ('繁體中文', 'zh-Hant');

-- The canonical key for a legacy one.
create or replace function pg_temp.locale_scope_key(scope_key text) returns text language sql immutable as $$
  select case when r.tag is null then scope_key else concat_ws('|',
    split_part(scope_key, '|', 1), split_part(scope_key, '|', 2), split_part(scope_key, '|', 3),
    split_part(scope_key, '|', 4), r.tag, split_part(scope_key, '|', 6)) end
  from (select 1) one left join locale_tag_renames r on r.legacy = split_part(scope_key, '|', 5)
$$;

update public.pr_memory_proposals p
set scope_key = pg_temp.locale_scope_key(p.scope_key),
    body = case when p.body ? 'scope' then
             jsonb_set(jsonb_set(p.body, '{scopeKey}', to_jsonb(pg_temp.locale_scope_key(p.scope_key))), '{scope,language}', to_jsonb(r.tag), false)
           else jsonb_set(p.body, '{scopeKey}', to_jsonb(pg_temp.locale_scope_key(p.scope_key))) end
from locale_tag_renames r
where r.legacy = split_part(p.scope_key, '|', 5);

-- One current version per scope key: if a current version already uses the new key (it cannot before
-- this release, but a re-run must not fail), the legacy one is retired rather than colliding.
update public.pr_memory_versions v
set status = 'retired', valid_to = now()
where v.valid_to is null
  and split_part(v.scope_key, '|', 5) in (select legacy from locale_tag_renames)
  and exists (select 1 from public.pr_memory_versions w
              where w.workspace_id = v.workspace_id and w.valid_to is null and w.id <> v.id
                and w.scope_key = pg_temp.locale_scope_key(v.scope_key));

update public.pr_memory_versions v
set scope_key = pg_temp.locale_scope_key(v.scope_key),
    body = case when v.body ? 'scope' then
             jsonb_set(jsonb_set(v.body, '{scopeKey}', to_jsonb(pg_temp.locale_scope_key(v.scope_key))), '{scope,language}', to_jsonb(r.tag), false)
           else jsonb_set(v.body, '{scopeKey}', to_jsonb(pg_temp.locale_scope_key(v.scope_key))) end
from locale_tag_renames r
where r.legacy = split_part(v.scope_key, '|', 5)
  and not (v.valid_to is null and exists (select 1 from public.pr_memory_versions w
           where w.workspace_id = v.workspace_id and w.valid_to is null and w.id <> v.id
             and w.scope_key = pg_temp.locale_scope_key(v.scope_key)));

commit;
