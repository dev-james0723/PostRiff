'use client';

import { Icons } from '@/components/icons';
import { InfoTip, StateMessage, Surface } from '@/components/rafii';
import type { Usage } from '@/lib/api/types';
import { creditMeter } from '@/lib/billing/mode';
import { formatDate, formatNumber } from '@/lib/time';
import { Bar } from './allowances';
import { allowanceTotal, currentTerms } from './billing-model';
import { useBillingCopy } from './use-copy-locale';

/**
 * Managed credits (Pricing v2, `billingMode === 'managed_credits'`): what is left of this period's granted
 * credits, when they reset, what is held for running tasks, and that paid work stops at the limit. A period
 * total that is not on record is said so, never replaced by the plan's advertised number; the plan's monthly
 * credits are named beside it instead. Provider US$ cost lives in its own owner-only panel.
 */
export function CreditMeterCard({ usage, now }: { usage: Usage; now: number }) {
  const copy = useBillingCopy().creditMeter;
  const meter = creditMeter(usage.credits, now);
  const planCredits = allowanceTotal(currentTerms(usage), 'monthlyCredits');
  const count = (value: number) => formatNumber(value);

  return (
    <section className='flex flex-col gap-3' aria-labelledby='credits-heading' data-tour='billing-allowances'>
      <div className='flex items-center gap-1 px-1'>
        <h2 id='credits-heading' className='text-foreground text-lg font-medium tracking-tight'>
          {copy.title}
        </h2>
        <InfoTip label={copy.aboutLabel} description={copy.howItWorks} />
        {meter.kind !== 'unavailable' && meter.resetsAt !== null && <span className='text-muted-foreground ml-auto text-sm'>{copy.resets(formatDate(meter.resetsAt))}</span>}
      </div>
      <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-3'>
        {meter.kind === 'unavailable' ? (
          <StateMessage kind='partial' layout='inline' title={copy.unavailable} description={copy.unavailableHint} />
        ) : (
          <>
            <div className='flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1'>
              <p className='text-foreground text-2xl font-medium tracking-tight tabular-nums'>
                {meter.kind === 'measured' ? copy.left(count(meter.available), count(meter.total)) : copy.available(count(meter.available))}
              </p>
              {meter.held > 0 && <p className='text-muted-foreground text-sm tabular-nums'>{copy.held(count(meter.held))}</p>}
            </div>
            {meter.kind === 'measured' && (
              <Bar fill={meter.fill} warn={meter.warn} index={0} label={copy.barLabel} valueText={copy.barValue(count(meter.available), count(meter.total))} />
            )}
            {meter.kind === 'no_total' && (
              <p className='text-muted-foreground text-sm'>
                {meter.reason === 'above_period_grant' ? copy.aboveGrant : planCredits ? `${copy.totalUnknown} ${copy.planIncludes(count(planCredits))}` : copy.totalUnknown}
              </p>
            )}
            {meter.expiringSoon && meter.resetsAt !== null && <p className='text-foreground text-sm'>{copy.expiring(count(meter.available), formatDate(meter.resetsAt))}</p>}
            {meter.debt > 0 && (
              <p role='alert' className='text-foreground flex items-start gap-1.5 text-sm'>
                <Icons.warning className='mt-0.5 size-3.5 shrink-0' aria-hidden />
                <span>{copy.debt(count(meter.debt))}</span>
              </p>
            )}
            <p className='text-muted-foreground text-xs leading-relaxed'>{copy.noSilentOverage}</p>
          </>
        )}
      </Surface>
    </section>
  );
}
