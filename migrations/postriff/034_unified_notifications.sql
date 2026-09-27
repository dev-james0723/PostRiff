-- Unified Attention Router. 44 current worktrees inspected: highest forward migration is 033.
-- Server-owned consent/acknowledgements; no second phone-number store. Forward only.
begin;
alter table public.pr_notification_deliveries drop constraint if exists pr_notification_deliveries_channel_check;
alter table public.pr_notification_deliveries add constraint pr_notification_deliveries_channel_check
  check (channel in ('in_app','email','push','sms','phone'));
alter table public.pr_notification_deliveries drop constraint if exists pr_notification_deliveries_status_check;
alter table public.pr_notification_deliveries add constraint pr_notification_deliveries_status_check
  check (status in ('pending','claimed','sent','delivered','read','acted','dismissed','failed','dead','suppressed','cancelled','digested','uncertain'));
alter table public.pr_notification_deliveries add column if not exists sms_phone_hash text check (sms_phone_hash ~ '^[0-9a-f]{64}$');
alter table public.pr_notification_deliveries add column if not exists sms_dispatch_started_at timestamptz;
alter table public.pr_notification_deliveries add column if not exists sms_escalation boolean not null default false;
alter table public.pr_notification_deliveries add column if not exists sms_segments integer check (sms_segments between 1 and 10);
alter table public.pr_notification_deliveries add column if not exists sms_reserved_usd_micro bigint check (sms_reserved_usd_micro >= 0);
alter table public.pr_notification_deliveries add column if not exists sms_cost_usd_micro bigint check (sms_cost_usd_micro >= 0);
alter table public.pr_notification_preferences add column if not exists sms_mode text check (sms_mode in ('off','important_only'));
alter table public.pr_notification_preferences add column if not exists smart_escalation boolean;
alter table public.pr_notification_events add column if not exists sms_policy text not null default 'off' check (sms_policy in ('off','escalate','immediate'));
alter table public.pr_notification_events add column if not exists time_sensitive boolean not null default false;
alter table public.pr_notification_events add column if not exists resolved_at timestamptz;

create table if not exists public.pr_sms_consents (
  user_id uuid primary key references public.pr_profiles(user_id) on delete cascade,
  phone_hash text not null check (phone_hash ~ '^[0-9a-f]{64}$'),
  status text not null check (status in ('opted_in','opted_out','invalidated')),
  version text not null check (length(version) between 1 and 40),
  source text not null check (source in ('settings','provider','phone_change')),
  security_sms boolean not null default false,
  provider_blocked boolean not null default false,
  consented_at timestamptz, opted_out_at timestamptz,
  updated_at timestamptz not null default now()
);
create table if not exists public.pr_notification_acknowledgements (
  event_id uuid not null references public.pr_notification_events(id) on delete cascade,
  user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  acknowledged_at timestamptz not null default now(),
  source_channel text not null check (source_channel in ('in_app','email','push','sms','domain')),
  kind text not null check (kind in ('opened','acted','resolved','manual')),
  primary key (event_id,user_id)
);
create index if not exists pr_notification_ack_user on public.pr_notification_acknowledgements(user_id,event_id);
create index if not exists pr_sms_deliveries_limits on public.pr_notification_deliveries(user_id,sms_dispatch_started_at)
  where channel='sms' and sms_dispatch_started_at is not null;
create index if not exists pr_sms_deliveries_due on public.pr_notification_deliveries(next_attempt_at)
  where channel='sms' and status in ('pending','claimed');

-- A binding change or deletion invalidates consent and all unsent escalations even outside PhoneService.
create or replace function postriff_private.invalidate_sms_binding() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if TG_OP='DELETE' or (TG_OP='UPDATE' and (NEW.phone_hash is distinct from OLD.phone_hash or NEW.verified_at is null)) then
    update public.pr_sms_consents set status='invalidated',security_sms=false,source='phone_change',updated_at=now(),
      provider_blocked=case when TG_OP='UPDATE' and NEW.phone_hash is distinct from OLD.phone_hash then false else provider_blocked end
      where user_id=OLD.user_id;
    update public.pr_notification_deliveries set status='suppressed',failure_class='preference',failure_detail='phone_binding_changed',
      lease_owner=null,lease_until=null,updated_at=now()
      where user_id=OLD.user_id and channel='sms' and status in ('pending','claimed') and sms_dispatch_started_at is null;
  end if;
  return case when TG_OP='DELETE' then OLD else NEW end;
end $$;
revoke all on function postriff_private.invalidate_sms_binding() from public,anon,authenticated;
drop trigger if exists pr_phone_sms_binding on public.pr_phone_numbers;
create trigger pr_phone_sms_binding before update or delete on public.pr_phone_numbers
  for each row execute function postriff_private.invalidate_sms_binding();

do $$ declare t text; begin
  foreach t in array array['pr_sms_consents','pr_notification_acknowledgements'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant all on public.%I to service_role',t);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)',t);
    end if;
  end loop;
end $$;
commit;
