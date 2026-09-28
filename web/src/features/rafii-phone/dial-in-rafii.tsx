'use client';
import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { useWorkspace } from '@/lib/workspace/provider';
import { usePhoneSettings } from '@/lib/phone/hooks';
import type { PhoneInboundCode, PhoneSettingsData } from '@/lib/phone/types';
import { inboundCodeCooldownSeconds, inboundCodeCooldownUntil } from './inbound-code-cooldown';

type Props = { conversationId?: string | null; onConversation?: (id: string) => void };

export function DialInRafii(props: Props) {
  const { workspaceId } = useWorkspace();
  const settings = usePhoneSettings();
  if (!workspaceId || !settings.data?.inbound?.available) return null;
  // A workspace/conversation switch destroys the transient secret, including any late response.
  return <DialInPanel key={`${workspaceId}:${props.conversationId ?? ''}`} {...props} workspaceId={workspaceId} inbound={settings.data.inbound} />;
}

function DialInPanel({ workspaceId, inbound, conversationId, onConversation }: Props & { workspaceId: string; inbound: NonNullable<PhoneSettingsData['inbound']> }) {
  const { api } = useWorkspace();
  const client = useQueryClient();
  const [ticket, setTicket] = useState<PhoneInboundCode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const mounted = useRef(true);
  const notified = useRef<string | null>(null);
  const cooldownSeconds = inboundCodeCooldownSeconds(now, cooldownUntil);
  const cooldownActive = cooldownSeconds > 0;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!ticket && !cooldownActive) return;
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [ticket, cooldownActive]);
  const status = useQuery({
    queryKey: ['phone-inbound-status', workspaceId, ticket?.id],
    queryFn: () => api.phoneInboundStatus(workspaceId, ticket!.id),
    enabled: Boolean(ticket && ticket.expiresAt > now),
    refetchInterval: (query) => query.state.data?.state && query.state.data.state !== 'ready' ? false : 2000,
    retry: false,
  });
  useEffect(() => {
    const call = status.data?.call;
    if (call && notified.current !== call.id) {
      notified.current = call.id;
      void client.invalidateQueries({ queryKey: ['phone', workspaceId] });
      onConversation?.(call.conversationId);
    }
  }, [status.data?.call, onConversation, client, workspaceId]);
  const spending = inbound.spending;
  const creditReady = !spending.usesCredits || ((spending.availableMilliCredits ?? 0) >= spending.ceilingMilliCredits);
  const seconds = ticket ? Math.max(0, Math.ceil(ticket.expiresAt - now)) : 0;
  const usable = Boolean(ticket?.code && seconds > 0 && (!status.data || status.data.state === 'ready') && !status.isError);
  useEffect(() => {
    if (ticket?.code && !usable) setTicket((current) => current ? { ...current, code: '' } : current);
  }, [ticket?.code, usable]);

  async function generate() {
    if (busy || !creditReady || cooldownActive) return;
    setBusy(true); setError(''); setTicket(null);
    try {
      const result = await api.phoneInboundCode(workspaceId, { conversationId, ...(spending.usesCredits ? { useAvailableCredits: true } : {}) });
      if (mounted.current) {
        const issuedAt = Date.now() / 1000;
        setNow(issuedAt);
        setCooldownUntil(inboundCodeCooldownUntil(issuedAt));
        setTicket(result);
      }
    } catch (err) {
      if (mounted.current) {
        if (err instanceof ApiError && err.code === 'inbound_code_limit') {
          const rejectedAt = Date.now() / 1000;
          setNow(rejectedAt);
          setCooldownUntil(inboundCodeCooldownUntil(rejectedAt));
        }
        setError(err instanceof Error ? err.message : 'Couldn’t create a Agent Pairing Code.');
      }
    }
    finally { if (mounted.current) setBusy(false); }
  }
  async function cancel() {
    if (!ticket || busy) return;
    setBusy(true); setError('');
    try { await api.phoneInboundRevoke(workspaceId, ticket.id); if (mounted.current) setTicket(null); }
    catch (err) { if (mounted.current) setError(err instanceof Error ? err.message : 'Couldn’t cancel the code.'); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <details aria-live='off' className='w-full rounded-xl border border-border/60 p-3 text-sm'>
    <summary className='rafii-focus min-h-11 cursor-pointer content-center font-medium'>Call Rafii by phone</summary>
    <div className='mt-3 flex flex-col items-start gap-3'>
      <p>Call {inbound.phoneNumber} and say your 12-digit Agent Pairing Code, or enter it on the keypad followed by * (star), to reach your Rafii in this workspace. {conversationId ? 'Continue this conversation.' : 'A new conversation will appear here when you connect.'}</p>
      {spending.usesCredits && <>
        <p className='text-muted-foreground text-xs'>Calling uses your available credits for phone time, voice and Rafii’s reasoning, reserved a minute at a time. Calls last up to one hour, or until there aren’t enough credits to continue. Unused credits return after settlement; provider account limits and paid-task approvals still apply.</p>
      </>}
      {usable && ticket ? <div className='w-full space-y-3 rounded-lg bg-muted/40 p-3'>
        <p className='text-xs'>Your Agent Pairing Code</p>
        <output aria-label='Agent Pairing Code' className='block break-words font-mono text-2xl tracking-wider'>{ticket.code.match(/.{1,4}/g)?.join(' ')}</output>
        <p className='text-xs'>On the call, say all 12 digits, or enter them on the keypad and press *. Pause after speaking. Keypad: press # to start over.</p>
        <p className='text-muted-foreground text-xs'>Expires in {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}. Keep it private: it gives one call access to this workspace.</p>
        <div className='flex flex-wrap gap-2'><Button size='sm' variant='quiet' className='min-h-11' onClick={() => void navigator.clipboard.writeText(ticket.code).catch(() => setError('Couldn’t copy the code.'))}>Copy code</Button><a className='rafii-focus inline-flex min-h-11 items-center rounded-lg border px-3 font-medium' href={`tel:${ticket.phoneNumber}`}>Dial {ticket.phoneNumber}</a><Button size='sm' variant='quiet' className='min-h-11' disabled={busy} onClick={() => void cancel()}>Cancel code</Button></div>
      </div> : <>
        {ticket && <p role='status'>{status.data?.state === 'used' ? 'Code used. Your phone conversation is available in Rafii.' : status.isError ? 'Couldn’t confirm this code. Create a new one before calling.' : 'This code is no longer active. Create a new one to call.'}</p>}
        {status.data?.call && <Link className='rafii-focus min-h-11 content-center underline underline-offset-4' href={`/app/agent/${status.data.call.conversationId}`}>Open phone conversation</Link>}
        {cooldownActive && <p role='status'>You can create another code in {cooldownSeconds}s.</p>}
        <Button variant='glass' size='sm' className='min-h-11' disabled={busy || !creditReady || cooldownActive} onClick={() => void generate()}>{busy ? 'Creating code…' : cooldownActive ? `Try again in ${cooldownSeconds}s` : 'Generate new Agent Pairing Code'}</Button>
      </>}
      <p className='text-muted-foreground text-xs'>Spoken codes are transcribed by OpenAI to verify this call; use the keypad if you prefer. The code lasts five minutes and works once. Creating a code sends no text and places no call. Your carrier may charge for the call.</p>
      {error && <p className='text-destructive' role='alert'>{error}</p>}
    </div>
  </details>;
}
