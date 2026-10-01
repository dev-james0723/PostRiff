'use client';

import { useEffect, useId, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Band, FIELD_CLASS, StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { failureOf, useCapability, useContactPolicy, useSaveContactPolicy, useTestCall } from '../customers/kit/api';
import { clockToMinutes, minutesToClock, usdMicro, whenDateTime } from '../customers/kit/format';
import { QueryState } from '../customers/kit/page-frame';
import type { ContactPolicy } from '../customers/kit/types';
import { channelListed } from './comms';

/**
 * Contact & calls policy (CONTRACTS §5, PRD §6.6–§6.7). Every switch that would cause a real call, email or push
 * is disabled with its reason: live delivery is off in this release and the provider is not configured, so the
 * switches are read-only truth, not controls. Quiet hours, caps, allowlist and budget are saved with the policy
 * revision; a stale revision is refused by the server. The test call always comes back 409 POLICY_DISABLED and
 * the page shows that refusal as the result.
 */
/** The policy's channel ids (`founder_contact.CHANNELS`) and their labels. */
const CHANNELS = [
  { id: 'call', label: 'Phone' },
  { id: 'email', label: 'Email' },
  { id: 'push', label: 'Push' }
] as const;
const EVENTS = ['founder.incident', 'founder.briefing'] as const;
const LIVE_DELIVERY_REASON = 'Real calls, email and push stay off in this release (liveDeliveryEnabled = false; provider flags default to 0). Enabling them needs a configured provider and a separate enablement, not this form.';

interface Draft {
  quietStart: string;
  quietEnd: string;
  timeZone: string;
  dailyCap: string;
  concurrentCap: string;
  eventAllowlist: string[];
  budgetUsd: string;
}

function draftFrom(policy: ContactPolicy): Draft {
  return {
    quietStart: minutesToClock(policy.quietStart),
    quietEnd: minutesToClock(policy.quietEnd),
    timeZone: policy.timeZone,
    dailyCap: String(policy.dailyCap),
    concurrentCap: String(policy.concurrentCap),
    eventAllowlist: [...policy.eventAllowlist],
    budgetUsd: String(policy.budgetUsdMicroDaily / 1_000_000)
  };
}

/** The policy to save, or the first validation message; the server validates again. */
export function policyFromDraft(policy: ContactPolicy, draft: Draft): { policy: ContactPolicy } | { error: string } {
  const quietStart = clockToMinutes(draft.quietStart);
  const quietEnd = clockToMinutes(draft.quietEnd);
  if (quietStart === null || quietEnd === null) return { error: 'Quiet hours need a start and an end time (HH:MM).' };
  const dailyCap = Number(draft.dailyCap);
  const concurrentCap = Number(draft.concurrentCap);
  if (!Number.isInteger(dailyCap) || dailyCap < 0 || dailyCap > 2) return { error: 'Daily cap must be 0, 1 or 2 calls.' };
  if (!Number.isInteger(concurrentCap) || concurrentCap < 0 || concurrentCap > 1) return { error: 'At most one call at a time (0 or 1).' };
  const budget = Number(draft.budgetUsd);
  if (!Number.isFinite(budget) || budget < 0) return { error: 'Daily budget must be zero or more.' };
  if (!draft.timeZone.trim()) return { error: 'A time zone is required.' };
  return {
    policy: {
      ...policy,
      liveDeliveryEnabled: false,
      quietStart,
      quietEnd,
      timeZone: draft.timeZone.trim(),
      dailyCap,
      concurrentCap,
      eventAllowlist: draft.eventAllowlist,
      budgetUsdMicroDaily: Math.round(budget * 1_000_000)
    }
  };
}

function LockedSwitch({ label, description, checked, reason }: { label: string; description?: string; checked: boolean; reason: string }) {
  const id = useId();
  return (
    <div className='flex items-start justify-between gap-3'>
      <div className='flex min-w-0 flex-col gap-0.5'>
        <Label htmlFor={id} className='text-foreground text-sm font-medium'>
          {label}
        </Label>
        {description && <p className='text-muted-foreground text-xs'>{description}</p>}
        <p id={`${id}-reason`} className='text-muted-foreground text-xs italic'>
          {reason}
        </p>
      </div>
      <Switch id={id} checked={checked} disabled aria-describedby={`${id}-reason`} />
    </div>
  );
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className='flex min-w-0 flex-col gap-1.5 text-sm'>
      <span className='text-foreground font-medium'>{label}</span>
      {children}
      {hint && <span className='text-muted-foreground text-xs'>{hint}</span>}
    </label>
  );
}

