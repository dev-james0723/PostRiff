'use client';

import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StatefulButton } from '@/components/motion/button';
import { Surface } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { SuccessCheck } from '@/components/ui/success-check';
import { catalogPlan } from '@/config/plans';
import { cents } from '@/lib/api/client';
import type { PlanTerms, Usage } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { formatNumber } from '@/lib/time';
import { CONFIRM, PLAN_ALLOWANCES, PRICE_STATUS, checkoutNote } from './billing-copy';
import { allowanceTotal, humanize, latestTermsPerPlan, planOffer, type PlanOffer } from './billing-model';
import { planListKind, v2PlanCardModels } from './billing-mode';
import { ACTION_STATEFUL } from './lifecycle-alert';
import { useBillingCopy } from './use-copy-locale';
import type { BillingRedirect } from './use-billing-redirect';
import type { ConfirmPhase } from './use-checkout-return';

function allowanceValue(terms: PlanTerms, key: string, unit?: string) {
  const total = allowanceTotal(terms, key);
  if (total === null) return '—';
  if (total === 0) return 'Not included';
  return unit ? `${total.toLocaleString()} ${unit}` : total.toLocaleString();
}

/**
 * What a plan card says when it has no Choose button. "Current" is already a badge and an
 * unavailable plan needs no apology, so those say nothing; the section says "owner only" once.
 */
const OFFER_TEXT: Partial<Record<PlanOffer, string>> = {
  switch_in_portal: 'Switch in Manage plan'
};

/**
 * The return from checkout, shown at the top of the page while it is still news: a real poll
 * of `/usage` (loading), the provider's confirmation (success), or an honest timeout (warning).
 */
