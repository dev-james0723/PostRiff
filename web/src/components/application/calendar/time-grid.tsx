'use client';

import { useLayoutEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { isToday, now, type CalendarDate, type ZonedDateTime } from '@internationalized/date';
import { useDateFormatter } from '@react-aria/i18n';
import { cn } from '@/lib/utils';
import { HOUR_HEIGHT, MIN_EVENT_MINUTES, type CalendarDetailsContext, type CalendarEvent } from './config';
import { EventButton } from './event-button';
import { dayKey, layoutDay, minutesIntoDay } from './utils';

interface TimeGridProps<T> {
  /** Seven days for the week view, one for the day view. */
  days: CalendarDate[];
  focusedDate: CalendarDate;
  byDay: Map<string, CalendarEvent<T>[]>;
  timeZone: string;
  /** Ticks from the parent; `null` until mounted, so the server never renders a stale "now". */
  currentTime: ZonedDateTime | null;
  countLabel: (count: number) => string;
  /** Column headers open that day when given. */
  onOpenDay?: (date: CalendarDate) => void;
  renderDetails?: (event: CalendarEvent<T>, context: CalendarDetailsContext) => ReactNode;
  className?: string;
}

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

export function TimeGrid<T>({
  days,
  focusedDate,
  byDay,
  timeZone,
  currentTime,
  countLabel,
  onOpenDay,
  renderDetails,
  className
}: TimeGridProps<T>) {
  const weekdayShort = useDateFormatter({ weekday: 'short', timeZone });
  const fullDate = useDateFormatter({ weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone });
  // Hour labels are wall-clock hours, so they format a plain local Date with no zone conversion.
  const hourLabel = useDateFormatter({ hour: 'numeric' });
  const timeLabel = useDateFormatter({ hour: 'numeric', minute: '2-digit', timeZone });
  const zoneLabel = useDateFormatter({ timeZoneName: 'short', timeZone });
  const scrollRef = useRef<HTMLDivElement>(null);

  const compact = days.length > 1;
  const columns: CSSProperties = { gridTemplateColumns: `var(--gutter) repeat(${days.length}, minmax(0, 1fr))` };
  const nowColumn = currentTime ? days.findIndex((day) => day.toString() === dayKey(currentTime)) : -1;
  const nowTop = currentTime ? (minutesIntoDay(currentTime) / 60) * HOUR_HEIGHT : 0;
  const zone =
    zoneLabel.formatToParts(days[0].toDate(timeZone)).find((part) => part.type === 'timeZoneName')?.value ?? timeZone;

  const periodKey = `${days[0].toString()}/${days.length}`;
  useLayoutEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    // Open the ruler on something worth seeing: now when it is in view, else the first event, else 8 AM.
    const clock = now(timeZone);
    const showsToday = days.some((day) => day.toString() === dayKey(clock));
    const starts = days.flatMap((day) => byDay.get(day.toString()) ?? []).map((event) => minutesIntoDay(event.start));
    const target = showsToday ? minutesIntoDay(clock) : starts.length > 0 ? Math.min(...starts) : 8 * 60;
    scroller.scrollTop = Math.max(0, (target / 60) * HOUR_HEIGHT - HOUR_HEIGHT);
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- only a new period scrolls; refetched events and clock ticks keep the reader's place
  }, [periodKey]);

  return (
    <div className={cn('flex min-w-0 flex-col [--gutter:3.5rem] md:[--gutter:4.5rem]', className)}>
      <div className='grid border-b' style={columns}>
        <div className='text-muted-foreground flex items-end justify-end px-2 pb-2 text-[10px] font-medium'>{zone}</div>
        {days.map((day) => {
          const today = isToday(day, timeZone);
          const selected = compact && day.compare(focusedDate) === 0;
          const content = (
            <>
              <span className='text-muted-foreground text-xs font-medium'>{weekdayShort.format(day.toDate(timeZone))}</span>
              <span
                className={cn(
                  'flex size-7 items-center justify-center rounded-full text-sm font-semibold',
                  today && 'bg-primary text-primary-foreground',
                  selected && !today && 'bg-muted'
                )}
              >
                {day.day}
              </span>
            </>
          );
          const count = byDay.get(day.toString())?.length ?? 0;
          return onOpenDay ? (
            <button
              key={day.toString()}
              type='button'
              aria-label={`${fullDate.format(day.toDate(timeZone))}${today ? ', today' : ''}, ${countLabel(count)}`}
              onClick={() => onOpenDay(day)}
              className='hover:bg-accent/60 flex min-w-0 flex-col items-center gap-1 py-2 transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset sm:flex-row sm:justify-center sm:gap-2'
            >
              {content}
            </button>
          ) : (
            <div key={day.toString()} className='flex min-w-0 items-center justify-center gap-2 py-2'>
              {content}
            </div>
          );
        })}
      </div>

      <div ref={scrollRef} className='relative h-[28rem] overflow-y-auto overscroll-contain md:h-[36rem]'>
        <div className='relative grid' style={{ ...columns, height: 24 * HOUR_HEIGHT }}>
          <div aria-hidden className='relative border-r'>
            {HOURS.slice(1).map((hour) => (
              <span
                key={hour}
                className='text-muted-foreground absolute right-2 -translate-y-1/2 text-[11px] whitespace-nowrap tabular-nums'
                style={{ top: hour * HOUR_HEIGHT }}
              >
                {hourLabel.format(new Date(2000, 0, 1, hour))}
              </span>
            ))}
          </div>

          {days.map((day) => (
            <div
              key={day.toString()}
              className='relative border-r last:border-r-0'
              style={{
                backgroundImage: 'linear-gradient(to bottom, var(--border) 1px, transparent 1px)',
                backgroundSize: `100% ${HOUR_HEIGHT}px`
              }}
            >
              {layoutDay(byDay.get(day.toString()) ?? [], HOUR_HEIGHT, MIN_EVENT_MINUTES).map(
                ({ event, top, height, lane, lanes }) => (
                  <EventButton
                    key={event.id}
                    event={event}
                    variant='block'
                    compact={compact}
                    timeZone={timeZone}
                    renderDetails={renderDetails}
                    className='absolute z-10'
                    style={{
                      top: top + 1,
                      height: height - 2,
                      left: `calc(${(lane / lanes) * 100}% + 2px)`,
                      width: `calc(${100 / lanes}% - 4px)`
                    }}
                  />
                )
              )}
            </div>
          ))}

          {currentTime && nowColumn !== -1 && (
            <>
              <div aria-hidden className='pointer-events-none absolute right-0 left-(--gutter) z-20' style={{ top: nowTop }}>
                <div className='bg-primary h-0.5 -translate-y-1/2' />
                <span
                  className='bg-primary absolute top-0 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full'
                  style={{ left: `${(nowColumn / days.length) * 100}%` }}
                />
              </div>
              <span
                aria-hidden
                className='bg-primary text-primary-foreground pointer-events-none absolute z-20 -translate-y-1/2 rounded px-1 text-[10px] leading-4 font-semibold whitespace-nowrap tabular-nums'
                style={{ top: nowTop, right: 'calc(100% - var(--gutter) + 4px)' }}
              >
                {timeLabel.format(currentTime.toDate())}
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
