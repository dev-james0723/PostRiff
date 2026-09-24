'use client';

import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StatefulButton } from '@/components/motion/button';
import { Surface } from '@/components/rafii';
import { cents } from '@/lib/api/client';
import type { Usage } from '@/lib/api/types';
import { lifecycleLabel, timelineText } from './billing-copy';
import { isTrial, lifecycleTone, planTimeline } from './billing-model';
import { ACTION_STATEFUL } from './lifecycle-alert';
import { PORTAL, type BillingRedirect } from './use-billing-redirect';

function exportText(available: boolean | undefined) {
  if (available === undefined) return 'Export status unavailable';
  return available ? 'Drafts stay exportable' : 'Export not available';
}

/** Which plan, what it costs, and the next date that changes something: the page's contextual glass surface (DNA §21.18). */
export function PlanCard({ usage, isOwner, redirect, now }: { usage: Usage; isOwner: boolean; redirect: BillingRedirect; now: number }) {
  const sub = usage.subscription;
  const status = usage.lifecycle?.status;
  const trial = isTrial(usage);
  const billing = usage.billing;
  const portalError = redirect.errorFor(PORTAL);

  return (
    <Surface material='glass' radius='card' padding='md' className='flex flex-col gap-4 lg:col-span-1' data-tour='billing-plan'>
      <div className='flex flex-col gap-2'>
        <span className='rafii-eyebrow'>Current plan</span>
        <h2 className='flex flex-wrap items-center gap-2 text-2xl font-medium tracking-tight'>
          <span className='text-foreground'>{sub?.label ?? 'Plan unavailable'}</span>
          <AnimatedBadge status={lifecycleTone(status)} size='sm' contentKey={status ?? 'unknown'}>
            {lifecycleLabel(status)}
          </AnimatedBadge>
        </h2>
      </div>
      <div className='text-muted-foreground flex flex-col gap-1 text-sm'>
        {!sub ? (
          <span>Price unavailable</span>
        ) : trial ? (
          <span>{cents(sub.priceCents, sub.currency)} · no card on file · nothing converts automatically</span>
        ) : (
          <span>
            {cents(sub.priceCents, sub.currency)} / month
            {sub.priceStatus !== 'active' && ' · proposed price'}
          </span>
        )}
        <span className='text-foreground'>{timelineText(planTimeline(usage, now))}</span>
        <span>{exportText(usage.lifecycle?.exportAvailable)}</span>
      </div>
      <div className='mt-auto flex flex-col items-start gap-2 pt-1'>
        {!isOwner ? (
          <span className='text-muted-foreground text-xs'>Plan changes are made by the workspace owner.</span>
        ) : !billing ? (
          <span className='text-muted-foreground text-xs'>Billing details are unavailable right now.</span>
        ) : billing.portalAvailable ? (
          <>
            <StatefulButton
              data-tour='billing-manage'
              className={ACTION_STATEFUL}
              state={redirect.stateFor(PORTAL)}
              disabled={redirect.busy}
              loadingText='Opening portal…'
              errorText='Try again'
              onClick={redirect.openPortal}
            >
              Manage billing
            </StatefulButton>
            {portalError && (
              <p role='alert' className='text-destructive text-xs'>
                {portalError}
              </p>
            )}
          </>
        ) : billing.provider === 'disabled' ? (
          <span className='text-muted-foreground text-xs'>Billing is not enabled on this deployment yet.</span>
        ) : (
          <span className='text-muted-foreground text-xs'>Payment method, invoices and cancellation appear here after your first subscription.</span>
        )}
      </div>
    </Surface>
  );
}
