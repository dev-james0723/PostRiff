'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Icons } from '@/components/icons';
import { PageHeader, StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { safeNext, verifyHref } from '@/lib/auth/navigation';
import { plans } from '@/config/plans';
import { siteConfig } from '@/config/site';
import { passkeysSupported } from '@/lib/auth/mfa';
import { passkeySignInEnabled, signInWithPasskey } from '@/lib/auth/passkeys';
import { devSignIn, useAuth } from '@/lib/auth/session';
import { rememberPlan, selectedPlan, type TrialPlan } from '@/lib/workspace/provider';
import { rafiiInput } from './form-styles';

const TRIAL_PLANS: { id: TrialPlan; label: string; note: string }[] = [
  { id: 'studio', label: 'Studio', note: 'Manual drafting and scheduling' },
  { id: 'assist', label: 'Studio Assist', note: 'Adds AI writing batches' }
];

/** The one central surface every auth page uses (DNA §21.16): glass over the ambient canvas. */
export function AuthSurface({ children }: { children: React.ReactNode }) {
  return (
    <Surface material='glass' radius='dialog' padding='lg' className='flex flex-col gap-6'>
      {children}
    </Surface>
  );
}

const linkClass = 'rafii-focus text-foreground rounded-sm underline underline-offset-4';

export function AuthForm({ intent }: { intent: 'sign-in' | 'sign-up' }) {
  const auth = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get('next'));
  const callbackError = params.get('error');

  const [plan, setPlan] = useState<TrialPlan>('studio');
  const [email, setEmail] = useState(params.get('email') ?? '');
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(callbackError ? 'Sign-in could not be completed. Please try again.' : null);

  useEffect(() => {
    const fromUrl = params.get('plan');
    setPlan(fromUrl === 'assist' ? 'assist' : fromUrl === 'studio' ? 'studio' : selectedPlan());
  }, [params]);

  useEffect(() => {
    if (auth.status === 'signed-in') router.replace(next);
    if (auth.status === 'mfa-required') router.replace(verifyHref(next));
  }, [auth.status, next, router]);

  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  async function google() {
    rememberPlan(plan);
    const { createClient } = await import('@/lib/supabase/client');
    const { error: oauthError } = await createClient().auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}` }
    });
    if (oauthError) throw oauthError;
  }

  async function passkey() {
    const { createClient } = await import('@/lib/supabase/client');
    await signInWithPasskey(createClient());
    router.replace(verifyHref(next));
  }

  // Existing accounts only: a passkey is registered from the profile after the first sign-in.
  const offerPasskey = intent === 'sign-in' && passkeySignInEnabled() && passkeysSupported();

  async function sendCode() {
    rememberPlan(plan);
    const { createClient } = await import('@/lib/supabase/client');
    const { error: otpError } = await createClient().auth.signInWithOtp({
      email: email.trim(),
      options: { shouldCreateUser: intent === 'sign-up' }
    });
    if (otpError) throw otpError;
    setSent(true);
  }

  async function verifyCode() {
    const { createClient } = await import('@/lib/supabase/client');
    const { data, error: verifyError } = await createClient().auth.verifyOtp({
      email: email.trim(),
      token: code.trim(),
      type: 'email'
    });
    if (verifyError) throw verifyError;
    if (!data.session) throw new Error('The code did not create a session. Request a new one.');
    router.replace(verifyHref(next));
  }

  const title = intent === 'sign-up' ? 'Create your PostRiff workspace' : 'Sign in to PostRiff';
  const subtitle =
    intent === 'sign-up'
      ? '14-day trial. No card. Export everything, any time.'
      : 'Welcome back. Your drafts are where you left them.';

  if (auth.status === 'loading') {
    return (
      <AuthSurface>
        <StateMessage kind='loading' title='Loading' className='bg-transparent p-0' />
      </AuthSurface>
    );
  }

  if (auth.status === 'unavailable') {
    return (
      <AuthSurface>
        <StateMessage
          kind='offline'
          title='Sign-in is unavailable right now.'
          description={auth.error ?? undefined}
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

  const PlanChooser = intent === 'sign-up' && !next.startsWith('/invite/') && (
    <fieldset className='flex flex-col gap-2'>
      <legend className='text-foreground mb-2 text-sm font-medium'>Trial plan</legend>
      <RadioGroup value={plan} onValueChange={(value) => setPlan(value === 'assist' ? 'assist' : 'studio')}>
        {TRIAL_PLANS.map((option) => {
          const priced = plans.find((p) => p.id === option.id);
          return (
            <Label
              key={option.id}
              htmlFor={`plan-${option.id}`}
              className='rafii-quiet has-data-checked:rafii-glass-selected flex min-h-14 cursor-pointer items-center gap-3 rounded-[var(--rafii-radius-control)] px-3.5 py-3 transition-colors'
            >
              <RadioGroupItem id={`plan-${option.id}`} value={option.id} />
              <span className='flex flex-1 flex-col gap-0.5'>
                <span className='text-sm font-medium'>{option.label}</span>
                <span className='text-muted-foreground text-xs font-normal'>{option.note}</span>
              </span>
              {priced && (
                <span className='text-muted-foreground text-xs font-normal tabular-nums'>
                  ${priced.priceCents / 100}/mo after trial
                </span>
              )}
            </Label>
          );
        })}
      </RadioGroup>
      <p className='text-muted-foreground text-xs leading-relaxed'>You are not charged during the trial and nothing converts automatically.</p>
    </fieldset>
  );

  if (auth.mode === 'dev') {
    return (
      <AuthSurface>
        <PageHeader title={title} description='Local dev harness: identity is simulated on this machine.' />
        {PlanChooser}
        <div className='flex flex-col gap-2'>
          <Button
            variant='action'
            size='control'
            disabled={busy}
            onClick={() => {
              rememberPlan(plan);
              devSignIn();
              router.replace(next);
            }}
          >
            Enter dev workspace
          </Button>
          <Button
            variant='glass'
            size='control'
            disabled={busy}
            onClick={() => {
              rememberPlan(plan);
              devSignIn(true);
              router.replace(next);
            }}
          >
            New dev identity
          </Button>
        </div>
      </AuthSurface>
    );
  }

  return (
    <AuthSurface>
      <PageHeader title={title} description={subtitle} />

      {error && <StateMessage kind='error' layout='inline' title={error} />}

      {PlanChooser}

      {!sent ? (
        <div className='flex flex-col gap-3'>
          {offerPasskey && (
            <Button variant='action' size='control' disabled={busy} onClick={() => void run(passkey)}>
              <Icons.key className='size-4' aria-hidden />
              Sign in with a passkey
            </Button>
          )}
          <Button variant='glass' size='control' disabled={busy} onClick={() => void run(google)}>
            <Icons.logo className='size-4' aria-hidden />
            Continue with Google
          </Button>
          <p className='rafii-eyebrow py-1 text-center'>or use your email</p>
          <form
            className='flex flex-col gap-3'
            onSubmit={(event) => {
              event.preventDefault();
              void run(sendCode);
            }}
          >
            <div className='flex flex-col gap-2'>
              <Label htmlFor='email'>Email address</Label>
              <Input
                id='email'
                type='email'
                autoComplete='email'
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className={rafiiInput}
              />
            </div>
            <Button type='submit' variant={offerPasskey ? 'glass' : 'action'} size='control' disabled={busy || !email.includes('@')}>
              Send one-time code
            </Button>
          </form>
          <Link href={`/auth/reset?next=${encodeURIComponent(next)}`} className={`${linkClass} text-muted-foreground self-start text-sm`}>
            Need help signing in?
          </Link>
        </div>
      ) : (
        <form
          className='flex flex-col gap-4'
          onSubmit={(event) => {
            event.preventDefault();
            void run(verifyCode);
          }}
        >
          <div className='flex flex-col gap-2'>
            <Label htmlFor='code'>Enter the code we sent to {email}</Label>
            <InputOTP id='code' maxLength={8} value={code} onChange={setCode}>
              <InputOTPGroup>
                {Array.from({ length: 8 }).map((_, i) => (
                  <InputOTPSlot key={i} index={i} />
                ))}
              </InputOTPGroup>
            </InputOTP>
          </div>
          <div className='flex flex-wrap gap-2'>
            <Button type='submit' variant='action' size='control' disabled={busy || code.trim().length < 6}>
              Verify and continue
            </Button>
            <Button
              type='button'
              variant='quiet'
              size='control'
              disabled={busy}
              onClick={() => {
                setSent(false);
                setCode('');
              }}
            >
              Change email
            </Button>
          </div>
        </form>
      )}

      <div className='flex flex-col gap-2'>
        <p className='text-muted-foreground text-xs leading-relaxed'>
          By continuing you agree to the{' '}
          <Link href={siteConfig.links.terms} className={linkClass}>
            Terms
          </Link>{' '}
          and{' '}
          <Link href={siteConfig.links.privacy} className={linkClass}>
            Privacy Policy
          </Link>
          .
        </p>
        <p className='text-muted-foreground text-sm'>
          {intent === 'sign-up' ? (
            <>
              Already have an account?{' '}
              <Link href={`${siteConfig.links.signIn}?next=${encodeURIComponent(next)}`} className={linkClass}>
                Sign in
              </Link>
            </>
          ) : (
            <>
              New to PostRiff?{' '}
              <Link href={`${siteConfig.links.signUp}?next=${encodeURIComponent(next)}`} className={linkClass}>
                Start a free trial
              </Link>
            </>
          )}
        </p>
      </div>
    </AuthSurface>
  );
}
