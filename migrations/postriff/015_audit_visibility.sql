-- Match audit access to the API and navigation. No expiry or retention deletion is introduced.
-- Local candidate; production application requires explicit approval.
begin;
drop policy if exists audit_tenant_read on public.pr_audit_events;
drop policy if exists audit_admin_read on public.pr_audit_events;
create policy audit_admin_read on public.pr_audit_events for select to authenticated using (
  workspace_id is not null and postriff_private.member(workspace_id) and exists (
    select 1 from public.pr_memberships m
    where m.workspace_id=pr_audit_events.workspace_id and m.user_id=(select auth.uid())
      and m.status='active' and m.role in ('admin','owner')
  )
);
commit;