export function CheckoutConfirmation({ phase }: { phase: ConfirmPhase }) {
  const reduce = useReducedMotion();
  const view =
    phase === 'confirming'
      ? { status: 'loading' as const, title: CONFIRM.loading, hint: null }
      : phase === 'confirmed'
        ? { status: 'success' as const, title: CONFIRM.success, hint: null }
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
            className='rafii-glass flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-4 text-sm sm:flex-row sm:items-center'
          >
            <AnimatedBadge status={view.status} contentKey={view.status} className='self-start sm:self-auto'>
              {view.title}
            </AnimatedBadge>
            {phase === 'confirmed' && <SuccessCheck className='text-foreground size-4' />}
            {view.hint && <span className='text-muted-foreground text-xs'>{view.hint}</span>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/**
 * Pricing v2's plan list: Free and Creator only (plans for new sale), each at this workspace's own price.
 * Creator's Choose button appears only when its checkout can work; before that the card says checkout is not
 * open yet. Free is never bought, and a held subscription (including a legacy package) changes in the portal.
 */
function V2Plans({ usage, isOwner, redirect }: { usage: Usage; isOwner: boolean; redirect: BillingRedirect }) {
  const copy = useBillingCopy().plans;
  const cards = v2PlanCardModels(usage, isOwner);
  if (cards.length === 0) return null;
  const note = isOwner && cards.some((card) => card.offer === 'checkout') ? checkoutNote(usage.billing?.provider) : null;
  const firstValue = catalogPlan('free')?.firstValue;

  return (
    <section id='plans' className='flex scroll-mt-4 flex-col gap-3' aria-labelledby='plans-heading' data-tour='billing-plans'>
      <div className='flex flex-col gap-0.5 px-1'>
        <h2 id='plans-heading' className='text-foreground text-lg font-medium tracking-tight'>
          Plans
        </h2>
        {!isOwner && <p className='text-muted-foreground text-sm'>Only the owner can change plans.</p>}
        {note && <p className='text-muted-foreground text-sm'>{note}</p>}
      </div>
      <div className='grid gap-4 md:grid-cols-2'>
        {cards.map(({ terms, current, priceCents, currency, offer }) => {
          const credits = allowanceTotal(terms, 'monthlyCredits');
          const free = terms.plan === 'free';
          const rows = [
            ...(free && firstValue ? [{ label: copy.firstLook, value: copy.firstLookValue(formatNumber(firstValue.genomeMaxPosts)) }] : []),
            { label: copy.managedCredits, value: credits ? formatNumber(credits) : copy.none },
            { label: copy.connectedAccounts, value: allowanceValue(terms, 'connectedAccounts') },
            { label: copy.brands, value: allowanceValue(terms, 'brands') },
            { label: copy.seats, value: allowanceValue(terms, 'members') }
          ];
          const error = redirect.errorFor(terms.id);
          return (
            <Surface key={terms.id} material={current ? 'selected' : 'quiet'} radius='card' padding='md' className='flex flex-col gap-4' role='group' aria-labelledby={`plan-${terms.id}-name`}>
              <div className='flex flex-col gap-2'>
                {current && (
                  <div className='flex flex-wrap items-center gap-2'>
                    <Badge>Current</Badge>
                  </div>
                )}
                <h3 id={`plan-${terms.id}-name`} className='flex flex-wrap items-baseline gap-x-2 text-xl font-medium tracking-tight'>
                  <span className='text-foreground'>{terms.label}</span>
                  {priceCents !== null && (
                    <span className='text-muted-foreground text-base font-normal tabular-nums'>
                      {cents(priceCents, currency)}
                      {free ? '' : ` ${copy.perMonth}`}
                    </span>
                  )}
                </h3>
                {priceCents === null && !isOwner && <p className='text-muted-foreground text-xs'>{copy.ownerSeesPrice}</p>}
              </div>
              <dl className='grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm'>
                {rows.map((row) => (
                  <div key={row.label} className='contents'>
                    <dt className='text-muted-foreground'>{row.label}</dt>
                    <dd className='text-foreground text-right tabular-nums'>{row.value}</dd>
                  </div>
                ))}
              </dl>
              {!free && <p className='text-muted-foreground text-xs'>{copy.noSilentOverage}</p>}
              {(offer === 'checkout' || offer === 'not_open') && (
                <div className='mt-auto flex flex-col items-start gap-2 pt-1'>
                  {offer === 'checkout' ? (
                    <>
                      <StatefulButton
                        className={ACTION_STATEFUL}
                        state={redirect.stateFor(terms.id)}
                        disabled={redirect.busy}
                        loadingText='Opening checkout…'
                        errorText='Try again'
                        onClick={() => redirect.startCheckout(terms.id)}
                      >
                        {copy.choose(terms.label)}
                      </StatefulButton>
                      {error && (
                        <p role='alert' className='text-destructive text-xs'>
                          {error}
                        </p>
                      )}
                    </>
                  ) : (
                    <span className='text-muted-foreground text-xs'>{copy.notOpen}</span>
                  )}
                </div>
              )}
            </Surface>
          );
        })}
      </div>
    </section>
  );
}

export function Plans({ usage, isOwner, redirect }: { usage: Usage; isOwner: boolean; redirect: BillingRedirect }) {
  if (planListKind(usage) === 'v2') return <V2Plans usage={usage} isOwner={isOwner} redirect={redirect} />;
  const currentId = usage.entitlement.planTermsId;
  const plans = latestTermsPerPlan(usage.planTerms, currentId);
  // A plan list with nothing to buy yet is still worth seeing (what comes after the trial), but an
  // empty one is not: the section is left out rather than explained.
  if (plans.length === 0) return null;
  const note = usage.billing?.checkoutAvailable && isOwner ? checkoutNote(usage.billing.provider) : null;

  return (
    <section id='plans' className='flex scroll-mt-4 flex-col gap-3' aria-labelledby='plans-heading' data-tour='billing-plans'>
      <div className='flex flex-col gap-0.5 px-1'>
        <h2 id='plans-heading' className='text-foreground text-lg font-medium tracking-tight'>
          Plans
        </h2>
        {!isOwner && <p className='text-muted-foreground text-sm'>Only the owner can change plans.</p>}
        {note && <p className='text-muted-foreground text-sm'>{note}</p>}
      </div>
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
            <Surface key={terms.id} material={current ? 'selected' : 'quiet'} radius='card' padding='md' className='flex flex-col gap-4'>
              <div className='flex flex-col gap-2'>
                {(current || terms.status !== 'active') && (
                  <div className='flex flex-wrap items-center gap-2'>
                    {current && <Badge>Current</Badge>}
                    {terms.status !== 'active' && <Badge variant='secondary'>{PRICE_STATUS[terms.status] ?? humanize(terms.status)}</Badge>}
                  </div>
                )}
                <h3 className='flex flex-wrap items-baseline gap-x-2 text-xl font-medium tracking-tight'>
                  <span className='text-foreground'>{terms.label}</span>
                  <span className='text-muted-foreground text-base font-normal'>{cents(terms.priceCents, terms.currency)} / month</span>
                </h3>
              </div>
              <dl className='grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm'>
                {PLAN_ALLOWANCES.map((item) => (
                  <div key={item.key} className='contents'>
                    <dt className='text-muted-foreground'>{item.label}</dt>
                    <dd className='text-foreground text-right tabular-nums'>{allowanceValue(terms, item.key, item.unit)}</dd>
                  </div>
                ))}
              </dl>
              {(offer === 'checkout' || OFFER_TEXT[offer]) && (
                <div className='mt-auto flex flex-col items-start gap-2 pt-1'>
                  {offer === 'checkout' ? (
                    <>
                      <StatefulButton
                        className={ACTION_STATEFUL}
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
                </div>
              )}
            </Surface>
          );
        })}
      </div>
    </section>
  );
}
