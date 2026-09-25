'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AuthSurface } from '@/components/auth/auth-form';
import { PageHeader, StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { siteConfig } from '@/config/site';
import { invitationLanding, verifyHref } from '@/lib/auth/navigation';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/session';

export function AcceptInvitation({ token }: { token: string }) {
  const auth = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [joined, setJoined] = useState<{ workspaceId: string; role: string } | null>(null);

  const here = `/invite/${encodeURIComponent(token)}`;

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      const result = await auth.api.acceptInvitation(token);
      setJoined(result);
      try {
        localStorage.setItem('postriff-workspace', result.workspaceId);
      } catch {
        /* ignore */
      }
      router.replace(invitationLanding(result));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Couldn’t accept this invitation.');
    } finally {
      setBusy(false);
    }
  }

  if (auth.status === 'loading') {
    return (
      <AuthSurface>
        <StateMessage kind='loading' title='Checking your invitation' className='bg-transparent p-0' />
      </AuthSurface>
    );
  }

  return (
    <AuthSurface>
      <PageHeader
        title='You’re invited to a Rafii workspace'
        description='You’ll join with the role the inviter chose. You can leave any time.'
      />
      {error && <StateMessage kind='error' layout='inline' title={error} />}
      {auth.status === 'unavailable' && <StateMessage kind='offline' layout='inline' title={auth.error ?? 'Rafii is unavailable right now.'} />}
      {auth.status === 'mfa-required' && (
        <Link href={verifyHref(here)} className={buttonVariants({ variant: 'action', size: 'control' })}>
          Confirm two-factor to accept
        </Link>
      )}
      {auth.status === 'signed-out' && (
        <div className='flex flex-col gap-3'>
          <p className='text-muted-foreground text-sm leading-relaxed'>Sign in to accept. Anyone with this link can accept it, and the workspace records who joined.</p>
          <Link href={`${siteConfig.links.signIn}?next=${encodeURIComponent(here)}`} className={buttonVariants({ variant: 'action', size: 'control' })}>
            Sign in to accept
          </Link>
          <Link href={`${siteConfig.links.signUp}?next=${encodeURIComponent(here)}`} className={buttonVariants({ variant: 'glass', size: 'control' })}>
            Create an account
          </Link>
        </div>
      )}
      {auth.status === 'signed-in' && !joined && (
        <Button variant='action' size='control' disabled={busy} onClick={() => void accept()}>
          {busy ? 'Joining…' : 'Accept invitation'}
        </Button>
      )}
      {joined && (
        <StateMessage
          kind='success'
          layout='inline'
          title={
            <>
              Joined as <strong>{joined.role}</strong>.
            </>
          }
          description='Taking you to the workspace…'
        />
      )}
    </AuthSurface>
  );
}
