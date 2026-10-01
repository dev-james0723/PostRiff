'use client';

/**
 * Which accepted next-week decisions this week's plan applied (and to how many posts), and which it could not apply,
 * with the reason in words (PRD R-PROOF-02). A decision revoked after planning is marked so: drafts written from now
 * on no longer use it. Shown only when the plan recorded decisions; hidden when proof v2 is off.
 */
import { usePreferences } from '@/lib/preferences';
import { isFeatureDisabled } from '@/lib/growth-v2/request';
import { useStrategy } from '@/lib/growth-v2/proof-hooks';
import { appliedSummary, proofCopy } from '@/lib/growth-v2/proof-present';
import type { AppliedDecision, NotAppliedDecision } from '@/lib/growth-v2/proof-types';
import type { Week } from '@/lib/coworker/types';

type PlannedWeek = Week & { appliedDecisions?: AppliedDecision[]; notApplied?: NotAppliedDecision[] };

export function AppliedDecisions({ week }: { week: Week }) {
  const planned = week as PlannedWeek;
  const recorded = Boolean(planned.appliedDecisions?.length || planned.notApplied?.length);
  const strategy = useStrategy(recorded);
  const copy = proofCopy(usePreferences().locale);
  if (!recorded || (strategy.isError && isFeatureDisabled(strategy.error))) return null;
  const summary = appliedSummary(planned.appliedDecisions, planned.notApplied, strategy.data?.decisions ?? [], copy);
  return (
    <section aria-labelledby={`applied-${week.id}`} className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] px-4 py-3'>
      <h3 id={`applied-${week.id}`} className='text-sm font-medium'>{copy.applied}</h3>
      {summary.applied.length > 0 && (
        <ul className='flex flex-col gap-1 text-sm'>
          {summary.applied.map((entry) => (
            <li key={entry.id}>
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
            {summary.notApplied.map((entry) => <li key={entry.id}><span dir='auto'>{entry.statement}</span>: {entry.reason}</li>)}
          </ul>
        </>
      )}
    </section>
  );
}
