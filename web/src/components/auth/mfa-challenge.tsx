'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { listFactors, passkeysSupported, verifyPasskey, verifyTotp, type SecondFactor } from '@/lib/auth/mfa';
import { useAuth } from '@/lib/auth/session';

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
      <div className='flex w-full max-w-sm flex-col gap-6'>
        <header className='flex flex-col gap-3'>
          <div className='bg-primary/10 text-primary flex size-10 items-center justify-center rounded-lg'>
            <Icons.shieldCheck className='size-5' aria-hidden />
          </div>
          <h1 className='text-2xl font-semibold tracking-tight'>Confirm it&apos;s you</h1>
          <p className='text-muted-foreground text-sm'>
            Two-factor authentication is on for this account.{' '}
            {showCode ? 'Enter the 6-digit code from your authenticator app.' : 'Use the passkey saved on this device.'}
          </p>
        </header>

        {error && (
          <Alert variant='destructive'>
            <Icons.alertCircle className='size-4' />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {factors === null ? (
          <Skeleton className='h-10 w-full' />
        ) : factors.length === 0 ? (
          <p role='alert' className='text-sm'>Your account expects a second factor, but none could be listed. Sign out and try again, or use the sign-in help below.</p>
        ) : showCode ? (
          <form
            className='flex flex-col gap-4'
            onSubmit={(event) => {
              event.preventDefault();
              void run(() => verifyTotp(client as NonNullable<typeof client>, code), 'That code did not work. Wait for the next one and try again.');
            }}
          >
            <div className='flex flex-col gap-1.5'>
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
              <Button type='submit' disabled={busy || code.trim().length < 6}>
                {busy ? 'Verifying…' : 'Verify and continue'}
              </Button>
              {hasPasskey && (
                <Button type='button' variant='ghost' disabled={busy} onClick={() => setMode('passkey')}>
                  Use Face ID / Touch ID instead
                </Button>
              )}
            </div>
          </form>
        ) : (
          <div className='flex flex-col gap-3'>
            <Button
              disabled={busy}
              onClick={() => void run(() => verifyPasskey(client as NonNullable<typeof client>), 'Your device did not complete the passkey step.')}
            >
              <Icons.key className='size-4' aria-hidden />
              {busy ? 'Waiting for your device…' : 'Continue with Face ID / Touch ID'}
            </Button>
            {hasCode && (
              <Button variant='ghost' disabled={busy} onClick={() => setMode('code')}>
                Use a code from my authenticator app instead
              </Button>
            )}
          </div>
        )}

        <Link href='/auth/reset' className='text-muted-foreground text-sm underline'>Lost access to your authenticator?</Link>
        <Button variant='ghost' className='w-fit' disabled={busy} onClick={() => void auth.signOut()}>
          Sign out
        </Button>
      </div>
    </div>
  );
}
