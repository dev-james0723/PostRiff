'use client';

import { useId, useState, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { SegmentedControl } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
import type { Coverage, DataState } from '@/lib/founder/types';
import { ReceiptChips } from './receipt-chip';
import { DataStateChip } from './state-fallbacks';

/**
 * The shared chart frame (CONTRACTS §6, PRD §5.3): title, the question it answers, a period switch, an actions menu
 * with Ask Rafii / View data / Definition / Compare, the chart, and a footer with its receipts and data state. The
 * chart itself is the child; "View data" reveals the table the page passes in, so numbers are shown twice but
 * computed nowhere here.
 */

export interface ChartCardProps {
  title: ReactNode;
  titleId?: string;
  eyebrow?: ReactNode;
  /** The question the chart answers; `subtitle` is the same slot under the pages' name for it. */
  description?: ReactNode;
  subtitle?: ReactNode;
  /** Period options and the current one; with no `onPeriodChange` the period is shown as a label. */
  periods?: readonly string[];
  period?: string;
  onPeriodChange?: (period: string) => void;
  /** Compare toggles a previous-period overlay the page renders. */
  compare?: boolean;
  onCompareChange?: (compare: boolean) => void;
  /** Opens Founder Rafii with a question about this chart. */
  onAsk?: () => void;
  /** The table behind the chart, shown under "View data". */
  data?: ReactNode;
  /** Definition text, or the catalog definition id the page has (shown as the reference). */
  definition?: ReactNode;
  definitionId?: string | null;
  receiptIds?: readonly string[] | null;
  receiptId?: string | null;
  dataState?: DataState;
  asOf?: string | null;
  coverage?: Coverage | null;
  footer?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

function coverageText(coverage?: Coverage | null): string | null {
  if (!coverage || typeof coverage.known !== 'number' || typeof coverage.unknown !== 'number') return null;
  const total = coverage.known + coverage.unknown;
  if (!(total > 0)) return null;
  return `${Math.round((coverage.known / total) * 100)}% of rows have a known value`;
}

export function ChartCard({ title, titleId, eyebrow, description, subtitle, periods, period, onPeriodChange, compare, onCompareChange, onAsk, data, definition, definitionId, receiptIds, receiptId, dataState, asOf, coverage, footer, actions, children, className, bodyClassName }: ChartCardProps) {
  const generated = useId();
  const id = titleId ?? `chart-${generated}`;
  const [view, setView] = useState<'chart' | 'data' | 'definition'>('chart');
  const definitionBody = definition ?? (definitionId ? `Catalog definition ${definitionId}. Ask Rafii for its exact wording and version.` : null);
  const hasMenu = Boolean(onAsk || data || definitionBody || onCompareChange);
  const coverageLine = coverageText(coverage);
  const receipts = [...(receiptIds ?? []), ...(receiptId ? [receiptId] : [])];
  return (
    <Panel
      className={className}
      title={title}
      titleId={id}
      eyebrow={eyebrow}
      description={description ?? subtitle}
      bodyClassName={bodyClassName}
      actions={
        <>
          {periods && period && onPeriodChange ? (
            <SegmentedControl label='Period' size='sm' widths='content' value={period} onChange={onPeriodChange} options={periods.map((value) => ({ value, label: value }))} />
          ) : period ? (
            <StatusChip icon={null} className='h-6 px-2 text-[11px]'>
              {period}
            </StatusChip>
          ) : null}
          {actions}
          {hasMenu && (
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button type='button' variant='quiet' size='icon-sm' aria-label='Chart actions' />}>
                <Icons.dots className='size-4' />
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end' className='min-w-48'>
                {onAsk && (
                  <DropdownMenuItem onClick={onAsk}>
                    <Icons.sparkles className='size-4' /> Ask Rafii
                  </DropdownMenuItem>
                )}
                {data && (
                  <DropdownMenuItem onClick={() => setView(view === 'data' ? 'chart' : 'data')}>
                    <Icons.listDetails className='size-4' /> {view === 'data' ? 'View chart' : 'View data'}
                  </DropdownMenuItem>
                )}
                {definitionBody && (
                  <DropdownMenuItem onClick={() => setView(view === 'definition' ? 'chart' : 'definition')}>
                    <Icons.info className='size-4' /> {view === 'definition' ? 'Hide definition' : 'Definition'}
                  </DropdownMenuItem>
                )}
                {onCompareChange && (
                  <DropdownMenuItem onClick={() => onCompareChange(!compare)}>
                    <Icons.history className='size-4' /> {compare ? 'Hide comparison' : 'Compare'}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </>
      }
      footer={
        dataState || coverageLine || receipts.length || footer ? (
          <div className='flex flex-wrap items-center gap-2'>
            {dataState && <DataStateChip state={dataState} asOf={asOf} />}
            {coverageLine && <span className='text-muted-foreground'>{coverageLine}</span>}
            <ReceiptChips receiptIds={receipts} />
            {footer}
          </div>
        ) : undefined
      }
    >
      {view === 'definition' && definitionBody ? (
        <div className='rafii-quiet text-muted-foreground rounded-[var(--rafii-radius-control)] p-4 text-sm leading-relaxed' role='note'>
          {definitionBody}
        </div>
      ) : view === 'data' && data ? (
        // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a horizontally scrolling table must be reachable by keyboard (WCAG 2.1.1)
        <div className='overflow-x-auto' role='region' aria-labelledby={id} tabIndex={0}>
          {data}
        </div>
      ) : (
        children
      )}
    </Panel>
  );
}
