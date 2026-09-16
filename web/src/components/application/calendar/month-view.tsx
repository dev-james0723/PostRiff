'use client';

import { useEffect, useRef, type KeyboardEvent, type ReactNode, type RefObject } from 'react';
import {
  endOfWeek,
  isSameMonth,
  isToday,
  startOfWeek,
  type CalendarDate,
  type DayOfWeek
} from '@internationalized/date';
import { useDateFormatter, useLocale } from '@react-aria/i18n';
import { cn } from '@/lib/utils';
import { EVENT_COLORS, MONTH_CHIP_LIMIT, type CalendarDetailsContext, type CalendarEvent } from './config';
import { EventButton } from './event-button';

interface MonthViewProps<T> {
  /** Whole weeks, from `gridDays('month', …)`. */
  days: CalendarDate[];
  focusedDate: CalendarDate;
  byDay: Map<string, CalendarEvent<T>[]>;
  timeZone: string;
  firstDayOfWeek: DayOfWeek;
  labelledBy: string;
  /** Set by a key press; the grid that shows the new date moves focus to it, even after paging to another month. */
  keyboardMove: RefObject<boolean>;
  countLabel: (count: number) => string;
  onFocusedDateChange: (date: CalendarDate) => void;
  onOpenDay: (date: CalendarDate) => void;
  renderDetails?: (event: CalendarEvent<T>, context: CalendarDetailsContext) => ReactNode;
}

export function MonthView<T>({
  days,
  focusedDate,
  byDay,
  timeZone,
  firstDayOfWeek,
  labelledBy,
  keyboardMove,
  countLabel,
  onFocusedDateChange,
  onOpenDay,
  renderDetails
}: MonthViewProps<T>) {
  const { locale } = useLocale();
  const weekdayShort = useDateFormatter({ weekday: 'short', timeZone });
  const weekdayLong = useDateFormatter({ weekday: 'long', timeZone });
  const fullDate = useDateFormatter({ weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone });
  const gridRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!keyboardMove.current) return;
    const target = gridRef.current?.querySelector<HTMLButtonElement>(`[data-day="${focusedDate.toString()}"]`);
    if (!target) return;
    keyboardMove.current = false;
    target.focus();
  }, [focusedDate, keyboardMove]);

  function moveWithKeys(event: KeyboardEvent<HTMLButtonElement>, day: CalendarDate) {
    const next = {
      ArrowLeft: () => day.subtract({ days: 1 }),
      ArrowRight: () => day.add({ days: 1 }),
      ArrowUp: () => day.subtract({ weeks: 1 }),
      ArrowDown: () => day.add({ weeks: 1 }),
      Home: () => startOfWeek(day, locale, firstDayOfWeek),
      End: () => endOfWeek(day, locale, firstDayOfWeek),
      PageUp: () => (event.shiftKey ? day.subtract({ years: 1 }) : day.subtract({ months: 1 })),
      PageDown: () => (event.shiftKey ? day.add({ years: 1 }) : day.add({ months: 1 }))
    }[event.key];
    if (!next) return;
    event.preventDefault();
    keyboardMove.current = true;
    onFocusedDateChange(next());
  }

  const weeks = Array.from({ length: Math.ceil(days.length / 7) }, (_, index) => days.slice(index * 7, index * 7 + 7));

  return (
    <div ref={gridRef} role='grid' aria-labelledby={labelledBy} className='flex flex-col'>
      <div role='row' className='bg-muted/40 grid grid-cols-7 border-b'>
        {weeks[0]?.map((day) => (
          <div
            key={day.toString()}
            role='columnheader'
            aria-label={weekdayLong.format(day.toDate(timeZone))}
            className='text-muted-foreground py-2 text-center text-xs font-semibold'
          >
            {weekdayShort.format(day.toDate(timeZone))}
          </div>
        ))}
      </div>
      {weeks.map((week) => (
        <div key={week[0].toString()} role='row' className='grid grid-cols-7 border-b last:border-b-0'>
          {week.map((day) => {
            const key = day.toString();
            const events = byDay.get(key) ?? [];
            const inMonth = isSameMonth(day, focusedDate);
            const focused = day.compare(focusedDate) === 0;
            const today = isToday(day, timeZone);
            const overflow = events.length > MONTH_CHIP_LIMIT;
            const chips = overflow ? events.slice(0, MONTH_CHIP_LIMIT - 1) : events;
            const dateLabel = fullDate.format(day.toDate(timeZone));

            return (
              <div
                key={key}
                role='gridcell'
                aria-selected={focused}
                className={cn(
                  'relative flex min-h-[5.5rem] min-w-0 flex-col gap-1 border-r p-1 last:border-r-0 md:min-h-[8.5rem] md:p-2',
                  !inMonth && 'bg-muted/30'
                )}
              >
                <button
                  type='button'
                  data-day={key}
                  tabIndex={focused ? 0 : -1}
                  aria-label={`${dateLabel}${today ? ', today' : ''}, ${countLabel(events.length)}`}
                  onClick={() => onOpenDay(day)}
                  onKeyDown={(event) => moveWithKeys(event, day)}
                  className={cn(
                    'flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
                    // On phones the whole cell opens the day, since a row of dots cannot say what it holds.
                    'after:absolute after:inset-0 md:after:hidden',
                    today ? 'bg-primary text-primary-foreground hover:bg-primary/90' : 'hover:bg-accent',
                    !today && focused && 'bg-muted',
                    !today && !inMonth && 'text-muted-foreground'
                  )}
                >
                  {day.day}
                </button>
                {events.length > 0 && (
                  <>
                    <span aria-hidden className='flex flex-wrap gap-1 px-1 md:hidden'>
                      {events.slice(0, 6).map((event) => (
                        <span key={event.id} className={cn('size-2 rounded-full', EVENT_COLORS[event.color].dot)} />
                      ))}
                    </span>
                    <div className='hidden min-w-0 flex-col gap-1 md:flex'>
                      {chips.map((event) => (
                        <EventButton
                          key={event.id}
                          event={event}
                          variant='chip'
                          timeZone={timeZone}
                          renderDetails={renderDetails}
                          tabIndex={-1}
                        />
                      ))}
                      {overflow && (
                        <button
                          type='button'
                          tabIndex={-1}
                          aria-label={`${events.length - chips.length} more on ${dateLabel}`}
                          onClick={() => onOpenDay(day)}
                          className='text-muted-foreground hover:text-foreground self-start rounded px-1.5 text-xs font-semibold transition-colors'
                        >
                          +{events.length - chips.length} more
                        </button>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
