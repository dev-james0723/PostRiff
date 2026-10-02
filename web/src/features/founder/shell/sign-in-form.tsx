'use client';

/**
 * Founder sign-in (CONTRACTS §6): Supabase password, then a verified authenticator code, then the bearer token is
 * exchanged once for the `__Host-rafii-control` cookie (`POST /session/exchange` with `X-Control-Exchange: 1`).
 * The Supabase client here keeps nothing: `persistSession: false`, so the founder identity never lands in the
 * consumer app's storage, and the password is cleared from state the moment it has been sent. Errors show fixed copy.
 */
import { useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'next/navigation';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp';
import { Label } from '@/components/ui/label';
import { FIELD_CLASS } from '@/features/workspace/rafii-parts';
import { listFactors, verifyTotp } from '@/lib/auth/mfa';
import { CONTROL_EXCHANGE_HEADER, FOUNDER_API_BASE, safeFounderNext } from '@/lib/founder/api';
import { founderErrorMessage } from '@/lib/founder/errors';
import { getSupabaseEnv, hasSupabaseEnv } from '@/lib/supabase/env';

type Step =
  | { kind: 'password' }
  | { kind: 'code'; client: SupabaseClient; factorId: string }
  // The second factor passed but this identity is not (yet) the founder operator here. Enrolment is a reviewed server step;
  // the page keeps retrying the same verified session while its second factor is still fresh enough for Control (300 s).
  | { kind: 'waiting'; token: string; verifiedAt: number };

/** Control accepts an exchange only within 300 s of the second factor; stop retrying a little before that. */
const WAIT_LIMIT_MS = 270_000;
const WAIT_EVERY_MS = 15_000;

const COPY = {
  notConfigured: 'Founder identity is not configured for this deployment.', // copy-audit: allow — founder-only sign-in
  signIn: 'Sign-in could not be verified.',
  noFactor: 'A verified authenticator app is required. Enrol one through Account security first.',
  code: 'Second-factor verification failed.',
  noToken: 'The second factor was accepted but no session token came back. Sign in again.',
  expired: 'The second factor is no longer fresh enough to finish. Start over to sign in again.'
};

async function exchange(accessToken: string): Promise<void> {
  const response = await fetch(`${FOUNDER_API_BASE}/session/exchange`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}`, ...CONTROL_EXCHANGE_HEADER },
    body: '{}',
    cache: 'no-store',
    credentials: 'same-origin'
  });
  if (!response.ok) {
    const safe = (await response.json().catch(() => ({}))) as { code?: string };
    const error = new Error(founderErrorMessage(response.status, safe.code)) as Error & { code?: string };
    error.name = response.status === 401 || response.status === 403 ? 'ExchangeRefused' : 'ExchangeFailed';
    error.code = typeof safe.code === 'string' ? safe.code : undefined;
    throw error;
  }
}

function notYetFounder(failure: unknown): boolean {
  return failure instanceof Error && failure.name === 'ExchangeRefused' && (failure as Error & { code?: string }).code === 'FOUNDER_REQUIRED';
}

export function FounderSignInForm() {
  const params = useSearchParams();
  const next = safeFounderNext(params.get('next'));
  const configured = hasSupabaseEnv();
  const [step, setStep] = useState<Step>({ kind: 'password' });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitPassword() {
    const { url, key } = getSupabaseEnv();
    const client = createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false } });
    const signed = await client.auth.signInWithPassword({ email, password });
    setPassword('');
    if (signed.error) throw new Error(COPY.signIn);
    const totp = (await listFactors(client)).find((factor) => factor.kind === 'totp' && factor.verified);
    if (!totp) throw new Error(COPY.noFactor);
    setStep({ kind: 'code', client, factorId: totp.id });
  }

  async function submitCode(current: Extract<Step, { kind: 'code' }>) {
    try {
      await verifyTotp(current.client, code, current.factorId);
    } catch {
      throw new Error(COPY.code);
    } finally {
      setCode('');
    }
    const { data } = await current.client.auth.getSession();
    const token = data.session?.access_token;
    if (!token) throw new Error(COPY.noToken);
    try {
      await exchange(token);
    } catch (failure) {
      if (notYetFounder(failure)) {
        setStep({ kind: 'waiting', token, verifiedAt: Date.now() });
        return;
      }
      // Any other refusal starts over rather than retrying the same token.
      if (failure instanceof Error && failure.name === 'ExchangeRefused') setStep({ kind: 'password' });
      throw failure;
    }
    window.location.assign(next);
  }

  // Waiting for enrolment: retry the exchange with the same verified session until it succeeds or the factor goes stale.
  useEffect(() => {
    if (step.kind !== 'waiting') return;
    let stopped = false;
    const attempt = async () => {
      if (stopped) return;
      if (Date.now() - step.verifiedAt > WAIT_LIMIT_MS) {
        setStep({ kind: 'password' });
        setError(COPY.expired);
        return;
      }
      try {
        await exchange(step.token);
        if (!stopped) window.location.assign(next);
      } catch (failure) {
        if (stopped) return;
        if (!notYetFounder(failure) && failure instanceof Error && failure.name === 'ExchangeRefused') {
          setStep({ kind: 'password' });
          setError(failure.message);
        }
      }
    };
    const timer = window.setInterval(() => void attempt(), WAIT_EVERY_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [step, next]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (!configured) throw new Error(COPY.notConfigured);
      if (step.kind === 'password') await submitPassword();
      else if (step.kind === 'code') await submitCode(step);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : COPY.signIn);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Surface material='glass' radius='dialog' padding='lg' className='flex flex-col gap-6'>
      <div className='flex flex-col gap-1.5'>
        <span className='rafii-eyebrow'>Rafii · Founder admin</span>
        <h1 className='text-foreground text-[1.625rem] leading-[1.15] font-medium tracking-[-0.02em]'>{step.kind === 'password' ? 'Sign in as the founder' : step.kind === 'code' ? 'Enter your authenticator code' : 'Waiting for founder enrollment'}</h1>
        <p className='text-muted-foreground text-sm leading-relaxed'>
          {step.kind === 'password'
            ? 'Your founder identity, then a second factor. Customer workspace roles do not grant access here.'
            : step.kind === 'code'
              ? 'The six-digit code from your authenticator app. It is checked once and never stored.'
              : 'Your sign-in and second factor are verified, but this account is not enrolled as the founder here yet. Keep this page open: it finishes by itself within about four minutes once enrollment is done.'}
        </p>
      </div>
      {!configured ? (
        <StateMessage kind='unsupported' title='Identity source unavailable' description={COPY.notConfigured} />
      ) : step.kind === 'waiting' ? (
        <div className='flex flex-col gap-4' role='status' aria-live='polite'>
          <StateMessage kind='loading' title='Checking enrollment every 15 seconds' description='Nothing else is needed from you while this page is open.' />
          <Button type='button' variant='quiet' size='sm' onClick={() => setStep({ kind: 'password' })} className='self-center'>
            Start over
          </Button>
        </div>
      ) : (
        <form onSubmit={onSubmit} aria-busy={busy} className='flex flex-col gap-4' noValidate>
          {step.kind === 'password' ? (
            <>
              <div className='flex flex-col gap-2'>
                <Label htmlFor='founder-email'>Founder email</Label>
                <Input id='founder-email' type='email' autoComplete='username' required value={email} onChange={(event) => setEmail(event.target.value)} className={FIELD_CLASS} />
              </div>
              <div className='flex flex-col gap-2'>
                <Label htmlFor='founder-password'>Password</Label>
                <Input id='founder-password' type='password' autoComplete='current-password' required value={password} onChange={(event) => setPassword(event.target.value)} className={FIELD_CLASS} />
              </div>
            </>
          ) : (
            <div className='flex flex-col gap-2'>
              <Label htmlFor='founder-code'>Authenticator code</Label>
              <InputOTP id='founder-code' maxLength={6} value={code} onChange={setCode} autoComplete='one-time-code'>
                <InputOTPGroup>
                  {Array.from({ length: 6 }, (_, index) => (
                    <InputOTPSlot key={index} index={index} />
                  ))}
                </InputOTPGroup>
              </InputOTP>
            </div>
          )}
          {error && (
            <p role='alert' className='text-destructive flex items-start gap-2 text-sm'>
              <Icons.warning className='mt-0.5 size-4 shrink-0' aria-hidden />
              <span>{error}</span>
            </p>
          )}
          <Button type='submit' variant='action' size='control' disabled={busy || (step.kind === 'password' ? !email || !password : code.length < 6)} className='w-full'>
            {busy ? 'Verifying…' : step.kind === 'password' ? 'Continue' : 'Verify founder session'}
          </Button>
          {step.kind === 'code' && (
            <Button type='button' variant='quiet' size='sm' onClick={() => setStep({ kind: 'password' })} disabled={busy} className='self-center'>
              Start over
            </Button>
          )}
        </form>
      )}
      <p className='text-muted-foreground text-xs leading-relaxed'>Sessions last eight hours and end on sign out. Real calls, emails and pushes stay off regardless of who signs in.</p>
    </Surface>
  );
}
