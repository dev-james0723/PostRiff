'use client';

import { Icons } from '@/components/icons';
import { StatefulButton } from '@/components/motion/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { buttonVariants } from '@/components/ui/button';
import type { Usage } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { alertCopy } from './billing-copy';
import { lifecycleAlert } from './billing-model';
import { PORTAL, type BillingRedirect } from './use-billing-redirect';

/** Only what `lifecycle` and the subscription row prove; nothing renders when all is well. */
export function LifecycleAlert({ usage, isOwner, redirect, now }: { usage: Usage; isOwner: boolean; redirect: BillingRedirect; now: number }) {
  const alert = lifecycleAlert(usage, now);
  if (!alert) return null;
  const copy = alertCopy(alert);
  const destructive = alert.kind === 'payment_failed';
  const portal = isOwner && usage.billing?.portalAvailable === true;
  const choosePlan = isOwner && (alert.kind === 'ended' || alert.kind === 'trial_ended');

  return (
    <Alert variant={destructive ? 'destructive' : 'default'} className='flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between'>
      <div className='flex min-w-0 gap-2'>
        {destructive ? <Icons.warning className='mt-0.5 size-4 shrink-0' /> : <Icons.info className='mt-0.5 size-4 shrink-0' />}
        <div className='flex min-w-0 flex-col gap-0.5'>
          <AlertTitle>{copy.title}</AlertTitle>
          <AlertDescription>{copy.description}</AlertDescription>
        </div>
      </div>
      {choosePlan ? (
        <a href='#plans' className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'shrink-0')}>
          Choose a plan
        </a>
      ) : portal && (alert.kind === 'payment_failed' || alert.kind === 'ending') ? (
        <StatefulButton
          variant='outline'
          size='sm'
          className='shrink-0'
          state={redirect.stateFor(PORTAL)}
          disabled={redirect.busy}
          loadingText='Opening portal…'
          errorText='Try again'
          onClick={redirect.openPortal}
        >
          Open billing portal
        </StatefulButton>
      ) : null}
    </Alert>
  );
}
