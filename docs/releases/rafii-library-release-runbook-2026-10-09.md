# Rafii Library release runbook (2026-10-09)

James approved a **full release** on 2026-10-09: migration 104 to staging, then production, then merge #144 (one production deploy, every Library flag off), production smoke, and a recorded rollback target. This approval overrides the 2026-09-25 rule that only Extra High may run releases, for this release only.

## Preconditions

1. **OpenUI hold lifted.** The "Rafii × OpenUI 正式版發佈" session asked for no production change until it sends "hold lifted". That covers this migration and any runner build. The session will send the final production deployment ID, which becomes the rollback target.
2. **Release head validated.** The release head is #144 = `claude/rafii-intelligent-library-20261008` @ `7737d63c`, the same tree as redesign head `62ff1cbd`. It includes consumer-saas `4a0bd786`.
   - The redesign alone passed on Depot (`rjzngvv5pw`, at `ea99149e`).
   - The release head's Depot run is `q88fqk426t`; check that it finished.
   - Check that #144's GitHub checks are green.
3. **Permissions in this Claude session.** The auto-mode classifier blocked each of these. James either adds the rules or runs the steps himself.
   - `mcp__b0806f46-cf3a-435e-9ef7-9eabce22542a__apply_migration`: staging and production migration.
   - `mcp__b0806f46-cf3a-435e-9ef7-9eabce22542a__execute_sql`: read-only checks before and after.
   - Bash `gh pr merge`: merging #144.

## Projects

| | Supabase project | Library migrations present (2026-10-09) |
|---|---|---|
| Production | `buoyhkbodnhzngaotoel` (postriff-phase2-private, PG 17) | universal_library, _lifecycle, _storage, _duplicate_index (093–096); 097, 098, 102, 103 |
| Staging | `oxacvkhpfgytkepxcaqh` (rafii-consumer-staging, PG 17) | 093 plus the verified lifecycle and storage releases; `duplicate_of` present. The 104 columns are absent. `vector` 0.8.2 is available but not installed. |

## Steps

Run every step on staging first, then repeat it on production.

1. **Read-only probe**, with `execute_sql`:
   ```sql
   select (select json_agg(json_build_object('name',e.extname,'schema',n.nspname)) from pg_extension e join pg_namespace n on n.oid=e.extnamespace where e.extname='vector') as vector_installed,
          (select json_object_agg(c, exists(select 1 from information_schema.columns where table_schema='public' and table_name='pr_library_assets' and column_name=c)) from unnest(array['lineage_id','version_no','source_kind','media','duplicate_of']) c) as columns,
          to_regclass('public.pr_library_policy') is not null as has_104;
   ```
   Expect `duplicate_of = true` (096 is applied) and `has_104 = false`.
2. **pgvector in `extensions`.** Run `apply_migration`, name `library_intelligence_104_vector_extension`, with:
   ```sql
   create extension if not exists vector with schema extensions;
   ```
   This keeps the extension out of `public`. 104's own `create extension if not exists vector` then does nothing.
3. **Migration 104.** Run `apply_migration`, name `library_intelligence_104`, with the exact committed file `migrations/postriff/104_library_intelligence.sql`.
   - sha256: `07de2f2b9945443fa53095ab6967b0c53d36c086d5f615e276c6d66c07c23cf2`
   - Remove only its unindented `begin;` and `commit;` lines, because `apply_migration` supplies the transaction. The repo runner (`scripts/postriff_migrate.py`, `body()`) strips the same lines.
   - The migration is additive and idempotent.
4. **Verify**, with `execute_sql`:
   ```sql
   select t, c.relrowsecurity as rls, c.relforcerowsecurity as forced,
          exists(select 1 from pg_policies p where p.schemaname='public' and p.tablename=t and p.policyname='service_only') as service_only,
          has_table_privilege('authenticated', 'public.'||t, 'select') as authenticated_select,
          has_table_privilege('anon', 'public.'||t, 'select') as anon_select
   from unnest(array['pr_library_policy','pr_library_grants','pr_library_capabilities','pr_library_jobs','pr_library_segments',
     'pr_library_annotations','pr_library_embeddings','pr_library_collection_overrides','pr_library_collection_revisions',
     'pr_library_relations','pr_library_voice_samples','pr_library_source_packs','pr_library_artifacts',
     'pr_library_suggestions','pr_library_suggestion_prefs','pr_library_usage_events','pr_library_action_receipts','pr_library_metrics']) t
   join pg_class c on c.oid = to_regclass('public.'||t);
   ```
   - Expect 18 rows, each with `rls = forced = service_only = true` and `authenticated_select = anon_select = false`.
   - Also check that `pr_library_embeddings.embedding` exists and that both HNSW indexes exist (`pr_library_embeddings_text_1024`, `pr_library_embeddings_visual_256`).
5. **Advisors.** Run `get_advisors` with `security` and with `performance`. Expect no new Library findings.
6. **Merge.** Production only, after the hold lifts.
   - Merge #144 into consumer-saas (merge commit). This is one production deploy.
   - Every `RAFII_LIBRARY_*` flag stays unset, and so does `RAFII_LIBRARY_TASK_UI_ENABLED` until the OpenUI registration seam lands.
7. **Production smoke** (flags off):
   - Health, catalog and models answer 200.
   - `/app/library` renders.
   - Existing upload, list, detail, download and delete still work (the Library acceptance covers these flows in CI).
   - Runtime error logs are empty.
   - `vercel inspect` shows the merge SHA.
8. **Record the result.**
   - Note the new production deployment ID and the rollback target (the OpenUI final ID) in `docs/releases/rafii-intelligent-library-2026-10-08.md`.
   - Tell the OpenUI session.

## Rollback

1. Leave the flags off.
2. Promote the previous production deployment (Vercel Instant Rollback).
3. **Do not drop the 104 tables.** They hold derived data and consent records. Nothing in 104 modifies an existing row, and the previous build ignores the new tables and columns.

## Still blocked on James (not part of this release)

- **Paid provider evaluation** (A017, A018, A022, A023, A026, A032), capped at US$10. It needs `~/.config/rafii-library-eval/provider.env` containing `AI_GATEWAY_API_KEY` and `OPENAI_API_KEY`. The eval reads credentials only from that file.
- **A066 real iPhone Safari smoke.** It needs James's device; see `evidence/iphone-smoke.md`.
- **Flag enablement** after release, one flag at a time, as in the canary plan.
