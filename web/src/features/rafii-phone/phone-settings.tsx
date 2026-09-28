'use client';
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { SettingsSection } from '@/features/account/settings-section';
import { useWorkspace } from '@/lib/workspace/provider';
import { usePhoneSettings } from '@/lib/phone/hooks';
import { coworkerKeys } from '@/lib/coworker/hooks';
import type { PhonePreferences, PhoneProviderReadiness } from '@/lib/phone/types';
import { CallRafii } from './call-rafii';
import { parseCreditLimit } from '@/features/agent/credit-limit';

const EVENTS = [['publish.failed', 'Publication failed'], ['publish.uncertain', 'Publication outcome uncertain'], ['campaign.approval_required', 'Approval blocking a deadline'], ['campaign.blocked', 'Campaign blocked'], ['channel.reconnect_required', 'Account connection needs attention']] as const;
const clock = (minutes: number) => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
const minutes = (value: string) => Number(value.split(':')[0]) * 60 + Number(value.split(':')[1]);
const CHECK_STAGE: Record<string, string> = {
  provider_transport: 'Dial’s network blocked Rafii’s API request before the calling service could check it. The connection configuration needs attention.',
  local_configuration: 'Rafii’s Dial settings are incomplete.',
  self_hosted_http: 'Dial did not accept the Self-Hosted status check.',
  self_hosted_access: 'Dial Self-Hosted access is not granted for this API key.',
  self_hosted_disabled: 'Dial Self-Hosted mode is off.',
  self_hosted_mode: 'Dial is using a different Self-Hosted mode.',
  self_hosted_url: 'Dial’s audio WebSocket URL does not match Rafii’s server setting.',
  self_hosted_format: 'Dial’s audio format does not match Rafii’s server setting.',
  numbers_http: 'Dial did not return the outgoing line.',
  outgoing_line: 'Dial’s outgoing line is unavailable for calls.',
  account_http: 'Dial did not return the account settings.',
  account_limit: 'Dial returned an unsupported call duration limit.',
};
function readinessMessage(result: PhoneProviderReadiness) {
  if (result.ready) return 'Dial is ready to create a call. This check did not place one.';
  const detail = result.stage ? CHECK_STAGE[result.stage] : undefined;
  return `${detail || 'Dial calling setup needs attention.'}${result.httpStatus ? ` HTTP ${result.httpStatus}.` : ''} This check did not place a call.`;
}

