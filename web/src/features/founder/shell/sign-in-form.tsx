'use client';

/**
 * Same Rafii account, isolated Founder login. A primary passkey does not bypass the server's fresh-MFA/operator checks.
 * Supabase identity stays memory-only; after exchange the __Host-rafii-control cookie owns the Founder session.
 */
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { useSearchParams } from 'next/navigation';
import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp';
import { Label } from '@/components/ui/label';
import { FIELD_CLASS } from '@/features/workspace/rafii-parts';
import { passkeysSupported } from '@/lib/auth/mfa';
import { passkeySignInEnabled } from '@/lib/auth/passkeys';
import { safeFounderNext } from '@/lib/founder/api';
import {
  beginFounderSignIn, discardFounderIdentity, exchangeFounderToken, FounderSignInError,
  notYetFounder, registerFounderPasskey, verifyFounderFactor, type FounderIdentity
} from '@/lib/founder/sign-in';
import { hasSupabaseEnv } from '@/lib/supabase/env';

type Step =
  | { kind: 'password' }
  | { kind: 'code' | 'passkey'; identity: FounderIdentity }
  | { kind: 'waiting'; identity: FounderIdentity; token: string; verifiedAt: number }
  | { kind: 'setup'; identity: FounderIdentity; verifiedAt: number };

const WAIT_LIMIT_MS = 270_000;
const WAIT_EVERY_MS = 15_000;
const NOT_CONFIGURED = 'Founder identity is not configured for this deployment.'; // copy-audit: allow — founder-only sign-in
const EXPIRED = 'The second factor is no longer fresh enough to finish. Start over to sign in again.';

