'use client';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { safeNext, verifyHref } from '@/lib/auth/navigation';
import { useAuth } from '@/lib/auth/session';
import { buttonVariants } from '@/components/ui/button';

/** This app signs in with codes, Google or passkeys; there is no password to reset. */
export function SignInHelp() {
  const params = useSearchParams();
  const auth = useAuth();
  const next = safeNext(params.get('next'));
  return <div className='flex flex-col gap-5'><h1 className='text-2xl font-semibold'>Help signing in</h1>
    <p className='text-muted-foreground text-sm'>PostRiff uses email codes, Google or passkeys. There is no PostRiff password to reset. Request a new email code from the sign-in page, or use your original Google account.</p>
    <Link className={buttonVariants()} href={`/auth/sign-in?next=${encodeURIComponent(next)}`}>Return to sign in</Link>
    <h2 className='text-sm font-medium'>Lost your second factor?</h2>
    <p className='text-muted-foreground text-sm'>If another enrolled passkey or authenticator is available, use it to confirm your sign-in. A new email code does not turn off two-factor authentication.</p>
    {auth.status === 'mfa-required' && <Link href={verifyHref(next)} className='text-sm underline'>Try another enrolled factor</Link>}
    <Link href='/contact' className='text-sm underline'>Contact support about account access</Link>
    <p className='text-muted-foreground text-xs'>Recovery needs an identity check. This page cannot disable two-factor authentication or promise that access can be restored.</p>
  </div>;
}
