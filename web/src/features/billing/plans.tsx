'use client';

import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StatefulButton } from '@/components/motion/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { SuccessCheck } from '@/components/ui/success-check';
import { cents } from '@/lib/api/client';
import type { PlanTerms, Usage } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { cn } from '@/lib/utils';
import { CONFIRM, PLAN_ALLOWANCES, PRICE_STATUS, providerNote } from './billing-copy';
import { allowanceTotal, humanize, latestTermsPerPlan, planOffer, type PlanOffer } from './billing-model';
import type { BillingRedirect } from './use-billing-redirect';
import type { ConfirmPhase } from './use-checkout-return';

function allowanceValue(terms: PlanTerms, key: string, unit?: string) {
  const total = allowanceTotal(terms, key);
  if (total === null) return '—';
  if (total === 0) return 'Not included';
  return unit ? `${total.toLocaleString()} ${unit}` : total.toLocaleString();
}

const OFFER_TEXT: Record<Exclude<PlanOffer, 'checkout'>, string> = {
  current: 'This is your current plan.',
  owner_only: 'Ask the workspace owner to change the plan.',
  switch_in_portal: 'Switch plans from the billing portal.',
  not_available: 'Not yet available for purchase.'
};

/**
 * The return from checkout, shown at the top of the page while it is still news: a real poll
 * of `/usage` (loading), the provider's confirmation (success), or an honest timeout (warning).
 */
export function CheckoutConfirmation({ phase }: { phase: ConfirmPhase }) {
  const reduce = useReducedMotion();
  const view =
    phase === 'confirming'
      ? { status: 'loading' as const, title: CONFIRM.loading, hint: CONFIRM.loadingHint }
      : phase === 'confirmed'
        ? { status: 'success' as const, title: CONFIRM.success, hint: CONFIRM.successHint }
        : phase === 'timeout'
          ? { status: 'warning' as const, title: CONFIRM.timeout, hint: CONFIRM.timeoutHint }
          : null;
  return (
    <div aria-live='polite'>
      <AnimatePresence initial={false}>
        {view && (
          <motion.div
            key='checkout-confirmation'
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0, transition: { duration: reduce ? 0 : 0.25, ease: EASE_OUT } }}
            exit={{ opacity: 0, transition: { duration: reduce ? 0 : 0.15, ease: EASE_OUT } }}
            className='bg-card flex flex-col gap-2 rounded-lg border p-3 text-sm sm:flex-row sm:items-center'
          >
            <AnimatedBadge status={view.status} contentKey={view.status} className='self-start sm:self-auto'>
              {view.title}
            </AnimatedBadge>
            {phase === 'confirmed' && <SuccessCheck className='size-4 text-emerald-600 dark:text-emerald-400' />}
            <span className='text-muted-foreground text-xs'>{view.hint}</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function Plans({ usage, isOwner, redirect }: { usage: Usage; isOwner: boolean; redirect: BillingRedirect }) {
  const currentId = usage.entitlement.planTermsId;
  const plans = latestTermsPerPlan(usage.planTerms, currentId);
  const note = providerNote(usage.billing?.provider);

  return (
    <section id='plans' className='flex scroll-mt-4 flex-col gap-3' aria-labelledby='plans-heading' data-tour='billing-plans'>
      <div>
        <h3 id='plans-heading' className='text-lg font-semibold'>
          Plans
        </h3>
        {note && <p className='text-muted-foreground text-sm'>{note}</p>}
      </div>
      {plans.length === 0 ? (
        <p className='text-muted-foreground rounded-lg border p-4 text-sm'>No plans are published on this deployment yet.</p>
      ) : (
        <div className='grid gap-4 md:grid-cols-2'>
          {plans.map((terms) => {
            const offer = planOffer({
              terms,
              currentTermsId: currentId,
              lifecycleStatus: usage.lifecycle?.status,
              checkoutAvailable: usage.billing?.checkoutAvailable,
              isOwner
            });
            const current = terms.id === currentId;
            const error = redirect.errorFor(terms.id);
            return (
              <Card key={terms.id} className={cn(current && 'ring-primary ring-2')}>
                <CardHeader>
                  {(current || terms.status !== 'active') && (
                    <CardDescription className='flex flex-wrap items-center gap-2'>
                      {current && <Badge>Current</Badge>}
                      {terms.status !== 'active' && <Badge variant='outline'>{PRICE_STATUS[terms.status] ?? humanize(terms.status)}</Badge>}
                    </CardDescription>
                  )}
                  <CardTitle className='flex flex-wrap items-baseline gap-x-2 text-2xl'>
                    <span>{terms.label}</span>
                    <span className='text-muted-foreground text-base font-normal'>{cents(terms.priceCents, terms.currency)} / month</span>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <dl className='grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm'>
                    {PLAN_ALLOWANCES.map((item) => (
                      <div key={item.key} className='contents'>
                        <dt className='text-muted-foreground'>{item.label}</dt>
                        <dd className='text-right tabular-nums'>{allowanceValue(terms, item.key, item.unit)}</dd>
                      </div>
                    ))}
                  </dl>
                </CardContent>
                <CardFooter className='mt-auto flex flex-col items-start gap-2'>
                  {offer === 'checkout' ? (
                    <>
                      <StatefulButton
                        state={redirect.stateFor(terms.id)}
                        disabled={redirect.busy}
                        loadingText='Opening checkout…'
                        errorText='Try again'
                        onClick={() => redirect.startCheckout(terms.id)}
                      >
                        {`Choose ${terms.label}`}
                      </StatefulButton>
                      {error && (
                        <p role='alert' className='text-destructive text-xs'>
                          {error}
                        </p>
                      )}
                    </>
                  ) : (
                    <span className='text-muted-foreground text-xs'>{OFFER_TEXT[offer]}</span>
                  )}
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}
    </section>
  );
}
