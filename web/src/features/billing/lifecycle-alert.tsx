'use client';

import { StatefulButton } from '@/components/motion/button';
import { StateMessage } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import type { Usage } from '@/lib/api/types';
import { alertCopy } from './billing-copy';
import { lifecycleAlert } from './billing-model';
import { PORTAL, type BillingRedirect } from './use-billing-redirect';

/** The glass recipe on a secondary motion button (DNA §10.2). */
export const GLASS_STATEFUL =
  'rafii-glass hover:rafii-glass-selected h-12 rounded-[var(--rafii-radius-control)] border-0 bg-transparent px-4 text-sm hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent';
/** The inverted primary on a motion button (DNA §10.1). */
export const ACTION_STATEFUL = 'rafii-action h-12 rounded-[var(--rafii-radius-control)] px-4 text-sm hover:brightness-[1.06]';

/** Only what `lifecycle` and the subscription row prove; nothing renders when all is well (DNA §20.1, §20.4). */
export function LifecycleAlert({ usage, isOwner, redirect, now }: { usage: Usage; isOwner: boolean; redirect: BillingRedirect; now: number }) {
  const alert = lifecycleAlert(usage, now);
  if (!alert) return null;
  const copy = alertCopy(alert);
  const failed = alert.kind === 'payment_failed';
  const portal = isOwner && usage.billing?.portalAvailable === true;
  const choosePlan = isOwner && (alert.kind === 'ended' || alert.kind === 'trial_ended');

  return (
    <StateMessage
      kind={failed ? 'error' : 'partial'}
      layout='inline'
      title={copy.title}
      description={copy.description}
      className='rafii-quiet rounded-[var(--rafii-radius-card)] px-5 py-4'
      action={
        choosePlan ? (
          <a href='#plans' className={buttonVariants({ variant: 'glass', size: 'sm' }) + ' min-h-10 px-3.5'}>
            Choose a plan
          </a>
        ) : portal && (alert.kind === 'payment_failed' || alert.kind === 'ending') ? (
          <StatefulButton
            variant='outline'
            size='sm'
            className={GLASS_STATEFUL + ' h-10'}
            state={redirect.stateFor(PORTAL)}
            disabled={redirect.busy}
            loadingText='Opening portal…'
            errorText='Try again'
            onClick={redirect.openPortal}
          >
            Open billing portal
          </StatefulButton>
        ) : undefined
      }
    />
  );
}
