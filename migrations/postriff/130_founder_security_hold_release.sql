-- Founder Admin: the security-hold release action (RAPv2 owner decision 11, 2026-10-16).
-- Numbered 130: 128 is the Discord release branch's and 129 is this release's consumer migration.
--
-- rafii_control.founder_action_requests (068) may now record kind 'security_hold_release': a founder lifts a RAPv2
-- account hold after verifying the person's identity out of band. The preview/confirm protocol, fresh second factor,
-- typed confirmation and Control audit are founder_actions.py's; the consumer side reuses security_holds.release and
-- resolves the open incidents with resolution_code 'support_verified' (security_center.support_release), writing the
-- verification method and reference to the consumer audit (security.hold_released_by_support) and the security ledger.
--
-- Applies only where 068 is installed (no-op otherwise) and is safe to re-apply.
--
-- Rollback: in one transaction, refuse new previews of the kind by restoring the 068 check
--   alter table rafii_control.founder_action_requests drop constraint founder_action_requests_kind_check;
--   alter table rafii_control.founder_action_requests add constraint founder_action_requests_kind_check
--     check(kind in ('reconcile','credits_adjust','account_block','account_unblock','refund_intent'));
-- (first delete or keep any 'security_hold_release' rows: they are audit evidence, so keeping this wider check is the
-- safer rollback; the routes can be withdrawn in code instead).
begin;

do $$
begin
  if to_regclass('rafii_control.founder_action_requests') is not null then
    alter table rafii_control.founder_action_requests drop constraint if exists founder_action_requests_kind_check;
    alter table rafii_control.founder_action_requests add constraint founder_action_requests_kind_check
      check (kind in ('reconcile','credits_adjust','account_block','account_unblock','refund_intent','security_hold_release'));
  end if;
end $$;

commit;
