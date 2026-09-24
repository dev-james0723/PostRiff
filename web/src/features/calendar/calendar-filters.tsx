'use client';

import type { ReactNode } from 'react';
import { ToneIcon } from '@/components/application/calendar/event-button';
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
}

/**
 * A pressed chip catches the selected glass; with no filter in its group every chip rests on glass, and once one is
 * pressed the others go quiet (DNA §10.5). The glyph and the label say what the chip stands for, never a colour.
 */
function FilterChip({ label, name = label, count, unit, filtering, selected, onPress, leading }: FilterChipProps) {
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
        'rafii-focus relative inline-flex h-11 shrink-0 items-center gap-1.5 rounded-full px-3 text-xs font-medium whitespace-nowrap transition-colors duration-200 md:h-9',
        !filtering && 'rafii-glass text-foreground',
        pressed && 'rafii-glass-selected text-foreground',
        filtering && !selected && 'rafii-quiet text-muted-foreground hover:text-foreground'
      )}
    >
      <span className={cn('flex items-center', filtering && !selected && 'opacity-60')}>{leading}</span>
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

/** Status and account chips that double as the legend. Counts are real entries inside the visible period. */
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
        <span className='text-muted-foreground mt-1 w-14 shrink-0 py-2 text-xs font-medium max-sm:sr-only'>Status</span>
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
                leading={<ToneIcon tone={meta.tone} className='size-3.5' />}
              />
            );
          })}
        </div>
      </div>

      {channels.length > 1 && (
        <div className='flex min-w-0 items-start gap-2'>
          <span className='text-muted-foreground mt-1 w-14 shrink-0 py-2 text-xs font-medium max-sm:sr-only'>Account</span>
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
              />
            ))}
          </div>
        </div>
      )}

      {showFooter && (
        <div aria-live='polite' className='text-muted-foreground flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1 px-1 text-xs'>
          {periodNote}
          {filtering && (
            <Button variant='quiet' size='sm' className='-mx-2 h-8 text-xs' onClick={onReset}>
              Show all
            </Button>
          )}
          {live && (
            <span className='flex items-center gap-1.5'>
              <span aria-hidden className='rafii-decorative-motion bg-foreground size-1.5 animate-pulse rounded-full motion-reduce:animate-none' />
              Checking for updates every {LIVE_REFRESH_MS / 1000} seconds while a post is going out
            </span>
          )}
        </div>
      )}
    </div>
  );
}