export function FounderSignInForm() {
  const params = useSearchParams();
  const next = safeFounderNext(params.get('next'));
  const configured = hasSupabaseEnv();
  const [step, setStep] = useState<Step>({ kind: 'password' });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ message: string; notice: boolean } | null>(null);
  const [supportsPasskey, setSupportsPasskey] = useState(false);
  const inFlight = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const currentIdentity = useRef<FounderIdentity | null>(null);
  const exchanged = useRef(false);
  const mounted = useRef(true);
  const offerPasskey = passkeySignInEnabled() && supportsPasskey;

  useEffect(() => {
    mounted.current = true;
    setSupportsPasskey(passkeysSupported());
    return () => {
      mounted.current = false;
      controller.current?.abort();
      // Revoking the accepted upstream session would invalidate the new Founder cookie. Only abandon unused identities.
      if (currentIdentity.current && !exchanged.current) void discardFounderIdentity(currentIdentity.current);
    };
  }, []);

  const startOver = useCallback(() => {
    // A server refusal resets the form inside run(); preserve its error instead of marking that completed request cancelled.
    if (!inFlight.current) controller.current?.abort();
    if (currentIdentity.current && !exchanged.current) void discardFounderIdentity(currentIdentity.current);
    currentIdentity.current = null;
    exchanged.current = false;
    setPassword('');
    setCode('');
    setFeedback(null);
    setStep({ kind: 'password' });
  }, []);

  const complete = useCallback((identity: FounderIdentity, verifiedAt: number) => {
    exchanged.current = true;
    if (!mounted.current) return;
    // Registration is optional, user-initiated, and offered only AFTER the server accepts Founder authority.
    if (offerPasskey && identity.method === 'password') setStep({ kind: 'setup', identity, verifiedAt });
    else window.location.assign(next);
  }, [next, offerPasskey]);

  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setFeedback(null);
    const pending = new AbortController();
    controller.current = pending;
    try {
      if (!configured) throw new FounderSignInError(NOT_CONFIGURED);
      await action(pending.signal);
    } catch (error) {
      if (mounted.current && !pending.signal.aborted) {
        const known = error instanceof FounderSignInError || (error instanceof Error && ['ExchangeRefused', 'ExchangeFailed'].includes(error.name));
        setFeedback({ message: known ? (error as Error).message : 'Sign-in could not be verified. Try again.', notice: error instanceof FounderSignInError && error.kind === 'cancelled' });
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function signIn(method: 'password' | 'passkey', signal: AbortSignal) {
    const secret = password;
    setPassword('');
    const identity = await beginFounderSignIn(method === 'password' ? { method, email, password: secret } : { method }, signal);
    if (!mounted.current || signal.aborted) { await discardFounderIdentity(identity); return; }
    currentIdentity.current = identity;
    setEmail(identity.email);
    if (identity.passkeyFactorId && supportsPasskey) setStep({ kind: 'passkey', identity });
    else if (identity.totpFactorId) setStep({ kind: 'code', identity });
    else {
      startOver();
      throw new FounderSignInError('Your enrolled second factor is not available in this browser. Use a supported device or Account security.');
    }
  }

  async function verify(current: Extract<Step, { kind: 'code' | 'passkey' }>, signal: AbortSignal) {
    let token: string;
    try {
      token = await verifyFounderFactor(current.identity, current.kind === 'code' ? { kind: 'totp', code } : { kind: 'webauthn' });
    } finally {
      setCode('');
    }
    if (!mounted.current || signal.aborted) return;
    const verifiedAt = Date.now();
    try {
      await exchangeFounderToken(token);
    } catch (error) {
      if (notYetFounder(error)) { setStep({ kind: 'waiting', identity: current.identity, token, verifiedAt }); return; }
      if (error instanceof Error && error.name === 'ExchangeRefused') startOver();
      throw error;
    }
    complete(current.identity, verifiedAt);
  }

  useEffect(() => {
    if (step.kind !== 'waiting') return;
    let stopped = false;
    let pending = false;
    const attempt = async () => {
      if (stopped || pending) return;
      if (Date.now() - step.verifiedAt > WAIT_LIMIT_MS) {
        startOver();
        setFeedback({ message: EXPIRED, notice: false });
        return;
      }
      pending = true;
      try {
        await exchangeFounderToken(step.token);
        if (!stopped) complete(step.identity, step.verifiedAt);
      } catch (error) {
        if (!stopped && !notYetFounder(error) && error instanceof Error && error.name === 'ExchangeRefused') {
          startOver();
          setFeedback({ message: error.message, notice: false });
        }
      } finally { pending = false; }
    };
    const timer = window.setInterval(() => void attempt(), WAIT_EVERY_MS);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [step, startOver, complete]);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (step.kind === 'password') void run((signal) => signIn('password', signal));
    else if (step.kind === 'code' || step.kind === 'passkey') void run((signal) => verify(step, signal));
  }

  const heading = step.kind === 'password' ? 'Sign in as the founder'
    : step.kind === 'code' ? 'Enter your authenticator code'
      : step.kind === 'passkey' ? 'Verify your second factor'
        : step.kind === 'setup' ? 'Set up faster sign-in' : 'Waiting for founder enrollment';

  return (
    <Surface material='glass' radius='dialog' padding='lg' className='flex flex-col gap-6'>
      <div className='flex flex-col gap-1.5'>
        <span className='rafii-eyebrow'>Rafii · Founder admin</span>
        <h1 className='text-foreground text-[1.625rem] leading-[1.15] font-medium tracking-[-0.02em]'>{heading}</h1>
        <p className='text-muted-foreground text-sm leading-relaxed'>
          {step.kind === 'password'
            ? 'Use your existing Rafii account. Founder access and a fresh second factor are checked separately.'
            : step.kind === 'code'
              ? 'Enter the six-digit code from your authenticator app. A passkey sign-in does not replace this second-factor check.'
              : step.kind === 'passkey'
                ? 'Confirm with your enrolled second-factor passkey. Your device may use Face ID, Touch ID or a security key.'
                : step.kind === 'setup'
                  ? 'Your Founder session is verified. Save a passkey on this device to replace the password next time. Your second factor still applies.'
                  : 'Your identity and second factor are verified. This account still needs approved Founder enrollment. This page retries for about four minutes.'}
        </p>
        {step.kind !== 'password' && <p className='text-muted-foreground break-all text-xs'>Account: {step.identity.email}</p>}
      </div>
      {feedback && <p role={feedback.notice ? 'status' : 'alert'} className={`${feedback.notice ? 'text-muted-foreground' : 'text-destructive'} flex items-start gap-2 text-sm`}>
        {!feedback.notice && <Icons.warning className='mt-0.5 size-4 shrink-0' aria-hidden />}<span>{feedback.message}</span>
      </p>}
      {!configured ? <StateMessage kind='unsupported' title='Identity source unavailable' description={NOT_CONFIGURED} />
        : step.kind === 'waiting' ? (
          <div className='flex flex-col gap-4' role='status' aria-live='polite'>
            <StateMessage kind='loading' title='Checking enrollment every 15 seconds' description='Keep this page open while your account is enrolled. No new account is created.' />
            <Button type='button' variant='quiet' size='sm' onClick={startOver} className='self-center'>Use a different account</Button>
          </div>
        ) : step.kind === 'setup' ? (
          <div className='flex flex-col gap-3' aria-busy={busy}>
            <Button type='button' variant='action' size='control' disabled={busy} onClick={() => void run(async () => {
              if (Date.now() - step.verifiedAt > WAIT_LIMIT_MS) throw new FounderSignInError('Sign in again to add a passkey. You can continue to Founder without adding one.');
              await registerFounderPasskey(step.identity);
              if (mounted.current) window.location.assign(next);
            })}>
              <Icons.key className='size-4' aria-hidden />{busy ? 'Waiting for your device…' : 'Set up Face ID / Passkey'}
            </Button>
            <Button type='button' variant='quiet' size='control' disabled={busy} onClick={() => window.location.assign(next)}>Continue to Founder</Button>
          </div>
        ) : (
          <form onSubmit={onSubmit} aria-busy={busy} className='flex flex-col gap-4' noValidate>
            {step.kind === 'password' ? <>
              {offerPasskey && <>
                <Button type='button' variant='action' size='control' disabled={busy} className='w-full' onClick={() => void run((signal) => signIn('passkey', signal))}>
                  <Icons.key className='size-4' aria-hidden />{busy ? 'Verifying…' : 'Sign in with Face ID / Passkey'}
                </Button>
                <p className='text-muted-foreground text-center text-xs'>Or use your password</p>
              </>}
              <div className='flex flex-col gap-2'>
                <Label htmlFor='founder-email'>Founder email</Label>
                <Input id='founder-email' type='email' autoComplete='username' required disabled={busy} value={email} onChange={(event) => setEmail(event.target.value)} className={FIELD_CLASS} />
              </div>
              <div className='flex flex-col gap-2'>
                <Label htmlFor='founder-password'>Password</Label>
                <Input id='founder-password' type='password' autoComplete='current-password' required disabled={busy} value={password} onChange={(event) => setPassword(event.target.value)} className={FIELD_CLASS} />
              </div>
            </> : step.kind === 'code' ? <div className='flex flex-col gap-2'>
              <Label htmlFor='founder-code'>Authenticator code</Label>
              <InputOTP id='founder-code' maxLength={6} value={code} disabled={busy} onChange={setCode} autoComplete='one-time-code'>
                <InputOTPGroup>{Array.from({ length: 6 }, (_, index) => <InputOTPSlot key={index} index={index} />)}</InputOTPGroup>
              </InputOTP>
            </div> : null}
            <Button type='submit' variant={step.kind === 'password' && offerPasskey ? 'glass' : 'action'} size='control' disabled={busy || (step.kind === 'password' ? !email || !password : step.kind === 'code' && code.length < 6)} className='w-full'>
              {busy ? 'Verifying…' : step.kind === 'password' ? 'Continue' : step.kind === 'passkey' ? 'Verify with Face ID / Passkey' : 'Verify founder session'}
            </Button>
            {step.kind !== 'password' && <>
              {step.kind === 'passkey' && step.identity.totpFactorId && <Button type='button' variant='quiet' size='sm' disabled={busy} onClick={() => { setFeedback(null); setStep({ kind: 'code', identity: step.identity }); }}>Use authenticator code instead</Button>}
              {step.kind === 'code' && supportsPasskey && step.identity.passkeyFactorId && <Button type='button' variant='quiet' size='sm' disabled={busy} onClick={() => { setCode(''); setFeedback(null); setStep({ kind: 'passkey', identity: step.identity }); }}>Use second-factor passkey instead</Button>}
              <Button type='button' variant='quiet' size='sm' onClick={startOver} disabled={busy} className='self-center'>Use a different account</Button>
            </>}
          </form>
        )}
      <p className='text-muted-foreground text-xs leading-relaxed'>Sessions last eight hours and end on sign out. Real calls, emails and pushes stay off regardless of who signs in.</p>
    </Surface>
  );
}
