'use client';

import Link from 'next/link';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { founderHref } from '@/config/founder-nav';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
import { formatRelative, humanize } from '@/features/founder/shared/format';
import type { FounderMode, SourceHealth, SourceState } from '@/lib/founder/types';

/**
 * Data health strip (PRD §5.2 D): every source with its last-good time and state, so a silent source is never read
 * as "all is well". Links to Advanced → Data health for the full picture.
 */

const STATE: Record<SourceState, { status: 'success' | 'warning' | 'danger' | 'neutral' | 'info'; label: string }> = {
  measured: { status: 'success', label: 'Healthy' },
  partial: { status: 'warning', label: 'Partial' },
  stale: { status: 'warning', label: 'Stale' },
  unavailable: { status: 'danger', label: 'Unavailable' },
  unknown: { status: 'neutral', label: 'Unknown' }
};

export function DataHealthStrip({ sources, mode, className }: { sources: SourceHealth[]; mode: FounderMode; className?: string }) {
  return (
    <Panel
      className={className}
      title='Data health'
      titleId='founder-data-health-heading'
      data-tour='founder-data-health'
      actions={
        <Link href={founderHref('advanced', mode, { tab: 'data-health' })} className='rafii-focus text-muted-foreground hover:text-foreground flex items-center gap-1 rounded-sm text-xs'>
          All sources <Icons.arrowRight className='size-3.5' aria-hidden />
        </Link>
      }
    >
      {sources.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title='No source probes recorded yet' description='The cron tick writes one row per source; until then nothing here is known.' />
      ) : (
        <ul className='flex flex-col gap-1.5' aria-label='Source health'>
          {sources.map((source) => {
            const meta = STATE[source.state] ?? STATE.unknown;
            return (
              <li key={source.sourceId} className='flex items-center justify-between gap-3 text-sm'>
                <span className='min-w-0 truncate'>{source.label ?? humanize(source.sourceId)}</span>
                <span className='flex shrink-0 items-center gap-2'>
                  <span className='text-muted-foreground text-xs' title={source.reasonCode ? humanize(source.reasonCode) : undefined}>
                    {source.lastGoodAt ? `last good ${formatRelative(source.lastGoodAt)}` : 'never good'}
                  </span>
                  <StatusChip status={meta.status} className='h-6 px-2 text-[11px]'>
                    {meta.label}
                  </StatusChip>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
