'use client';

import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StatefulButton } from '@/components/motion/button';
import { Surface } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { cents } from '@/lib/api/client';
import type { Usage } from '@/lib/api/types';
import { billingModeOf, isLegacyPlanUnderV2, planListKind, v2PlanCardModels } from '@/lib/billing/mode';
import { formatDate } from '@/lib/time';
import { cn } from '@/lib/utils';
import { planSummary, type PlanSummary } from './billing-copy';
import { currentTerms, isTrial, lifecycleTone, planTimeline } from './billing-model';
import { ACTION_STATEFUL } from './lifecycle-alert';
import { useBillingCopy } from './use-copy-locale';
import { PORTAL, type BillingRedirect } from './use-billing-redirect';

/**
 * The plan in one glance: its name, the one thing that changes next, and one action when there is
 * one (UI simplification spec §9). Price and exact dates sit behind Details for a trial; a paid
 * plan shows its price, because money stays visible. Payment trouble is announced, not tucked away.
 *
 * Pricing v2: Free reads "Free" (never "Plan unavailable"), a Creator subscriber sees the price of their own
 * variant, and a Studio / Studio Assist package kept after v2 launched is labelled as a legacy plan.
 */
export function PlanCard({ usage, isOwner, redirect, now }: { usage: Usage; isOwner: boolean; redirect: BillingRedirect; now: number }) {
  const v2Copy = useBillingCopy().summary;
  const sub = usage.subscription;
  const status = usage.lifecycle?.status;
  const mode = billingModeOf(usage);
  const trial = mode !== 'free_preview' && isTrial(usage);
  const legacyPlan = isLegacyPlanUnderV2(usage);
  // "Choose a plan" only when the plan list below really offers a checkout (no anchor to a list without one).
  const canChoose = planListKind(usage) === 'v2' ? v2PlanCardModels(usage, isOwner).some((card) => card.offer === 'checkout') : usage.billing?.checkoutAvailable === true;

  let summary: PlanSummary;
  if (mode === 'free_preview') {
    const ended = sub && (status === 'cancelled' || status === 'expired') && sub.currentPeriodEnd ? v2Copy.ended(sub.label, formatDate(sub.currentPeriodEnd)) : null;
    summary = {
      title: v2Copy.freeTitle,
      badge: null,
      line: ended ?? v2Copy.freeLine,
      exactDate: null,
      action: canChoose && isOwner ? 'plans' : null,
      actionLabel: canChoose && isOwner ? v2Copy.seeCreator : null,
      urgent: false
    };
  } else {
    summary = planSummary({
      timeline: planTimeline(usage, now),
      planLabel: sub?.label ?? currentTerms(usage)?.label,
      trial,
      status,
      isOwner,
      portalAvailable: usage.billing?.portalAvailable === true,
      checkoutAvailable: canChoose
    });
  }
  const portalError = redirect.errorFor(PORTAL);
  const price =
    mode === 'free_preview' || !sub ? null : `${cents(sub.priceCents, sub.currency)}${trial ? '' : ' / month'}${!trial && sub.priceStatus !== 'active' ? ' · proposed price' : ''}`;

  return (
    <Surface
      material='glass'
      radius='card'
      padding='md'
      className='flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6'
      data-tour='billing-plan'
      aria-labelledby='plan-heading'
      role='region'
    >
      <div className='flex min-w-0 flex-col gap-1'>
        <h2 id='plan-heading' className='flex flex-wrap items-center gap-2 text-2xl font-medium tracking-tight md:text-3xl'>
          <span className='text-foreground'>{summary.title}</span>
          {summary.badge && (
            <AnimatedBadge status={lifecycleTone(status)} size='sm' contentKey={summary.badge}>
              {summary.badge}
            </AnimatedBadge>
          )}
          {legacyPlan && <Badge variant='secondary'>{v2Copy.legacyBadge}</Badge>}
        </h2>
        {summary.line && (
          <p role={summary.urgent ? 'alert' : undefined} className={cn('text-base', summary.urgent ? 'text-foreground font-medium' : 'text-foreground/90')}>
            {summary.line}
          </p>
        )}
        {!trial && price && <p className='text-muted-foreground text-sm tabular-nums'>{price}</p>}
        {legacyPlan && <p className='text-muted-foreground text-sm'>{v2Copy.legacyNote}</p>}
        {trial && (price || summary.exactDate) && (
          <details className='group text-muted-foreground mt-1 text-sm'>
            <summary className='rafii-focus hover:text-foreground w-fit cursor-pointer list-none rounded-md underline-offset-4 hover:underline [&::-webkit-details-marker]:hidden'>
              Details
            </summary>
            <p className='mt-1 tabular-nums'>{[price, summary.exactDate].filter(Boolean).join(' · ')}</p>
          </details>
        )}
      </div>

      {summary.action && (
        <div className='flex shrink-0 flex-col items-start gap-2 sm:items-end'>
          {summary.action === 'portal' ? (
            <StatefulButton
              data-tour='billing-manage'
              className={ACTION_STATEFUL}
              state={redirect.stateFor(PORTAL)}
              disabled={redirect.busy}
              loadingText='Opening…'
              errorText='Try again'
              onClick={redirect.openPortal}
            >
              {summary.actionLabel}
            </StatefulButton>
          ) : (
            <a href='#plans' className={cn(buttonVariants({ variant: 'action', size: 'control' }))}>
              {summary.actionLabel}
            </a>
          )}
          {portalError && (
            <p role='alert' className='text-destructive text-xs'>
              {portalError}
            </p>
          )}
        </div>
      )}
    </Surface>
  );
}
