'use client';

import type { CSSProperties, ReactNode } from 'react';
import { useDateFormatter } from '@react-aria/i18n';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { EVENT_COLORS, type CalendarDetailsContext, type CalendarEvent } from './config';

interface EventButtonProps<T> {
  event: CalendarEvent<T>;
  /** `chip`: one 26px line for month cells. `block`: title over time, sized by the caller on the time ruler. */
  variant: 'chip' | 'block';
  timeZone: string;
  renderDetails?: (event: CalendarEvent<T>, context: CalendarDetailsContext) => ReactNode;
  /** Narrow week columns on phones keep only the colour; the accessible name still says everything. */
  compact?: boolean;
  tabIndex?: number;
  className?: string;
  style?: CSSProperties;
}

export function EventButton<T>({
  event,
  variant,
  timeZone,
  renderDetails,
  compact = false,
  tabIndex,
  className,
  style
}: EventButtonProps<T>) {
  const timeFormatter = useDateFormatter({ hour: 'numeric', minute: '2-digit', timeZone });
  const time = timeFormatter.format(event.start.toDate());
  const label = [event.title, event.status, time].filter(Boolean).join(', ');

  const classes = cn(
    'flex min-w-0 rounded-md border text-left text-xs transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
    EVENT_COLORS[event.color].chip,
    variant === 'chip' ? 'h-[26px] w-full items-center gap-1.5 px-1.5' : 'flex-col overflow-hidden px-2 py-1',
    className
  );

  const body =
    variant === 'chip' ? (
      <>
        {event.icon}
        <span className='min-w-0 flex-1 truncate font-semibold'>{event.title}</span>
        <span className='shrink-0 tabular-nums'>{time}</span>
      </>
    ) : (
      <span className={cn('flex min-w-0 flex-col gap-0.5', compact && 'max-sm:hidden')}>
        <span className='flex min-w-0 items-center gap-1.5'>
          {event.icon}
          <span className='truncate font-semibold'>{event.title}</span>
        </span>
        <span className='tabular-nums'>{time}</span>
      </span>
    );

  if (!renderDetails) {
    return (
      <div className={classes} style={style}>
        <span className='sr-only'>{label}</span>
        <span aria-hidden className='contents'>
          {body}
        </span>
      </div>
    );
  }

  return (
    <Popover>
      <PopoverTrigger data-tour='calendar-event' aria-label={label} tabIndex={tabIndex} className={classes} style={style}>
        {body}
      </PopoverTrigger>
      <PopoverContent align='start' className='w-auto max-w-[calc(100vw-1rem)]'>
        {renderDetails(event, 'popover')}
      </PopoverContent>
    </Popover>
  );
}
