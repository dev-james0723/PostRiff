'use client';

import { DigitSwap } from '@/components/motion/digit-swap';
import { ActiveFilters, SegmentedControl, Workbar, type SegmentOption } from '@/components/rafii';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { SELECT_TRIGGER_CLASS } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { FAMILIES, FAMILY_LABELS, personText, type Family, type Person } from './audit-model';

export interface ActorOption {
  value: string;
  person: Person;
  count: number;
}

const EVERYONE = 'everyone';

/**
 * WHAT and FIND for the log (DNA §9.1): the kind segments and the person filter, with the applied
 * constraints summarised while they narrow the list. Counts are exact for the events the API returned;
 * the page says how many that is. While the log loads the counts are skeletons, never zeros.
 */
export function AuditFilters({
  family,
  onFamily,
  actor,
  onActor,
  familyCounts,
  actorOptions,
  everyoneCount,
  onReset
}: {
  family: Family;
  onFamily: (family: Family) => void;
  actor: string | null;
  onActor: (actor: string | null) => void;
  /** Null while loading. */
  familyCounts: Record<Family, number> | null;
  actorOptions: ActorOption[] | null;
  everyoneCount: number | null;
  onReset: () => void;
}) {
  const loaded = familyCounts !== null && actorOptions !== null;
  const visible = FAMILIES.filter((value) => value !== 'other' || value === family || (familyCounts?.other ?? 0) > 0);
  const selected = actorOptions?.find((option) => option.value === actor) ?? null;
  const activeCount = (family !== 'all' ? 1 : 0) + (actor !== null ? 1 : 0);
  // Profile names need not be unique: when two options read the same, the start of the id tells them apart.
  const sameText = new Map<string, number>();
  for (const option of actorOptions ?? []) {
    const label = personText(option.person);
    sameText.set(label, (sameText.get(label) ?? 0) + 1);
  }
  const options: SegmentOption<Family>[] = visible.map((value) => ({
    value,
    ariaLabel: familyCounts ? `${FAMILY_LABELS[value]}, ${familyCounts[value]} ${familyCounts[value] === 1 ? 'event' : 'events'}` : FAMILY_LABELS[value],
    label: (
      <span className='inline-flex items-center gap-1.5'>
        {FAMILY_LABELS[value]}
        {familyCounts ? <DigitSwap value={familyCounts[value]} className='text-muted-foreground text-xs tabular-nums' /> : <Skeleton aria-hidden className='h-4 w-5' />}
      </span>
    )
  }));
  const personLabel = selected ? personText(selected.person) : actor !== null ? actor.slice(0, 8) : null;
  const summary = [family !== 'all' ? FAMILY_LABELS[family] : null, personLabel].filter(Boolean).join(' · ');

  return (
    <Workbar
      tabs={
        <div data-tour='audit-categories' className='relative scrollbar-hide -mx-1 max-w-full overflow-x-auto px-1 pb-1'>
          <SegmentedControl options={options} value={family} onChange={onFamily} label='Filter events by kind' widths='content' size='md' className='min-w-max' />
        </div>
      }
      filters={
        <div className='flex min-w-0 items-center gap-2' data-tour='audit-filters'>
          {loaded ? (
            <Select value={actor ?? EVERYONE} onValueChange={(value) => onActor(!value || value === EVERYONE ? null : String(value))}>
              <SelectTrigger aria-label='Filter events by person' className={cn(SELECT_TRIGGER_CLASS, 'min-w-0 max-w-full sm:w-64')}>
                <SelectValue>
                  <span className='min-w-0 truncate'>{selected ? personText(selected.person) : actor !== null ? actor.slice(0, 8) : 'Everyone'}</span>
                  <span className='text-muted-foreground shrink-0 tabular-nums'>{selected ? selected.count : actor !== null ? 0 : everyoneCount}</span>
                </SelectValue>
              </SelectTrigger>
              <SelectContent className='rafii-elevated rounded-[var(--rafii-radius-control)] ring-0'>
                <SelectItem value={EVERYONE}>
                  Everyone
                  <span className='text-muted-foreground ml-auto tabular-nums'>{everyoneCount}</span>
                </SelectItem>
                {actorOptions.map((option) => {
                  const { person } = option;
                  const showId = person.short !== null && (!person.role || (sameText.get(personText(person)) ?? 0) > 1);
                  return (
                    <SelectItem key={option.value} value={option.value}>
                      <span className='min-w-0 truncate'>{person.name}</span>
                      {person.role && <span className='text-muted-foreground text-xs'>{person.role}</span>}
                      {showId && <span className='text-muted-foreground font-mono text-xs'>{person.short}</span>}
                      <span className='text-muted-foreground ml-auto pl-3 tabular-nums'>{option.count}</span>
                    </SelectItem>
                  );
                })}
                {actor !== null && !selected && (
                  <SelectItem value={actor}>
                    <span className='font-mono text-xs'>{actor.slice(0, 8)}</span>
                    <span className='text-muted-foreground ml-auto pl-3 tabular-nums'>0</span>
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          ) : (
            <Skeleton aria-hidden className='h-12 w-64 max-w-full rounded-[var(--rafii-radius-control)]' />
          )}
        </div>
      }
      summary={<ActiveFilters count={activeCount} summary={summary} onClear={onReset} clearLabel='Reset' />}
    />
  );
}