function TestCallButton({ policy }: { policy: ContactPolicy }) {
  const test = useTestCall();
  const canSettings = useCapability('control.settings');
  const [outcome, setOutcome] = useState<ReactNode>(null);
  async function run() {
    setOutcome(null);
    try {
      const result = await test.mutateAsync();
      setOutcome(<StateMessage kind='success' layout='inline' title='Test call accepted' description={result.data.attemptId ? `Attempt ${result.data.attemptId} was recorded.` : 'The server accepted the request.'} />);
    } catch (error) {
      const failure = failureOf(error);
      const disabled = failure.code === 'POLICY_DISABLED' || failure.status === 409;
      setOutcome(
        <StateMessage
          kind={disabled ? 'unsupported' : failure.status === 403 ? 'permission' : 'error'}
          layout='inline'
          title={disabled ? 'The server refused the test call: POLICY_DISABLED' : 'The test call could not be placed'}
          description={disabled ? 'Live delivery is off and no telephony provider is configured, so Control refuses every call request before it reaches a provider. That is the expected state in this release; nothing was dialled.' : failure.message}
        />
      );
    }
  }
  return (
    <div className='flex flex-col gap-2'>
      <div className='flex flex-wrap items-center gap-2'>
        <Button variant='glass' size='control' onClick={() => void run()} disabled={test.isPending || !canSettings} title={canSettings ? 'Asks the server to place a test call to the verified number; refused while live delivery is off.' : 'Needs the control.settings capability and a step-up.'}>
          {test.isPending ? <Icons.spinner className='animate-spin' /> : <Icons.phone />} Test call
        </Button>
        <StatusChip status='neutral' icon='lock'>
          {policy.liveDeliveryEnabled ? 'Live delivery on' : 'Live delivery off'}
        </StatusChip>
      </div>
      {!canSettings && <p className='text-muted-foreground text-xs'>Changing or testing contact settings needs the control.settings capability with a fresh second factor.</p>}
      {outcome}
    </div>
  );
}

