'use client';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { PageHeader } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { safeNext, verifyHref } from '@/lib/auth/navigation';
import { useAuth } from '@/lib/auth/session';
import { cn } from '@/lib/utils';
import { AuthSurface } from './auth-form';

const linkClass = 'rafii-focus text-foreground rounded-sm text-sm underline underline-offset-4';

/** This app signs in with codes, Google or passkeys; there is no password to reset. */
export function SignInHelp() {
  const params = useSearchParams();
  const auth = useAuth();
  const next = safeNext(params.get('next'));
  return (
    <AuthSurface>
      <PageHeader
        title='Help signing in'
        description='PostRiff uses email codes, Google or passkeys. There is no PostRiff password to reset. Request a new email code from the sign-in page, or use your original Google account.'
      />
      <Link className={cn(buttonVariants({ variant: 'action', size: 'control' }), 'self-start')} href={`/auth/sign-in?next=${encodeURIComponent(next)}`}>
        Return to sign in
      </Link>
      <div className='flex flex-col gap-2'>
        <h2 className='text-foreground text-sm font-medium'>Lost your second factor?</h2>
        <p className='text-muted-foreground text-sm leading-relaxed'>
          If another enrolled passkey or authenticator is available, use it to confirm your sign-in. A new email code does not turn off two-factor authentication.
        </p>
        {auth.status === 'mfa-required' && (
          <Link href={verifyHref(next)} className={`${linkClass} self-start`}>
            Try another enrolled factor
          </Link>
        )}
        <Link href='/contact' className={`${linkClass} self-start`}>
          Contact support about account access
        </Link>
      </div>
      <p className='text-muted-foreground text-xs leading-relaxed'>
        Recovery needs an identity check. This page cannot disable two-factor authentication or promise that access can be restored.
      </p>
    </AuthSurface>
  );
}
