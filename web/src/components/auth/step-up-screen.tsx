'use client';

import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { clearStepUp, type StepUpRequest } from '@/lib/auth/security-step-up';
import { useAuth } from '@/lib/auth/session';
import { MfaChallenge } from './mfa-challenge';

const WHY = 'Rafii needs to confirm it’s you before it shows this workspace on this browser.';

/**
 * RAPv2 decision 3: the "Confirm it's you" step-up screen. Shown by AppGate when the API refused a workspace read
 * at high risk (a new browser right after a sign-in or two-step change). With a second factor the person confirms
 * here and the workspace loads again; without one they are sent to set one up first (account pages stay open).
 */
export function StepUpScreen({ request }: { request: StepUpRequest }) {
  const auth = useAuth();
  const queries = useQueryClient();

  async function retry() {
    clearStepUp();
    await queries.invalidateQueries();
  }

  if (request.nextAction === 'complete_mfa' && auth.supabase) {
    return (
      <div data-testid='security-step-up' className='relative isolate flex min-h-svh items-center justify-center p-6'>
        <div aria-hidden className='rafii-ambient' />
        <MfaChallenge onVerified={retry} intro={WHY} />
      </div>
    );
  }

  const enroll = request.nextAction === 'enroll_mfa';
  return (
    <div data-testid='security-step-up' className='relative isolate flex min-h-svh items-center justify-center p-6'>
      <div aria-hidden className='rafii-ambient' />
      <StateMessage
        kind='permission'
        media={
          <span aria-hidden className='rafii-glass text-foreground flex size-11 items-center justify-center rounded-full'>
            <Icons.shieldCheck className='size-5' />
          </span>
        }
        title='Confirm it’s you'
        description={
          enroll
            ? `${WHY} Set up an authenticator app or a passkey first, then come back here. Your drafts are safe and nothing was changed.`
            : request.nextAction === 'sign_in'
              ? `${WHY} Sign out and sign in again on this browser.`
              : `${WHY} Use your authenticator app or passkey. If you can’t, sign out and sign in again.`
        }
        action={
          <>
            {enroll && (
              <Link href='/app/account/profile' className={buttonVariants({ variant: 'action', size: 'control' })}>
                Set up two-step sign-in
              </Link>
            )}
            <Button variant='glass' size='control' onClick={() => void retry()}>
              Try again
            </Button>
            <Button variant='quiet' size='control' onClick={() => void auth.signOut()}>
              Sign out
            </Button>
          </>
        }
        className='rafii-glass w-full max-w-md'
      />
    </div>
  );
}
