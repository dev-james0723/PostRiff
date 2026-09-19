-- Raw ledger amounts are owner-only. Other members read the API's redacted usage projection.
-- Local candidate: production application requires explicit approval.
begin;
drop policy if exists ledger_tenant_read on public.pr_usage_ledger;
drop policy if exists ledger_owner_read on public.pr_usage_ledger;
create policy ledger_owner_read on public.pr_usage_ledger for select to authenticated using (
  postriff_private.member(workspace_id) and exists (
    select 1 from public.pr_memberships m
    where m.workspace_id=pr_usage_ledger.workspace_id and m.user_id=(select auth.uid())
      and m.status='active' and m.role='owner'
  )
);
commit;
