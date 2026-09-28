'use client';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { verifyPasskey, passkeysSupported } from '@/lib/auth/mfa';
import { DialInRafii } from './dial-in-rafii';

export function VerifyCall() {
  const id = useSearchParams().get('challenge') ?? '';
  return <CallApproval key={id} id={id} />;
}
function CallApproval({ id }: { id: string }) {
  const auth = useAuth();
  const { api, workspaceId } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [now, setNow] = useState(() => Date.now() / 1000);
  const abort = useRef<AbortController | null>(null);
  const validId = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(id);
  const query = useQuery({ queryKey: ['phone-auth', auth.user?.id, id], queryFn: () => api.phoneAuthStatus(id), enabled: validId && auth.status === 'signed-in', retry: false, refetchInterval: 1500 });
  const item = query.data;
  const pending = item?.state === 'pending' && item.expiresAt > now && !query.isError;
  useEffect(() => { const timer = setInterval(() => setNow(Date.now() / 1000), 1000); return () => { clearInterval(timer); abort.current?.abort(); }; }, []);
  async function confirm() {
    if (!pending || !auth.supabase || busy) return;
    setBusy(true); setError(''); abort.current = new AbortController();
    try {
      await verifyPasskey(auth.supabase, undefined, { signal: abort.current.signal,
        prepare: (factor) => api.phoneAuthPrepare(id, factor),
        approve: (credential) => api.phoneAuthApprove(id, credential, Boolean(item?.spending.usesCredits)) });
    } catch (err) { setError(err instanceof Error ? err.message : 'Verification did not complete.'); }
    finally { setBusy(false); void query.refetch(); }
  }
  async function dismiss(action: 'deny' | 'fallback' | 'cancel') {
    abort.current?.abort(); setBusy(true); setError('');
    try { await api.phoneAuthDismiss(id, action); }
    catch { setError('Couldn’t confirm the change. Hang up to end this call.'); }
    finally { setBusy(false); void query.refetch(); }
  }
  return <main className='mx-auto flex w-full max-w-xl flex-col gap-6 p-5 sm:p-8' aria-labelledby='verify-call-title'>
    <div><p className='text-muted-foreground mb-2 text-sm'>Agent call security</p><h1 id='verify-call-title' className='text-2xl font-semibold'>Verify your Rafii call</h1></div>
    <p>Only approve if you are calling Rafii right now. Your device verifies your passkey; your biometric data stays on your device.</p>
    {(!validId || query.isError) && <p role='alert'>This call verification is unavailable. Hang up or use a new Agent Pairing Code.</p>}
    {query.isLoading && <p role='status'>Checking the current call…</p>}
    {item && <section className='space-y-4 rounded-2xl border border-border/60 p-5'>
      <p>Call started <time dateTime={new Date(item.startedAt * 1000).toISOString()}>{new Date(item.startedAt * 1000).toLocaleTimeString()}</time></p>
      <p role='status'>{pending ? `Expires in ${Math.max(0, Math.ceil(item.expiresAt - now))} seconds.` : item.state === 'approved' || item.state === 'consumed' ? 'Call verified. Return to your call.' : 'This verification is no longer active. Your call has no private access.'}</p>
      {pending && <>
        {item.spending.usesCredits && <p className='text-sm text-muted-foreground'>Approving uses your available credits for phone time, voice and Rafii’s reasoning, reserved a minute at a time. Calls end when credits run out or after one hour. Paid tasks still need their own approval.</p>}
        <Button className='min-h-12 w-full whitespace-normal' disabled={busy || !auth.supabase || !passkeysSupported()} onClick={() => void confirm()}>{busy ? 'Waiting for your passkey…' : 'Confirm with Face ID / Touch ID'}</Button>
        <p className='text-xs text-muted-foreground'>Windows Hello and security keys work too. Choose the passkey registered with Rafii.</p>
        <Button variant='quiet' className='min-h-12 w-full whitespace-normal' onClick={() => void dismiss('fallback')} disabled={busy}>Use a new 12-digit Agent Pairing Code instead</Button>
        <Button variant='quiet' className='min-h-12 w-full' onClick={() => void dismiss('deny')} disabled={busy}>This wasn’t me</Button>
        {busy && <Button variant='quiet' className='min-h-12 w-full' onClick={() => void dismiss('cancel')}>Cancel verification</Button>}
      </>}
    </section>}
    {error && <p role='alert' className='text-destructive'>{error}</p>}
    {item && item.workspaceId === workspaceId && item.state === 'fallback' && <DialInRafii />}
    <Link className='rafii-focus min-h-11 content-center underline' href='/app/account/profile#profile-security'>Manage passkeys and authenticator backup</Link>
    <Link className='rafii-focus min-h-11 content-center underline' href='/app/account/notifications#phone-mode'>Agent Pairing Code and trusted callers</Link>
  </main>;
}
