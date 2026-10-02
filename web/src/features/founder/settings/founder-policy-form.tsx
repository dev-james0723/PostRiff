'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { founderFetch } from '@/lib/founder/api';
import type { Envelope } from '@/lib/founder/types';
import { useCapability, useFounderScope } from '../customers/kit/api';
import { Panel } from '../customers/kit/page-frame';

type Settings = {
  dailySpendMode: 'limited' | 'unlimited'; dailySpendUsdMicro: number; warnPercent: number; timeZone: string;
  replyTo: string; emailCanaryCount: number; pushCanaryCount: number; dailyBriefingTime: string;
  weeklyReviewTime: string; weeklyReviewDay: number; quietStart: number; quietEnd: number;
  maxCallSeconds: number; automaticCallAttemptsDaily: number; concurrentCalls: number;
};
type Policy = { settings: Settings; revision: number; applied: boolean;
  spending: { actualUsdMicro: number; heldUsdMicro: number; warning: boolean; newPaidActionsStopped: boolean };
  ledger: { provider: string; model: string; service: string; action: string; date: string; actualUsdMicro: number }[];
};
const dollars = (value: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value / 1_000_000);
const minuteTime = (value: number) => `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
const timeMinute = (value: string) => { const [h, m] = value.split(':').map(Number); return h * 60 + m; };

function Editor({ data, save, pending, editable }: { data: Policy; save: (changes: Settings) => void; pending: boolean; editable: boolean }) {
  const [draft, setDraft] = useState<Settings>(data.settings);
  const field = (name: keyof Settings, value: string | number) => setDraft({ ...draft, [name]: value });
  const number = (name: keyof Settings, label: string, min = 0, max = 100) => (
    <Label className='flex flex-col gap-2'>{label}<Input type='number' min={min} max={max} value={String(draft[name])} onChange={(e) => field(name, Number(e.target.value))} disabled={!editable} /></Label>
  );
  return <form className='flex flex-col gap-4' onSubmit={(e) => { e.preventDefault(); save(draft); }}>
    <p className='text-muted-foreground text-sm'>Founder product usage and internal credits are unlimited. The provider cap applies only to new paid actions. Settings changes require a recent second factor.</p>
    <div className='grid gap-4 sm:grid-cols-2'>
      <Label className='flex flex-col gap-2'>Provider spending<select className='rafii-quiet rounded-lg p-2' value={draft.dailySpendMode} onChange={(e) => field('dailySpendMode', e.target.value)} disabled={!editable}><option value='limited'>Custom daily cap</option><option value='unlimited'>Unlimited provider spending</option></select></Label>
      <Label className='flex flex-col gap-2'>Daily cap (USD)<Input type='number' min='0.01' max='10000' step='0.01' value={draft.dailySpendUsdMicro / 1_000_000} onChange={(e) => field('dailySpendUsdMicro', Math.round(Number(e.target.value) * 1_000_000))} disabled={!editable || draft.dailySpendMode === 'unlimited'} /></Label>
      {number('warnPercent', 'Warn at (%)', 1, 100)}
      <Label className='flex flex-col gap-2'>Time zone<Input value={draft.timeZone} onChange={(e) => field('timeZone', e.target.value)} disabled={!editable} /></Label>
      <Label className='flex flex-col gap-2'>Email Reply-To<Input type='email' value={draft.replyTo} onChange={(e) => field('replyTo', e.target.value)} disabled={!editable} /></Label>
      {number('emailCanaryCount', 'Founder email canary limit')}{number('pushCanaryCount', 'Founder push canary limit')}
      <Label className='flex flex-col gap-2'>Daily briefing<Input type='time' value={draft.dailyBriefingTime} onChange={(e) => field('dailyBriefingTime', e.target.value)} disabled={!editable} /></Label>
      <Label className='flex flex-col gap-2'>Weekly review<Input type='time' value={draft.weeklyReviewTime} onChange={(e) => field('weeklyReviewTime', e.target.value)} disabled={!editable} /></Label>
      <Label className='flex flex-col gap-2'>Weekly review day<select className='rafii-quiet rounded-lg p-2' value={draft.weeklyReviewDay} onChange={(e) => field('weeklyReviewDay', Number(e.target.value))} disabled={!editable}>{['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map((day, index) => <option key={day} value={index}>{day}</option>)}</select></Label>
      <Label className='flex flex-col gap-2'>Quiet hours start<Input type='time' value={minuteTime(draft.quietStart)} onChange={(e) => field('quietStart', timeMinute(e.target.value))} disabled={!editable} /></Label>
      <Label className='flex flex-col gap-2'>Quiet hours end<Input type='time' value={minuteTime(draft.quietEnd)} onChange={(e) => field('quietEnd', timeMinute(e.target.value))} disabled={!editable} /></Label>
      {number('maxCallSeconds', 'Maximum call duration (seconds)', 60, 3600)}
      {number('automaticCallAttemptsDaily', 'Automatic call attempts per day')}{number('concurrentCalls', 'Concurrent calls', 1, 10)}
    </div>
    <p className='text-muted-foreground text-sm'>Financial records retain their immutable history. Charges and refunds require explicit Founder confirmation. Saving these defaults does not activate delivery channels.</p>
    <Button type='submit' variant='action' disabled={pending || !editable}>{pending ? 'Saving…' : data.applied ? 'Save Founder settings' : 'Apply approved Founder defaults'}</Button>
  </form>;
}

export function FounderPolicyForm() {
  const scope = useFounderScope(); const client = useQueryClient(); const permitted = useCapability('control.settings');
  const key = scope.key('founder-policy');
  const query = useQuery({ queryKey: key, enabled: scope.ready, queryFn: async ({ signal }) => (await founderFetch<Envelope<Policy>>('/founder-policy', { signal })).data });
  const save = useMutation({ mutationFn: async (changes: Settings) => (await founderFetch<Envelope<Policy>>('/founder-policy', { method: 'PUT', body: { mode: 'live', revision: query.data?.revision, changes } })).data,
    onSuccess: async (data) => { client.setQueryData(key, data); await client.invalidateQueries({ queryKey: scope.key('activation-readiness') }); } });
  return <Panel title='Founder limits and defaults' description='Your entitlement, external provider budget, contact limits and briefing defaults.'>
    {query.isPending ? <p>Loading settings…</p> : query.isError ? <StateMessage kind='error' layout='inline' title='Founder settings unavailable' description='Create or resume the internal Ops workspace, then reload. No provider spend has been authorized by this failed read.' /> : query.data ? <>
      {query.data.spending.newPaidActionsStopped ? <StateMessage kind='partial' layout='inline' title='Daily provider cap reached' description='New paid actions are stopped. Other Founder features remain available.' /> : query.data.spending.warning ? <StateMessage kind='partial' layout='inline' title='Provider spending warning' /> : null}
      <p className='mb-4 text-sm'>Observed today: {dollars(query.data.spending.actualUsdMicro)} · Unresolved holds: {dollars(query.data.spending.heldUsdMicro)}</p>
      <Editor key={query.data.revision} data={query.data} save={(changes) => save.mutate(changes)} pending={save.isPending} editable={permitted && scope.mode === 'live'} />
      {save.isError && <StateMessage kind='error' layout='inline' title='Settings were not saved' description='Refresh a stale revision or complete a recent second factor, then retry.' />}
      {save.isSuccess && <p role='status' className='mt-3 text-sm'>Founder settings saved.</p>}
      <details className='mt-5'><summary>Provider ledger · last 60 days</summary>{query.data.ledger.length === 0 ? <p className='text-muted-foreground mt-2 text-sm'>No observed provider settlements in this period.</p> : <ul className='mt-2 space-y-2 text-sm'>{query.data.ledger.map((r, i) => <li key={i}>{r.date} · {r.provider} / {r.model || r.service} · {r.action} · {dollars(r.actualUsdMicro)}</li>)}</ul>}</details>
    </> : null}
  </Panel>;
}
