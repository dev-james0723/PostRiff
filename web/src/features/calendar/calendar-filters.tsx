'use client';

import type { ReactNode } from 'react';
import { EVENT_COLORS } from '@/components/application/calendar/config';
import { ChannelIcon } from '@/components/channel-icon';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { KIND_META, KINDS, type Kind } from './calendar-kinds';
import { LIVE_REFRESH_MS } from './use-calendar-live';

export type PeriodUnit = 'month' | 'week' | 'day';

export interface ChannelOption {
  /** The connection id, or `platform:account` for a post whose connection is no longer listed. */
  key: string;
  platform: string;
  account: string;
}

/**
 * The next selection after a chip is pressed. With everything shown, a press shows only that value; after that
 * presses add and remove values. Emptying the selection, or selecting everything, returns `null` (show all), so
 * the address never carries a filter that hides nothing.
 */
export function toggleSelection<T extends string>(all: readonly T[], selected: readonly T[] | null, value: T): T[] | null {
  if (!selected) return [value];
  const next = selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value];
  if (next.length === 0 || all.every((item) => next.includes(item))) return null;
  return all.filter((item) => next.includes(item));
}

interface FilterChipProps {
  label: string;
  /** Read instead of the label when the label alone is ambiguous (the same handle on two platforms). */
  name?: string;
  count: number;
  unit: PeriodUnit;
  /** A filter of this group is active. */
  filtering: boolean;
  selected: boolean;
  onPress: () => void;
  leading: ReactNode;
  selectedClassName: string;
}

function FilterChip({ label, name = label, count, unit, filtering, selected, onPress, leading, selectedClassName }: FilterChipProps) {
  const pressed = filtering && selected;
  const hint = !filtering ? `Show only ${label}` : selected ? `Hide ${label}` : `Also show ${label}`;
  return (
    <button
      type='button'
      aria-pressed={pressed}
      aria-label={`${name}: ${count} this ${unit}`}
      title={hint}
      onClick={onPress}
      className={cn(
        'relative inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium whitespace-nowrap transition-[color,background-color,border-color] duration-150 outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
        !filtering && 'border-border bg-background text-foreground hover:bg-muted',
        pressed && selectedClassName,
        filtering && !selected && 'text-muted-foreground hover:text-foreground border-dashed bg-transparent hover:bg-muted'
      )}
    >
      <span className={cn('flex items-center', filtering && !selected && 'opacity-50')}>{leading}</span>
      {label}
      <DigitSwap value={count} className={cn('tabular-nums', count === 0 ? 'opacity-50' : 'opacity-80')} />
    </button>
  );
}

interface CalendarFiltersProps {
  unit: PeriodUnit;
  kindCounts: Record<Kind, number>;
  selectedKinds: Kind[] | null;
  onKindsChange: (next: Kind[] | null) => void;
  channels: (ChannelOption & { count: number })[];
  selectedChannels: string[] | null;
  onChannelsChange: (next: string[] | null) => void;
  onReset: () => void;
  /** The snapshot is being read again on a timer. */
  live: boolean;
  /** What to say when nothing in the period matches, with a way to the nearest post. */
  periodNote?: ReactNode;
}

// `relative` keeps the chips' screen-reader text (absolutely positioned) inside the scroller, so a long row
// scrolls on its own instead of widening the page.
const ROW = 'scrollbar-hide relative flex min-w-0 flex-1 gap-1.5 overflow-x-auto p-1 sm:flex-wrap';

/** Status and account chips that double as the colour legend. Counts are real entries inside the visible period. */
export function CalendarFilters({
  unit,
  kindCounts,
  selectedKinds,
  onKindsChange,
  channels,
  selectedChannels,
  onChannelsChange,
  onReset,
  live,
  periodNote
}: CalendarFiltersProps) {
  const filtering = selectedKinds !== null || selectedChannels !== null;
  const channelKeys = channels.map((channel) => channel.key);
  const showFooter = filtering || live || periodNote;

  return (
    <div data-tour='calendar-legend' className='flex min-w-0 flex-col gap-1'>
      <div className='flex min-w-0 items-start gap-2'>
        <span className='text-muted-foreground mt-1 shrink-0 py-1.5 text-xs font-medium max-sm:sr-only'>Status</span>
        <div role='group' aria-label={`Legend and status filter, counted for this ${unit}`} className={ROW}>
          {KINDS.map((kind) => {
            const meta = KIND_META[kind];
            return (
              <FilterChip
                key={kind}
                label={meta.label}
                count={kindCounts[kind]}
                unit={unit}
                filtering={selectedKinds !== null}
                selected={selectedKinds?.includes(kind) ?? true}
                onPress={() => onKindsChange(toggleSelection(KINDS, selectedKinds, kind))}
                leading={<span aria-hidden className={cn('size-2 rounded-full', EVENT_COLORS[meta.color].dot)} />}
                selectedClassName={EVENT_COLORS[meta.color].chip}
              />
            );
          })}
        </div>
      </div>

      {channels.length > 1 && (
        <div className='flex min-w-0 items-start gap-2'>
          <span className='text-muted-foreground mt-1 shrink-0 py-1.5 text-xs font-medium max-sm:sr-only'>Account</span>
          <div role='group' aria-label={`Account filter, counted for this ${unit}`} className={ROW}>
            {channels.map((channel) => (
              <FilterChip
                key={channel.key}
                label={channel.account}
                name={`${channel.platform} ${channel.account}`}
                count={channel.count}
                unit={unit}
                filtering={selectedChannels !== null}
                selected={selectedChannels?.includes(channel.key) ?? true}
                onPress={() => onChannelsChange(toggleSelection(channelKeys, selectedChannels, channel.key))}
                leading={<ChannelIcon platform={channel.platform} name={channel.platform} size='xs' />}
                selectedClassName='border-foreground/25 bg-accent text-accent-foreground'
              />
            ))}
          </div>
        </div>
      )}

      {showFooter && (
        <div aria-live='polite' className='text-muted-foreground flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1 px-1 text-xs'>
          {periodNote}
          {filtering && (
            <Button variant='ghost' size='xs' className='-mx-2' onClick={onReset}>
              Show all
            </Button>
          )}
          {live && (
            <span className='flex items-center gap-1.5'>
              <span aria-hidden className='size-1.5 rounded-full bg-emerald-500' />
              Checking for updates every {LIVE_REFRESH_MS / 1000} seconds while a post is going out
            </span>
          )}
        </div>
      )}
    </div>
  );
}
