-- Read-only Control continuation. Apply only with separate hosted migration authorization.
-- Local synthetic values do not activate the proposed metric/financial policies.
begin;
alter table rafii_control.admin_audit_log add column if not exists error_code text
  check(error_code in ('AUTH_REQUIRED','FOUNDER_REQUIRED','STEP_UP_REQUIRED','SCOPE_DENIED','VALIDATION_FAILED','SOURCE_UNAVAILABLE','RATE_LIMITED','BUDGET_EXCEEDED','IDEMPOTENCY_CONFLICT','STALE_PREVIEW'));
alter table rafii_control.query_receipts add column if not exists result_rows jsonb not null default '[]';
alter table rafii_control.query_receipts add column if not exists execution_state text not null default 'policy_unavailable'
  check(execution_state in ('policy_unavailable','local_synthetic'));
-- Preserve 049 byte-for-byte. Permit measured synthetic metadata only in local execution.
-- Discover the original unnamed measured-value constraint by its expression, never a guessed name.
do $$ declare c record; begin
  for c in select conname from pg_constraint where conrelid='rafii_control.metric_rollups'::regclass
      and contype='c' and pg_get_constraintdef(oid) like '%policy_approval_ref%' loop
    execute format('alter table rafii_control.metric_rollups drop constraint %I',c.conname);
  end loop;
end $$;
alter table rafii_control.metric_rollups add constraint rc_measured_lineage
  check(data_state<>'measured' or (value is not null and source_watermark is not null
    and (policy_approval_ref is not null or (fixture and environment='local'))));
create unique index if not exists rc_synthetic_check_receipt on rafii_control.metric_rollups(environment,metric_id,source_receipt_ids)
  where environment='local' and fixture and metric_id='check_failures';
grant select on rafii_control.engineering_evidence to rafii_control_ingest;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='engineering_evidence' and policyname='control_ingest_read') then
  create policy control_ingest_read on rafii_control.engineering_evidence for select to rafii_control_ingest
    using(environment=current_setting('rafii_control.environment',true));
 end if;
end $$;
commit;
