'use client';

import Link from 'next/link';
import { useId } from 'react';
import { Icons } from '@/components/icons';
import { Surface } from '@/components/rafii';
import { StatusChip } from '@/features/queue/status-chip';
import manifestJson from '@/lib/site-agent/route-manifest.json';
import { safeHref, type RouteManifest } from '@/lib/site-agent/routes';
import type { SiteAgentCalendarCard } from '@/lib/site-agent/types';
import { cn } from '@/lib/utils';
import {
  CALENDAR_STATUS_META,
  QUEUE_COUNT_META,
  calendarCountAria,
  calendarCountText,
  calendarSourceText
} from './calendar-card-model';

const MANIFEST = manifestJson as RouteManifest;

export function CalendarCard({
  block,
  onNavigate
}: {
  block: SiteAgentCalendarCard;
  onNavigate?: () => void;
}) {
  const titleId = useId();
  const rangeLabel = block.range?.label || 'Requested range';
  const sourceText = calendarSourceText(
    block.sources?.calendarRange ?? 'unavailable',
    block.sources?.queueSummary ?? 'unavailable'
  );
  const href = block.href ? safeHref(MANIFEST, block.href) : null;

  return (
    <Surface
      material='glass'
      padding='none'
      className='overflow-hidden'
      role='region'
      aria-labelledby={titleId}
      data-testid='calendar-card'
    >
      <header className='flex min-w-0 items-start gap-3 p-3.5 sm:p-4'>
        <span
          aria-hidden
          className='rafii-lens text-foreground flex size-9 shrink-0 items-center justify-center rounded-[var(--rafii-radius-control)]'
        >
          <Icons.calendar className='size-4.5' />
        </span>
        <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
          <div className='flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5'>
            <h3 id={titleId} className='text-sm font-semibold'>
              Calendar
            </h3>
            <span className='text-muted-foreground text-[10px] font-medium tracking-[0.08em] uppercase'>
              Read-only snapshot
            </span>
          </div>
          <p className='text-foreground text-sm leading-snug font-medium break-words'>
            {rangeLabel}
          </p>
          {block.range?.timeZone && (
            <p className='text-muted-foreground text-[11px] break-words'>{block.range.timeZone}</p>
          )}
        </div>
      </header>

      <div
        className='border-border/60 border-t px-3.5 py-3 sm:px-4'
        aria-label={`Status counts for ${rangeLabel}`}
      >
        <p className='text-muted-foreground mb-2 text-[10px] font-medium tracking-[0.1em] uppercase'>
          In this range
        </p>
        <dl className='grid min-w-0 grid-cols-2 gap-2 min-[400px]:grid-cols-3'>
          {(block.statuses ?? []).map((status) => {
            const meta = CALENDAR_STATUS_META[status.key] ?? CALENDAR_STATUS_META.unknown;
            return (
              <div
                key={status.key}
                className='rafii-quiet flex min-h-15 min-w-0 flex-col justify-between gap-1.5 rounded-[var(--rafii-radius-control)] px-2.5 py-2'
              >
                <dt className='text-muted-foreground text-[10px] leading-tight font-medium break-words'>
                  {meta.label}
                </dt>
                <dd
                  className='text-foreground text-lg leading-none font-semibold tabular-nums'
                  aria-label={calendarCountAria(meta.label, status.count)}
                >
                  {calendarCountText(status.count)}
                </dd>
              </div>
            );
          })}
        </dl>
      </div>

      <div className='border-border/60 border-t px-3.5 py-3 sm:px-4'>
        <div className='mb-2 flex min-w-0 flex-wrap items-center justify-between gap-2'>
          <p className='text-muted-foreground text-[10px] font-medium tracking-[0.1em] uppercase'>
            Stored entries
          </p>
          <span
            className='text-muted-foreground text-[11px] tabular-nums'
            aria-label={calendarCountAria('Total calendar entries', block.total)}
          >
            {calendarCountText(block.total)} total
          </span>
        </div>
        {block.entries?.length ? (
          <ol
            className='flex min-w-0 flex-col gap-1.5'
            aria-label={`Calendar entries for ${rangeLabel}`}
          >
            {block.entries.map((entry, index) => {
              const meta = CALENDAR_STATUS_META[entry.status] ?? CALENDAR_STATUS_META.unknown;
              const name =
                [entry.platform, entry.account].filter(Boolean).join(' · ') ||
                entry.title ||
                'Calendar entry';
              return (
                <li
                  key={`${entry.kind ?? 'entry'}-${entry.id ?? index}`}
                  className='rafii-quiet flex min-w-0 flex-col gap-1.5 rounded-[var(--rafii-radius-control)] px-2.5 py-2'
                >
                  <div className='flex min-w-0 flex-wrap items-start justify-between gap-1.5'>
                    <span className='min-w-0 flex-1 text-xs leading-snug font-medium break-words'>
                      {name}
                    </span>
                    <StatusChip
                      tone={meta.tone}
                      pulse={meta.pulse}
                      size='sm'
                      className='max-w-full'
                      contentKey={`${entry.id}-${entry.state}`}
                    >
                      {meta.label}
                    </StatusChip>
                  </div>
                  <div className='text-muted-foreground flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[11px] leading-snug'>
                    {entry.when && <span className='break-words'>{entry.when}</span>}
                    {entry.title && entry.title !== name && (
                      <span className='break-words'>{entry.title}</span>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className='text-muted-foreground text-sm'>No stored entries in this range.</p>
        )}
        {block.truncated && (
          <p className='text-muted-foreground mt-2 text-[11px]'>
            Showing the first {block.entries.length}; the total above remains exact.
          </p>
        )}
      </div>

      <footer className='border-border/60 flex min-w-0 flex-col gap-2 border-t px-3.5 py-3 sm:px-4'>
        <div
          className='flex min-w-0 flex-wrap items-center gap-1.5'
          aria-label='Current queue counts'
        >
          <span className='text-muted-foreground mr-0.5 text-[10px] font-medium tracking-[0.08em] uppercase'>
            Queue now
          </span>
          {QUEUE_COUNT_META.map(([key, label]) => (
            <span
              key={key}
              className='rafii-quiet text-muted-foreground inline-flex min-h-6 items-center rounded-full px-2 text-[10px] tabular-nums'
              aria-label={calendarCountAria(label, block.queue?.[key])}
            >
              {calendarCountText(block.queue?.[key])} {label}
            </span>
          ))}
        </div>
        <div className='flex min-w-0 flex-wrap items-center justify-between gap-2'>
          <span
            className={cn(
              'text-[10px] leading-snug',
              block.sources?.calendarRange === 'verified' &&
                block.sources?.queueSummary === 'verified'
                ? 'text-muted-foreground'
                : 'text-destructive'
            )}
          >
            {sourceText}
          </span>
          {href && (
            <Link
              href={href}
              onClick={onNavigate}
              className='rafii-focus text-foreground inline-flex min-h-8 shrink-0 items-center gap-1 text-xs font-medium underline decoration-border underline-offset-4'
            >
              Open Calendar
              <Icons.arrowRight className='size-3.5' aria-hidden />
            </Link>
          )}
        </div>
      </footer>
    </Surface>
  );
}