export function ContactPolicyForm() {
  const query = useContactPolicy();
  const save = useSaveContactPolicy();
  const canSettings = useCapability('control.settings');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [revision, setRevision] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const policy = query.data?.policy ?? null;

  useEffect(() => {
    if (policy && policy.revision !== revision) {
      setDraft(draftFrom(policy));
      setRevision(policy.revision);
    }
  }, [policy, revision]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!policy || !draft) return;
    const next = policyFromDraft(policy, draft);
    if ('error' in next) {
      setError(next.error);
      return;
    }
    setError(null);
    try {
      await save.mutateAsync(next.policy);
      toast.success('Contact policy saved. Live delivery stays off.');
    } catch (cause) {
      const failure = failureOf(cause);
      setError(failure.status === 409 ? 'The policy changed since this page loaded. It has been refreshed; review and save again.' : failure.message ?? 'The policy could not be saved.');
      if (failure.status === 409) void query.refetch();
    }
  }

  return (
    <QueryState query={query} label='contact policy' isEmpty={(result) => result.policy === null} emptyTitle='No contact policy yet' emptyDescription='The server has not created a policy row for this operator and environment; saving creates revision 1.'>
      {() =>
        policy &&
        draft && (
          <form onSubmit={(event) => void submit(event)} className='flex flex-col gap-5' aria-describedby='contact-policy-live'>
            <Band>
              <LockedSwitch label='Live delivery' description='Allow Control to place real calls and send real messages.' checked={policy.liveDeliveryEnabled} reason={LIVE_DELIVERY_REASON} />
              {policy.liveDeliveryBlockers && policy.liveDeliveryBlockers.length > 0 && <p className='text-muted-foreground text-xs'>Blockers reported by the server: {policy.liveDeliveryBlockers.join(', ')}.</p>}
              <div className='grid gap-3 sm:grid-cols-3'>
                {CHANNELS.map((channel) => (
                  <LockedSwitch key={channel.id} label={channel.label} checked={channelListed(policy.channels, channel.id)} reason='Listed in the policy; used only while live delivery is on.' />
                ))}
              </div>
            </Band>

            <div className='grid gap-4 sm:grid-cols-2'>
              <Field label='Destination' hint='Verified in the ops workspace phone settings; not editable here.'>
                <Input readOnly value={policy.destinationRef ?? ''} placeholder='No verified number' className={FIELD_CLASS} />
              </Field>
              <Field label='Time zone' hint='Quiet hours and schedules are interpreted in this zone.'>
                <Input value={draft.timeZone} onChange={(event) => setDraft({ ...draft, timeZone: event.target.value })} className={FIELD_CLASS} autoComplete='off' />
              </Field>
              <Field label='Quiet hours start'>
                <Input type='time' value={draft.quietStart} onChange={(event) => setDraft({ ...draft, quietStart: event.target.value })} className={FIELD_CLASS} />
              </Field>
              <Field label='Quiet hours end'>
                <Input type='time' value={draft.quietEnd} onChange={(event) => setDraft({ ...draft, quietEnd: event.target.value })} className={FIELD_CLASS} />
              </Field>
              <Field label='Daily cap' hint='Contact attempts per day, 0–2.'>
                <Input type='number' inputMode='numeric' min={0} max={2} value={draft.dailyCap} onChange={(event) => setDraft({ ...draft, dailyCap: event.target.value })} className={FIELD_CLASS} />
              </Field>
              <Field label='Concurrent cap' hint='Calls in flight at once, 0 or 1.'>
                <Input type='number' inputMode='numeric' min={0} max={1} value={draft.concurrentCap} onChange={(event) => setDraft({ ...draft, concurrentCap: event.target.value })} className={FIELD_CLASS} />
              </Field>
              <Field label='Daily budget (USD)' hint={`Stored as USD micro; currently ${usdMicro(policy.budgetUsdMicroDaily)} per day.`}>
                <Input type='number' inputMode='decimal' min={0} step='0.01' value={draft.budgetUsd} onChange={(event) => setDraft({ ...draft, budgetUsd: event.target.value })} className={FIELD_CLASS} />
              </Field>
            </div>

            <fieldset className='flex flex-col gap-2'>
              <legend className='text-foreground text-sm font-medium'>Event allowlist</legend>
              <p className='text-muted-foreground text-xs'>Only these founder events may plan a contact attempt once live delivery exists.</p>
              <div className='flex flex-wrap gap-3'>
                {EVENTS.map((event) => {
                  const checked = draft.eventAllowlist.includes(event);
                  return (
                    <label key={event} className={cn('rafii-quiet flex items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm', checked && 'rafii-glass-selected')}>
                      <input type='checkbox' aria-label={event} checked={checked} onChange={(change) => setDraft({ ...draft, eventAllowlist: change.target.checked ? [...draft.eventAllowlist, event] : draft.eventAllowlist.filter((item) => item !== event) })} className='accent-foreground size-4' />
                      {event}
                    </label>
                  );
                })}
              </div>
            </fieldset>

            {error && <StateMessage kind='error' layout='inline' title={error} />}
            <div className='flex flex-wrap items-center gap-3'>
              <Button type='submit' variant='action' size='control' disabled={save.isPending || !canSettings} title={canSettings ? undefined : 'Needs the control.settings capability and a step-up.'}>
                {save.isPending ? <Icons.spinner className='animate-spin' /> : <Icons.check />} Save policy
              </Button>
              <span id='contact-policy-live' className='text-muted-foreground text-xs'>
                Revision {policy.revision}
                {policy.updatedAt && ` · updated ${whenDateTime(policy.updatedAt)}`} · saving never turns live delivery on.
              </span>
            </div>
            <TestCallButton policy={policy} />
          </form>
        )
      }
    </QueryState>
  );
}
