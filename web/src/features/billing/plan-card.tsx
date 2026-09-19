'use client';

import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StatefulButton } from '@/components/motion/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { cents } from '@/lib/api/client';
import type { Usage } from '@/lib/api/types';
import { lifecycleLabel, timelineText } from './billing-copy';
import { isTrial, lifecycleTone, planTimeline } from './billing-model';
import { PORTAL, type BillingRedirect } from './use-billing-redirect';

function exportText(available: boolean | undefined) {
  if (available === undefined) return 'Export status unavailable';
  return available ? 'Drafts stay exportable' : 'Export not available';
}

/** Which plan, what it costs, and the next date that changes something. */
export function PlanCard({ usage, isOwner, redirect, now }: { usage: Usage; isOwner: boolean; redirect: BillingRedirect; now: number }) {
  const sub = usage.subscription;
  const status = usage.lifecycle?.status;
  const trial = isTrial(usage);
  const billing = usage.billing;
  const portalError = redirect.errorFor(PORTAL);

  return (
    <Card className='lg:col-span-1' data-tour='billing-plan'>
      <CardHeader>
        <CardDescription>Current plan</CardDescription>
        <CardTitle className='flex flex-wrap items-center gap-2 text-2xl'>
          <span>{sub?.label ?? 'Plan unavailable'}</span>
          <AnimatedBadge status={lifecycleTone(status)} size='sm' contentKey={status ?? 'unknown'}>
            {lifecycleLabel(status)}
          </AnimatedBadge>
        </CardTitle>
      </CardHeader>
      <CardContent className='text-muted-foreground flex flex-col gap-1 text-sm'>
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
      </CardContent>
      <CardFooter className='flex flex-col items-start gap-2'>
        {!isOwner ? (
          <span className='text-muted-foreground text-xs'>Plan changes are made by the workspace owner.</span>
        ) : !billing ? (
          <span className='text-muted-foreground text-xs'>Billing details are unavailable right now.</span>
        ) : billing.portalAvailable ? (
          <>
            <StatefulButton
              data-tour='billing-manage'
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
      </CardFooter>
    </Card>
  );
}
