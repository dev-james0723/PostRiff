'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Skeleton } from '@/components/ui/skeleton';
import { plans } from '@/config/plans';
import { siteConfig } from '@/config/site';
import { devSignIn, useAuth } from '@/lib/auth/session';
import { rememberPlan, selectedPlan, type TrialPlan } from '@/lib/workspace/provider';

const TRIAL_PLANS: { id: TrialPlan; label: string; note: string }[] = [
  { id: 'studio', label: 'Studio', note: 'Manual drafting and scheduling' },
  { id: 'assist', label: 'Studio Assist', note: 'Adds AI writing batches' }
];

function safeNext(value: string | null) {
  return value && value.startsWith('/') && !value.startsWith('//') ? value : '/app';
}

export function AuthForm({ intent }: { intent: 'sign-in' | 'sign-up' }) {
  const auth = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get('next'));
  const callbackError = params.get('error');

  const [plan, setPlan] = useState<TrialPlan>('studio');
  const [email, setEmail] = useState('');
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

  async function sendCode() {
    rememberPlan(plan);
    const { createClient } = await import('@/lib/supabase/client');
    const { error: otpError } = await createClient().auth.signInWithOtp({
      email: email.trim(),
      options: { shouldCreateUser: true }
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
    router.replace(next);
  }

  const title = intent === 'sign-up' ? 'Create your PostRiff workspace' : 'Sign in to PostRiff';
  const subtitle =
    intent === 'sign-up'
      ? '14-day trial. No card. Export everything, any time.'
      : 'Welcome back. Your drafts are where you left them.';

  if (auth.status === 'loading') {
    return (
      <div className='flex flex-col gap-3' role='status' aria-label='Loading'>
        <Skeleton className='h-7 w-2/3' />
        <Skeleton className='h-4 w-1/2' />
        <Skeleton className='mt-4 h-10 w-full' />
        <Skeleton className='h-10 w-full' />
      </div>
    );
  }

  if (auth.status === 'unavailable') {
    return (
      <Alert>
        <Icons.alertCircle className='size-4' />
        <AlertDescription>{auth.error ?? 'Sign-in is unavailable right now.'}</AlertDescription>
      </Alert>
    );
  }

  const PlanChooser = intent === 'sign-up' && (
    <fieldset className='flex flex-col gap-2'>
      <legend className='text-sm font-medium'>Trial plan</legend>
      <RadioGroup value={plan} onValueChange={(value) => setPlan(value === 'assist' ? 'assist' : 'studio')}>
        {TRIAL_PLANS.map((option) => {
          const priced = plans.find((p) => p.id === option.id);
          return (
            <Label
              key={option.id}
              htmlFor={`plan-${option.id}`}
              className='hover:bg-accent flex cursor-pointer items-center gap-3 rounded-lg border p-3 has-data-checked:border-primary'
            >
              <RadioGroupItem id={`plan-${option.id}`} value={option.id} />
              <span className='flex flex-1 flex-col'>
                <span className='text-sm font-medium'>{option.label}</span>
                <span className='text-muted-foreground text-xs'>{option.note}</span>
              </span>
              {priced && (
                <span className='text-muted-foreground text-xs'>
                  ${priced.priceCents / 100}/mo after trial
                </span>
              )}
            </Label>
          );
        })}
      </RadioGroup>
      <p className='text-muted-foreground text-xs'>You are not charged during the trial and nothing converts automatically.</p>
    </fieldset>
  );

  if (auth.mode === 'dev') {
    return (
      <div className='flex flex-col gap-6'>
        <header className='flex flex-col gap-1'>
          <h1 className='text-2xl font-semibold tracking-tight'>{title}</h1>
          <p className='text-muted-foreground text-sm'>Local dev harness: identity is simulated on this machine.</p>
        </header>
        {PlanChooser}
        <div className='flex flex-col gap-2'>
          <Button
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
            variant='outline'
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
      </div>
    );
  }

  return (
    <div className='flex flex-col gap-6'>
      <header className='flex flex-col gap-1'>
        <h1 className='text-2xl font-semibold tracking-tight'>{title}</h1>
        <p className='text-muted-foreground text-sm'>{subtitle}</p>
      </header>

      {error && (
        <Alert variant='destructive'>
          <Icons.alertCircle className='size-4' />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {PlanChooser}

      {!sent ? (
        <div className='flex flex-col gap-3'>
          <Button variant='outline' disabled={busy} onClick={() => void run(google)}>
            <Icons.logo className='size-4' aria-hidden />
            Continue with Google
          </Button>
          <div className='text-muted-foreground flex items-center gap-3 text-xs'>
            <span className='bg-border h-px flex-1' />
            or use your email
            <span className='bg-border h-px flex-1' />
          </div>
          <form
            className='flex flex-col gap-3'
            onSubmit={(event) => {
              event.preventDefault();
              void run(sendCode);
            }}
          >
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='email'>Email address</Label>
              <Input
                id='email'
                type='email'
                autoComplete='email'
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <Button type='submit' disabled={busy || !email.includes('@')}>
              Send one-time code
            </Button>
          </form>
        </div>
      ) : (
        <form
          className='flex flex-col gap-4'
          onSubmit={(event) => {
            event.preventDefault();
            void run(verifyCode);
          }}
        >
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='code'>Enter the code we sent to {email}</Label>
            <InputOTP id='code' maxLength={8} value={code} onChange={setCode}>
              <InputOTPGroup>
                {Array.from({ length: 8 }).map((_, i) => (
                  <InputOTPSlot key={i} index={i} />
                ))}
              </InputOTPGroup>
            </InputOTP>
          </div>
          <div className='flex gap-2'>
            <Button type='submit' disabled={busy || code.trim().length < 6}>
              Verify and continue
            </Button>
            <Button
              type='button'
              variant='ghost'
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

      <p className='text-muted-foreground text-xs'>
        By continuing you agree to the{' '}
        <Link href={siteConfig.links.terms} className='underline'>
          Terms
        </Link>{' '}
        and{' '}
        <Link href={siteConfig.links.privacy} className='underline'>
          Privacy Policy
        </Link>
        .
      </p>
      <p className='text-muted-foreground text-sm'>
        {intent === 'sign-up' ? (
          <>
            Already have an account?{' '}
            <Link href={`${siteConfig.links.signIn}?next=${encodeURIComponent(next)}`} className='underline'>
              Sign in
            </Link>
          </>
        ) : (
          <>
            New to PostRiff?{' '}
            <Link href={`${siteConfig.links.signUp}?next=${encodeURIComponent(next)}`} className='underline'>
              Start a free trial
            </Link>
          </>
        )}
      </p>
    </div>
  );
}
