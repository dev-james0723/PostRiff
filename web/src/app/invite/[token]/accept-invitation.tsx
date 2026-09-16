'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { siteConfig } from '@/config/site';
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
      router.replace('/app');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'This invitation could not be accepted.');
    } finally {
      setBusy(false);
    }
  }

  if (auth.status === 'loading') {
    return <Skeleton className='h-40 w-full' />;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>You’ve been invited to a PostRiff workspace</CardTitle>
        <CardDescription>
          Accepting adds you as a member with the role the inviter chose. You can leave at any time.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        {error && (
          <Alert variant='destructive'>
            <Icons.alertCircle className='size-4' />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {auth.status === 'unavailable' && (
          <Alert>
            <AlertDescription>{auth.error ?? 'PostRiff is unavailable right now.'}</AlertDescription>
          </Alert>
        )}
        {auth.status === 'signed-out' && (
          <div className='flex flex-col gap-2'>
            <p className='text-muted-foreground text-sm'>Sign in or create an account with the invited email first.</p>
            <Link href={`${siteConfig.links.signIn}?next=${encodeURIComponent(here)}`} className={buttonVariants()}>
              Sign in to accept
            </Link>
            <Link
              href={`${siteConfig.links.signUp}?next=${encodeURIComponent(here)}`}
              className={buttonVariants({ variant: 'outline' })}
            >
              Create an account
            </Link>
          </div>
        )}
        {auth.status === 'signed-in' && !joined && (
          <Button disabled={busy} onClick={() => void accept()}>
            {busy ? 'Joining…' : 'Accept invitation'}
          </Button>
        )}
        {joined && (
          <p className='text-sm'>
            Joined as <strong>{joined.role}</strong>. Taking you to the workspace…
          </p>
        )}
      </CardContent>
    </Card>
  );
}
