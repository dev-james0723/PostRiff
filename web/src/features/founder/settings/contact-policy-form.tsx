'use client';

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
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
import { usdMicro, whenDateTime } from '../customers/kit/format';
import { QueryState } from '../customers/kit/page-frame';
import type { ContactPolicy } from '../customers/kit/types';
import { channelListed } from './comms';
import { draftFromPolicy, policyFromDraft, type ContactDraft } from './contact-policy';

/**
 * Fresh-MFA, revision-checked consent. Provider readiness and the shared spend policy are enforced by the server.
 */
/** The policy's channel ids (`founder_contact.CHANNELS`) and their labels. */
const CHANNELS = [
  { id: 'call', label: 'Phone' },
  { id: 'email', label: 'Email' },
  { id: 'push', label: 'Push' }
] as const;
const EVENTS = ['founder.incident', 'founder.briefing'] as const;
function PolicySwitch({ label, description, checked, disabled, onChange }: { label: string; description?: string; checked: boolean; disabled: boolean; onChange: (checked: boolean) => void }) {
  const id = useId();
  return (
    <div className='flex items-start justify-between gap-3'>
      <div className='flex min-w-0 flex-col gap-0.5'>
        <Label htmlFor={id} className='text-foreground text-sm font-medium'>
          {label}
        </Label>
        {description && <p className='text-muted-foreground text-xs'>{description}</p>}
      </div>
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
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
  const requestId = useRef<string | null>(null);
  async function run() {
    setOutcome(null);
    try {
      requestId.current ??= crypto.randomUUID();
      const result = await test.mutateAsync(requestId.current);
      const attempt = result.data.attempt;
      setOutcome(<StateMessage kind={attempt.state === 'ambiguous' ? 'unsupported' : 'success'} layout='inline' title={`Call request: ${attempt.state}`} description={`Attempt ${attempt.id} was recorded. This does not confirm connection or audio. Checking again reuses this request.`} />);
    } catch (error) {
      const failure = failureOf(error);
      const disabled = failure.code === 'POLICY_DISABLED';
      setOutcome(
        <StateMessage
          kind={disabled ? 'unsupported' : failure.status === 403 ? 'permission' : 'error'}
          layout='inline'
          title={disabled ? 'Test call is not ready' : `Call request refused${failure.code ? ': ' + failure.code : ''}`}
          description={failure.message}
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
  const [draft, setDraft] = useState<ContactDraft | null>(null);
  const [revision, setRevision] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const policy = query.data?.policy ?? null;

  useEffect(() => {
    if (policy && policy.revision !== revision) {
      setDraft(draftFromPolicy(policy));
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
      toast.success('Contact policy saved. Delivery remains subject to provider readiness and the shared spend policy.');
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
              <PolicySwitch label='Live delivery' description='Allow the selected channels after provider and canary checks pass.' checked={draft.liveDeliveryEnabled} disabled={!canSettings} onChange={(checked) => setDraft({ ...draft, liveDeliveryEnabled: checked })} />
              {policy.liveDeliveryBlockers && policy.liveDeliveryBlockers.length > 0 && <p className='text-muted-foreground text-xs'>Blockers reported by the server: {policy.liveDeliveryBlockers.join(', ')}.</p>}
              <div className='grid gap-3 sm:grid-cols-3'>
                {CHANNELS.map((channel) => (
                  <PolicySwitch key={channel.id} label={channel.label} checked={channelListed(draft.channels, channel.id)} disabled={!canSettings} onChange={(checked) => setDraft({ ...draft, channels: checked ? [...draft.channels, channel.id] : draft.channels.filter((id) => id !== channel.id) })} />
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
              <Field label='Daily cap' hint='Automatic call attempts per day. Explicit test calls are separate.'>
                <Input type='number' inputMode='numeric' min={0} max={100} value={draft.dailyCap} onChange={(event) => setDraft({ ...draft, dailyCap: event.target.value })} className={FIELD_CLASS} />
              </Field>
              <Field label='Concurrent cap' hint='Calls in flight at once. Zero pauses new calls.'>
                <Input type='number' inputMode='numeric' min={0} max={10} value={draft.concurrentCap} onChange={(event) => setDraft({ ...draft, concurrentCap: event.target.value })} className={FIELD_CLASS} />
              </Field>
              <Field label='Daily call budget (USD)' hint={`Currently ${policy.budgetUsdMicroDaily === null ? 'Unlimited' : usdMicro(policy.budgetUsdMicroDaily)}. The shared Founder spend cap applies to all paid actions.`}>
                <span className='flex items-center gap-2'><input type='checkbox' aria-label='Unlimited call budget' checked={draft.budgetMode === 'unlimited'} onChange={(event) => setDraft({ ...draft, budgetMode: event.target.checked ? 'unlimited' : 'limited' })} /> Unlimited call budget</span>
                <Input type='number' inputMode='decimal' min={0} max={10_000} step='0.01' disabled={draft.budgetMode === 'unlimited'} value={draft.budgetUsd} onChange={(event) => setDraft({ ...draft, budgetUsd: event.target.value })} className={FIELD_CLASS} />
              </Field>
            </div>

            <fieldset className='flex flex-col gap-2'>
              <legend className='text-foreground text-sm font-medium'>Event allowlist</legend>
              <p className='text-muted-foreground text-xs'>Only these Founder events may plan automatic contact attempts.</p>
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
                {policy.updatedAt && ` · updated ${whenDateTime(policy.updatedAt)}`} · changes require a fresh second factor.
              </span>
            </div>
            <TestCallButton policy={policy} />
          </form>
        )
      }
    </QueryState>
  );
}
