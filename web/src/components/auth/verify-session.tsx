'use client';
import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/lib/auth/session';
import { safeNext } from '@/lib/auth/navigation';
import { MfaChallenge } from './mfa-challenge';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';

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
  if (auth.status === 'unavailable') return <div role='alert' className='flex flex-col gap-3'><p>{auth.error ?? 'Sign-in is unavailable right now.'}</p><Button onClick={() => window.location.reload()}>Try again</Button></div>;
  return <Skeleton role='status' aria-label='Checking sign-in' className='h-32 w-full' />;
}
