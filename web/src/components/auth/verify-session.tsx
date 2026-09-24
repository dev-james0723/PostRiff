'use client';
import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth/session';
import { safeNext } from '@/lib/auth/navigation';
import { AuthSurface } from './auth-form';
import { MfaChallenge } from './mfa-challenge';

export function VerifySession() {
  const auth = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get('next'));
  useEffect(() => {
    if (auth.status === 'signed-out') router.replace(`/auth/sign-in?next=${encodeURIComponent(next)}`);
    if (auth.status === 'signed-in') router.replace(next);
  }, [auth.status, router, next]);
  if (auth.status === 'mfa-required') return <MfaChallenge />;
  if (auth.status === 'unavailable') {
    return (
      <AuthSurface>
        <StateMessage
          kind='offline'
          title={auth.error ?? 'Sign-in is unavailable right now.'}
          action={
            <Button variant='glass' size='control' onClick={() => window.location.reload()}>
              Try again
            </Button>
          }
          className='bg-transparent px-0 py-2'
        />
      </AuthSurface>
    );
  }
  return (
    <AuthSurface>
      <StateMessage kind='loading' title='Checking sign-in' className='bg-transparent p-0' />
    </AuthSurface>
  );
}
