'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp';
import { Label } from '@/components/ui/label';
import { listFactors, passkeysSupported, verifyPasskey, verifyTotp, type SecondFactor } from '@/lib/auth/mfa';
import { useAuth } from '@/lib/auth/session';
import { AuthSurface } from './auth-form';

/**
 * Second step of sign-in for accounts with two-factor authentication on. AppGate shows it while
 * the session is AAL1 but a verified factor exists; the API refuses such sessions until this passes.
 * A passkey is offered first when the account has one; a code from an authenticator app is the
 * other route. Nothing prompts the device without a click.
 */
export function MfaChallenge() {
  const auth = useAuth();
  const [factors, setFactors] = useState<SecondFactor[] | null>(null);
  const [mode, setMode] = useState<'auto' | 'code' | 'passkey'>('auto');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!auth.supabase) return;
    let cancelled = false;
    listFactors(auth.supabase)
      .then((list) => {
        if (!cancelled) setFactors(list.filter((factor) => factor.verified));
      })
      .catch(() => {
        if (!cancelled) setFactors([]);
      });
    return () => {
      cancelled = true;
    };
  }, [auth.supabase]);

  const hasPasskey = passkeysSupported() && (factors ?? []).some((factor) => factor.kind === 'webauthn');
  const hasCode = (factors ?? []).some((factor) => factor.kind === 'totp');
  const showCode = mode === 'code' || (mode === 'auto' && !hasPasskey);

  async function run(step: () => Promise<void>, fallback: string) {
    if (!auth.supabase) return;
    setBusy(true);
    setError(null);
    try {
      await step();
      await auth.completeMfa();
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
      setCode('');
    } finally {
      setBusy(false);
    }
  }

  const client = auth.supabase;

  return (
    <div className='flex w-full items-center justify-center'>
      <div className='w-full max-w-[26.5rem]'>
        <AuthSurface>
          <header className='flex flex-col gap-3'>
            <span aria-hidden className='rafii-glass text-foreground flex size-11 items-center justify-center rounded-full'>
              <Icons.shieldCheck className='size-5' />
            </span>
            <h1 className='text-foreground text-[1.625rem] leading-[1.15] font-medium tracking-[-0.02em] text-balance md:text-[1.875rem]'>Confirm it&apos;s you</h1>
            <p className='text-muted-foreground text-sm leading-relaxed'>
              Two-factor authentication is on for this account.{' '}
              {showCode ? 'Enter the 6-digit code from your authenticator app.' : 'Use the passkey saved on this device.'}
            </p>
          </header>

          {error && <StateMessage kind='error' layout='inline' title={error} />}

          {factors === null ? (
            <StateMessage kind='loading' title='Checking your sign-in methods' className='bg-transparent p-0' />
          ) : factors.length === 0 ? (
            <p role='alert' className='text-foreground text-sm leading-relaxed'>
              Your account expects a second factor, but none could be listed. Sign out and try again, or use the sign-in help below.
            </p>
          ) : showCode ? (
            <form
              className='flex flex-col gap-4'
              onSubmit={(event) => {
                event.preventDefault();
                void run(() => verifyTotp(client as NonNullable<typeof client>, code), 'That code did not work. Wait for the next one and try again.');
              }}
            >
              <div className='flex flex-col gap-2'>
                <Label htmlFor='mfa-code'>Verification code</Label>
                <InputOTP id='mfa-code' maxLength={6} value={code} onChange={setCode}>
                  <InputOTPGroup>
                    {Array.from({ length: 6 }).map((_, i) => (
                      <InputOTPSlot key={i} index={i} />
                    ))}
                  </InputOTPGroup>
                </InputOTP>
              </div>
              <div className='flex flex-wrap gap-2'>
                <Button type='submit' variant='action' size='control' disabled={busy || code.trim().length < 6}>
                  {busy ? 'Verifying…' : 'Verify and continue'}
                </Button>
                {hasPasskey && (
                  <Button type='button' variant='quiet' size='control' disabled={busy} onClick={() => setMode('passkey')}>
                    Use Face ID / Touch ID instead
                  </Button>
                )}
              </div>
            </form>
          ) : (
            <div className='flex flex-col gap-2'>
              <Button
                variant='action'
                size='control'
                disabled={busy}
                onClick={() => void run(() => verifyPasskey(client as NonNullable<typeof client>), 'Your device did not complete the passkey step.')}
              >
                <Icons.key className='size-4' aria-hidden />
                {busy ? 'Waiting for your device…' : 'Continue with Face ID / Touch ID'}
              </Button>
              {hasCode && (
                <Button variant='quiet' size='control' disabled={busy} onClick={() => setMode('code')}>
                  Use a code from my authenticator app instead
                </Button>
              )}
            </div>
          )}

          <div className='flex flex-wrap items-center justify-between gap-3'>
            <Link href='/auth/reset' className='rafii-focus text-muted-foreground rounded-sm text-sm underline underline-offset-4'>
              Lost access to your authenticator?
            </Link>
            <Button variant='quiet' size='sm' className='min-h-11' disabled={busy} onClick={() => void auth.signOut()}>
              Sign out
            </Button>
          </div>
        </AuthSurface>
      </div>
    </div>
  );
}
