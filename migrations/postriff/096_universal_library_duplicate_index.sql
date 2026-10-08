-- Keep canonical asset deletion bounded when duplicate uploads reference it.
begin;
create index if not exists pr_library_assets_duplicate_of
  on public.pr_library_assets(duplicate_of)
  where duplicate_of is not null;
commit;
