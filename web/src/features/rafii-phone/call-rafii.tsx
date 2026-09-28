'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { keys } from '@/lib/api/hooks';
import { useWorkspace } from '@/lib/workspace/provider';
import { usePhoneSettings } from '@/lib/phone/hooks';
import { PHONE_TERMINAL } from '@/lib/phone/types';
import { parseCreditLimit } from '@/features/agent/credit-limit';

/** Only this button's explicit click submits a call. Navigation and notification opens never dial. */
export function CallRafii({ conversationId, onConversation }: { conversationId?: string | null; onConversation?: (id: string) => void }) {
  const { api, workspaceId } = useWorkspace();
  const settings = usePhoneSettings();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [creditLimit, setCreditLimit] = useState('');
  const key = useRef<string | null>(null);
  const data = settings.data;
  const active = data?.calls.find((call) => !PHONE_TERMINAL.has(call.state));
  if (!data?.available) return null;
  const ready = data.number?.verified && data.preferences.enabled && data.providerReady && data.flags.RAFII_PHONE_OUTBOUND_ENABLED;
  const spending = data.spending;
  const maximum = parseCreditLimit(creditLimit);
  const creditReady = !spending?.usesCredits || (maximum !== null && maximum >= spending.ceilingMilliCredits &&
    (spending.availableMilliCredits ?? 0) >= spending.ceilingMilliCredits);
  async function start() {
    if (busy || !workspaceId || !creditReady) return;
    setBusy(true); setError('');
    key.current ??= crypto.randomUUID();
    try {
      const call = await api.phoneCall(workspaceId, { idempotencyKey: key.current, conversationId,
        ...(spending?.usesCredits && maximum !== null ? { maxMilliCredits: maximum } : {}) });
      key.current = null;
      if (call.state === 'failed' || call.state === 'cancelled') setError(call.failureMessage || 'The call did not connect. Check recent calls before trying again.');
      onConversation?.(call.conversationId);
      await settings.refetch();
    } catch (err) {
      // Keep the key after an uncertain response: retry reconciles the original request, never adds another dial.
      setError(err instanceof Error ? err.message : 'Couldn’t confirm the call. Check recent calls before trying again.');
      await settings.refetch();
    } finally { setBusy(false); }
  }
  async function end() {
    if (!workspaceId || !active || busy) return;
    setBusy(true);
    try {
      const result = await api.phoneEnd(workspaceId, active.id);
      if (!result.ended) setError('The call is ending. Wait for confirmation before calling again.');
      await settings.refetch();
    } catch (err) { setError(err instanceof Error ? err.message : 'Couldn’t confirm the call ended.'); }
    finally { setBusy(false); }
  }
  return <div className='flex flex-wrap items-center gap-2 px-4 py-2 text-xs' aria-live='polite'>
    {ready && !active && spending?.usesCredits && <div className='w-full space-y-2'>
      <label className='flex flex-wrap items-center gap-2'>Maximum credits for this call<input aria-label='Maximum credits for this call' inputMode='decimal' value={creditLimit} onChange={(event) => setCreditLimit(event.target.value)} disabled={busy} placeholder='Set a limit' className='rafii-field min-h-11 w-28 rounded-lg px-3 text-base' /></label>
      <p>Phone and voice time holds up to {(Math.ceil(spending.ceilingMilliCredits / 100) / 10).toFixed(1)} credits. Set a higher limit to allow Rafii’s reasoning during the call. Unused credits return when the call settles; paid drafting, research and media keep their task approval rules.</p>
      <p>Available: {((spending.availableMilliCredits ?? 0) / 1000).toFixed(1)} credits.</p>
    </div>}
    {ready && !active && <Button type='button' variant='glass' size='sm' className='min-h-11' disabled={busy || !creditReady} onClick={() => void start()}>{busy ? 'Requesting call…' : 'Have Rafii call me'}</Button>}
    {!ready && !active && <Link href='/app/account/notifications#phone-mode' className='underline underline-offset-4'>Set up Call Rafii</Link>}
    {active && <><span>{data.execution === 'fake' ? 'Local test · ' : ''}{active.state === 'ambiguous' ? 'Call outcome uncertain. Checking the call; please wait.' : `Rafii call: ${active.state.replaceAll('_', ' ')}`}</span><Button type='button' variant='quiet' size='sm' className='min-h-11' disabled={busy} onClick={() => void end()}>End call</Button></>}
    {error && <p className='text-destructive w-full' role='alert'>{error}</p>}
  </div>;
}

/** Remains mounted when the panel/bell closes; web drafts and conversation follow phone edits while the call stays live. */
export function PhoneWorkspaceSync() {
  const { workspaceId } = useWorkspace();
  const settings = usePhoneSettings();
  const client = useQueryClient();
  const last = settings.data?.calls[0];
  useEffect(() => {
    if (!workspaceId || !last) return;
    void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    void client.invalidateQueries({ queryKey: keys.messages(workspaceId, last.conversationId) });
  }, [workspaceId, last, settings.dataUpdatedAt, client]);
  return null;
}
