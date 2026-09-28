'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { listFactors, verifyPasskey } from '@/lib/auth/mfa';
import { Button } from '@/components/ui/button';

export function AgentCallSecurity() {
  const auth = useAuth();
  const { api, workspaceId } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const factors = useQuery({ queryKey: ['phone-passkeys', auth.user?.id], queryFn: () => listFactors(auth.supabase!), enabled: Boolean(auth.supabase), retry: false });
  const routes = useQuery({ queryKey: ['trusted-callers', auth.user?.id, workspaceId], queryFn: () => api.phoneTrustedCallers(workspaceId!), enabled: Boolean(workspaceId), retry: false });
  async function revoke(id: string) {
    if (!workspaceId || !auth.supabase || busy) return;
    setBusy(true); setError('');
    try { await verifyPasskey(auth.supabase); await api.phoneRevokeCaller(workspaceId, id); await routes.refetch(); }
    catch { setError('Couldn’t revoke this caller. Confirm your passkey and try again.'); }
    finally { setBusy(false); }
  }
  return <section className='space-y-3 rounded-xl border border-border/60 p-4' aria-labelledby='agent-call-security'>
    <h3 id='agent-call-security' className='font-medium'>Agent call security</h3>
    <p>Passkey ready: {factors.isLoading ? 'Checking…' : factors.data?.some((f) => f.kind === 'webauthn' && f.verified) ? 'Yes' : 'No'}</p>
    <p className='text-muted-foreground text-xs'>Caller identity only routes a verification request. Each returning call needs a fresh passkey check. First-time or recovery code: expires in 5 minutes and works once.</p>
    <Link href='/app/account/profile#profile-security' className='rafii-focus inline-flex min-h-11 items-center underline'>Add passkey or authenticator backup</Link>
    <p className='font-medium'>Trusted callers</p>
    {routes.isError && <p role='alert'>Trusted callers could not be loaded.</p>}
    {routes.data?.callers.length === 0 && <p className='text-muted-foreground'>No trusted callers yet. Your first successful Agent Pairing Code creates one.</p>}
    {routes.data?.callers.map((caller) => <div key={caller.id} className='flex flex-wrap items-center justify-between gap-2'>
      <span>Paired {new Date(caller.pairedAt * 1000).toLocaleString()}{caller.lastUsedAt && <span className='block text-xs text-muted-foreground'>Last used {new Date(caller.lastUsedAt * 1000).toLocaleString()}</span>}</span>
      <Button variant='quiet' className='min-h-11' disabled={busy || !auth.supabase} onClick={() => void revoke(caller.id)}>Revoke trusted caller</Button>
    </div>)}
    {error && <p role='alert'>{error}</p>}
  </section>;
}