export function PhoneSettings() {
  const { api, workspaceId, membership } = useWorkspace();
  const settings = usePhoneSettings();
  const client = useQueryClient();
  const [number, setNumber] = useState('');
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const [readiness, setReadiness] = useState<PhoneProviderReadiness | null>(null);
  const [checkError, setCheckError] = useState('');
  const [day, setDay] = useState('Monday');
  const [time, setTime] = useState('09:00');
  const data = settings.data;
  async function run(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await action(); await settings.refetch(); if (workspaceId) await client.invalidateQueries({queryKey:coworkerKeys.preferences(workspaceId)}); }
    catch (err) { setError(err instanceof Error ? err.message : 'Couldn’t save phone settings.'); }
    finally { setBusy(false); }
  }
  async function checkCallingSetup() {
    if (!workspaceId) return;
    setChecking(true); setCheckError(''); setReadiness(null);
    try { setReadiness(await api.phoneProviderReadiness(workspaceId)); }
    catch (err) { setCheckError(err instanceof Error ? err.message : 'Couldn’t check calling setup.'); }
    finally { setChecking(false); }
  }
  if (settings.isError) return <SettingsSection id='phone-mode' title='Call Rafii'><p role='alert'>Phone settings could not load.</p><Button variant='glass' onClick={() => void settings.refetch()}>Retry</Button></SettingsSection>;
  if (!data?.available || !workspaceId) return null;
  const prefs = data.preferences;
  const save = (patch: Partial<PhonePreferences>) => run(() => api.phonePreferences(workspaceId, patch));
  const toggle = (key: 'enabled' | 'proactiveCalls' | 'scheduledCalls' | 'fallbackToPush' | 'fallbackToEmail', text: string, disabled = false) =>
    <Label key={key} htmlFor={`phone-${key}`} className='flex min-h-11 items-center justify-between gap-3'><span id={`phone-${key}-label`}>{text}</span><Switch id={`phone-${key}`} aria-labelledby={`phone-${key}-label`} aria-label={text} checked={prefs[key]} disabled={busy || disabled} onCheckedChange={(value) => void save({ [key]: value })} /></Label>;
  return <div id='phone-mode'><SettingsSection id='phone-mode' title='Call Rafii' description='The same Rafii, on your telephone. Rafii identifies itself as an AI assistant. Calls use phone and voice credits, last up to 10 minutes, and are never audio recorded. Text stays in this Rafii conversation.'>
    <div className='flex flex-col gap-4 text-sm'>
      {data.execution === 'fake' && <p>Local phone test. No telephone call or verification SMS is sent.</p>}
      <p>{data.number ? `Phone ending ${data.number.lastFour} · ${data.number.verified ? 'Verified' : 'Not verified'}` : 'No phone number saved.'}</p>
      {membership?.role === 'owner' && data.execution === 'provider' && <div className='flex flex-col items-start gap-2'>
        <Button variant='glass' size='control' disabled={checking} onClick={() => void checkCallingSetup()}>{checking ? 'Checking…' : 'Check calling setup'}</Button>
        <p className='text-muted-foreground text-xs'>Checks Dial’s settings without placing a call or sending a text.</p>
        {readiness && <p role='status'>{readinessMessage(readiness)}</p>}
        {checkError && <p role='alert' className='text-destructive'>{checkError}</p>}
      </div>}
      {!data.number?.verified && <form className='flex flex-col gap-2' onSubmit={(event) => { event.preventDefault(); void run(async () => { await api.phoneVerify(workspaceId, number); setNumber(''); setSent(true); }); }}>
        <Label htmlFor='rafii-phone-number'>Phone number with country code</Label>
        <Input id='rafii-phone-number' type='tel' autoComplete='tel' placeholder='+12025550123' value={number} onChange={(event) => setNumber(event.target.value)} required disabled={busy} />
        <Button type='submit' variant='glass' size='control' disabled={busy || !data.providerReady || (data.execution !== 'fake' && !data.flags.RAFII_PHONE_VERIFICATION_ENABLED)}>Send verification code</Button>
      </form>}
      {(sent || (data.number && !data.number.verified)) && <form className='flex flex-col gap-2' onSubmit={(event) => { event.preventDefault(); void run(async () => { await api.phoneConfirm(workspaceId, code); setCode(''); setSent(false); }); }}>
        <Label htmlFor='rafii-phone-code'>Verification code</Label><Input id='rafii-phone-code' autoComplete='one-time-code' inputMode='numeric' value={code} onChange={(event) => setCode(event.target.value)} required disabled={busy} />
        <Button type='submit' variant='glass' size='control' disabled={busy}>Verify phone number</Button>
      </form>}
      {toggle('enabled', 'Enable Call Rafii', !data.number?.verified)}
      <CallRafii />
      {toggle('proactiveCalls', 'Allow proactive calls', !data.number?.verified || !data.flags.RAFII_PHONE_PROACTIVE_ENABLED)}
      {toggle('scheduledCalls', 'Allow scheduled briefings', !data.number?.verified || !data.flags.RAFII_PHONE_SCHEDULED_ENABLED)}
      {data.spending?.usesCredits && <Label htmlFor='phone-automatic-credits' className='flex-col items-start'>Maximum credits per automatic call<Input id='phone-automatic-credits' inputMode='decimal' defaultValue={String(prefs.maxMilliCreditsPerCall / 1000)} key={prefs.maxMilliCreditsPerCall} disabled={busy} onBlur={(event) => { const value = event.target.value.trim() === '0' ? 0 : parseCreditLimit(event.target.value); if (value !== null && value !== prefs.maxMilliCreditsPerCall) void save({ maxMilliCreditsPerCall: value }); }} /><span className='text-muted-foreground text-xs'>Zero blocks automatic calls. Phone and voice time can hold up to {(Math.ceil(data.spending.ceilingMilliCredits / 100) / 10).toFixed(1)} credits per call. Rafii’s reasoning uses the remaining limit.</span></Label>}
      <Label htmlFor='rafii-phone-zone' className='flex-col items-start'>Time zone<Input id='rafii-phone-zone' defaultValue={prefs.timeZone} key={prefs.timeZone} disabled={busy} onBlur={(event) => { if (event.target.value !== prefs.timeZone) void save({ timeZone: event.target.value }); }} /></Label>
      <div className='grid grid-cols-2 gap-3'>
        <Label htmlFor='rafii-phone-quiet-start' className='flex-col items-start'>Quiet hours begin<Input id='rafii-phone-quiet-start' type='time' value={clock(prefs.quietStart)} disabled={busy} onChange={(event) => { if (event.target.value) void save({ quietStart: minutes(event.target.value) }); }} /></Label>
        <Label htmlFor='rafii-phone-quiet-end' className='flex-col items-start'>Quiet hours end<Input id='rafii-phone-quiet-end' type='time' value={clock(prefs.quietEnd)} disabled={busy} onChange={(event) => { if (event.target.value) void save({ quietEnd: minutes(event.target.value) }); }} /></Label>
      </div>
      <Label htmlFor='rafii-phone-daily'>Automatic calls per day<select id='rafii-phone-daily' className='rafii-focus bg-background rounded-md border p-2' value={prefs.maxCallsPerDay} disabled={busy} onChange={(event) => void save({ maxCallsPerDay: Number(event.target.value) })}><option value='1'>1</option><option value='2'>2</option></select></Label>
      <fieldset className='flex flex-col gap-2'><legend className='mb-2 font-medium'>Events allowed to call</legend>{EVENTS.map(([key, text]) => <Label key={key} htmlFor={`phone-${key}`} className='flex min-h-11 items-center justify-between gap-3'><span id={`phone-${key}-label`}>{text}</span><Switch id={`phone-${key}`} aria-labelledby={`phone-${key}-label`} aria-label={text} checked={prefs.eventAllowlist.includes(key)} disabled={busy} onCheckedChange={(value) => void save({ eventAllowlist: value ? [...prefs.eventAllowlist, key] : prefs.eventAllowlist.filter((item) => item !== key) })} /></Label>)}</fieldset>
      {toggle('fallbackToPush', 'Fall back to push notifications')}{toggle('fallbackToEmail', 'Fall back to email')}
      <p className='text-muted-foreground text-xs'>Fallback uses your existing notification choices and verified delivery channels. Opening a notification does not call you.</p>
      {prefs.scheduledCalls && <form className='flex flex-wrap items-end gap-3' onSubmit={(event) => { event.preventDefault(); void run(() => api.phoneSchedule(workspaceId, { weekdays: day === 'Daily' ? ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'] : [day], localTime: time, timeZone: prefs.timeZone })); }}>
        <Label htmlFor='rafii-phone-day'>Briefing day<select id='rafii-phone-day' className='rafii-focus bg-background rounded-md border p-2' value={day} onChange={(event) => setDay(event.target.value)}>{['Daily','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map((value) => <option key={value}>{value}</option>)}</select></Label>
        <Label htmlFor='rafii-phone-time'>Briefing time<Input id='rafii-phone-time' type='time' value={time} required onChange={(event) => setTime(event.target.value)} /></Label><Button type='submit' variant='glass' size='control' disabled={busy}>Add briefing</Button>
      </form>}
      {data.schedules.map((item) => <div key={item.id} className='flex items-center justify-between gap-2'><span>{item.schedule.weekdays.join(', ')} · {item.schedule.localTime} · {item.schedule.timeZone}</span><Button variant='quiet' size='control' disabled={busy} onClick={() => void run(() => api.phoneDeleteSchedule(workspaceId, item.id))}>Remove briefing</Button></div>)}
      <div><p className='mb-2 font-medium'>Recent calls</p>{data.calls.length === 0 ? <p className='text-muted-foreground'>No calls yet.</p> : <ul className='flex flex-col gap-3'>{data.calls.slice(0,10).map((call) => <li key={call.id} className='flex flex-wrap items-center justify-between gap-2'><span>{new Date(call.requestedAt * 1000).toLocaleString()} · {call.state.replaceAll('_',' ')}{call.durationSeconds !== null ? ` · ${call.durationSeconds}s` : ''}</span><Link href={`/app/agent/${call.conversationId}`} className='underline underline-offset-4'>Conversation</Link>{call.failureMessage && <p className='text-muted-foreground w-full'>{call.failureMessage}</p>}</li>)}</ul>}</div>
      {data.number && <Button variant='quiet' size='control' disabled={busy} onClick={() => void run(() => api.phoneDelete(workspaceId))}>Revoke and delete phone number</Button>}
      {error && <p role='alert' className='text-destructive'>{error}</p>}
    </div>
  </SettingsSection></div>;
}
