'use client';

/**
 * Which accepted next-week decisions this week's plan applied (and to how many posts), and which it could not apply,
 * with the reason in words (PRD R-PROOF-02). Each decision is shown by its wording (from the strategy list or what is
 * in effect), never by its id. A decision revoked after planning is marked so: drafts written from now on no longer
 * use it. Shown only when the plan recorded decisions; hidden when proof v2 is off. English and Traditional Chinese
 * follow the person's language preference (D-022).
 */
import { Button } from '@/components/ui/button';
import { usePreferences } from '@/lib/preferences';
import { isFeatureDisabled } from '@/lib/growth-v2/request';
import { useStrategy } from '@/lib/growth-v2/proof-hooks';
import { appliedSummary, proofCopy, proofLocale } from '@/lib/growth-v2/proof-present';
import type { AppliedDecision, NotAppliedDecision } from '@/lib/growth-v2/proof-types';
import type { Week } from '@/lib/coworker/types';

type PlannedWeek = Week & { appliedDecisions?: AppliedDecision[]; notApplied?: NotAppliedDecision[] };

export function AppliedDecisions({ week }: { week: Week }) {
  const planned = week as PlannedWeek;
  const recorded = Boolean(planned.appliedDecisions?.length || planned.notApplied?.length);
  const strategy = useStrategy(recorded);
  const { locale } = usePreferences();
  const lang = proofLocale(locale);
  const copy = proofCopy(locale);
  if (!recorded || (strategy.isError && isFeatureDisabled(strategy.error))) return null;
  const summary = appliedSummary(planned.appliedDecisions, planned.notApplied, strategy.data?.decisions ?? [], copy, strategy.data?.inEffect ?? []);
  return (
    <section aria-labelledby={`applied-${week.id}`} lang={lang} className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] px-4 py-3'>
      <h3 id={`applied-${week.id}`} className='text-sm font-medium'>{copy.applied}</h3>
      {strategy.isPending ? <p className='text-muted-foreground text-sm' role='status'>{copy.loadingDecisions}</p> : (
        <>
          {strategy.isError && (
            <p role='alert' className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
              {copy.decisionsError}
              <Button type='button' variant='quiet' onClick={() => void strategy.refetch()}>{copy.retry}</Button>
            </p>
          )}
          {summary.applied.length > 0 && (
            <ul className='flex flex-col gap-1 text-sm'>
              {summary.applied.map((entry) => (
                <li key={entry.id} className='break-words'>
                  <span dir='auto'>{entry.statement}</span>
                  <span className='text-muted-foreground'> · {copy.revision(entry.revision)} · {copy.appliedSlots(entry.slots)}</span>
                  {entry.revokedSince && <span className='text-muted-foreground block text-xs' role='note'>{copy.revokedSince}</span>}
                </li>
              ))}
            </ul>
          )}
          {summary.notApplied.length > 0 && (
            <>
              <h4 className='text-muted-foreground text-xs font-medium'>{copy.notApplied}</h4>
              <ul className='text-muted-foreground flex flex-col gap-1 text-xs'>
                {summary.notApplied.map((entry) => <li key={entry.id} className='break-words'><span dir='auto'>{entry.statement}</span>: {entry.reason}</li>)}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
