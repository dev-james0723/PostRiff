'use client';

import { DigitSwap } from '@/components/motion/digit-swap';
import { Tabs, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { FAMILIES, FAMILY_LABELS, personText, type Family, type Person } from './audit-model';

export interface ActorOption {
  value: string;
  person: Person;
  count: number;
}

const EVERYONE = 'everyone';

/**
 * Kind pills and the person filter. Counts are exact for the events the API returned; the page says
 * how many that is. While the log loads the counts are skeletons, never zeros.
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
  const filtered = family !== 'all' || actor !== null;
  // Profile names need not be unique: when two options read the same, the start of the id tells them apart.
  const sameText = new Map<string, number>();
  for (const option of actorOptions ?? []) {
    const label = personText(option.person);
    sameText.set(label, (sameText.get(label) ?? 0) + 1);
  }

  return (
    <div className='flex min-w-0 flex-col gap-2 lg:flex-row lg:items-center lg:justify-between'>
      <Tabs value={family} onValueChange={(value) => onFamily(value as Family)} variant='pill' className='min-w-0 max-w-full'>
        <TabsList aria-label='Filter events by kind' data-tour='audit-categories' className='scrollbar-hide max-w-full overflow-x-auto border'>
          {visible.map((value) => (
            <TabsTrigger key={value} value={value} className='gap-1.5 px-3 py-1'>
              {FAMILY_LABELS[value]}
              {familyCounts ? (
                <DigitSwap value={familyCounts[value]} className='text-xs opacity-75' />
              ) : (
                <Skeleton aria-hidden className='h-4 w-5' />
              )}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className='flex min-w-0 items-center gap-2' data-tour='audit-filters'>
        {loaded ? (
          <Select value={actor ?? EVERYONE} onValueChange={(value) => onActor(!value || value === EVERYONE ? null : String(value))}>
            <SelectTrigger aria-label='Filter events by person' className='min-w-0 max-w-full sm:w-56'>
              <SelectValue>
                <span className='min-w-0 truncate'>{selected ? personText(selected.person) : actor !== null ? actor.slice(0, 8) : 'Everyone'}</span>
                <span className='text-muted-foreground shrink-0 tabular-nums'>{selected ? selected.count : actor !== null ? 0 : everyoneCount}</span>
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
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
          <Skeleton aria-hidden className='h-8 w-56 max-w-full rounded-lg' />
        )}
        {filtered && (
          <Button variant='ghost' size='sm' onClick={onReset}>
            Reset
          </Button>
        )}
      </div>
    </div>
  );
}
