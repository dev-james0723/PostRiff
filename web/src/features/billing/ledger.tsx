'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { DigitSwap } from '@/components/motion/digit-swap';
import { SegmentedControl, StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { usd } from '@/lib/api/client';
import type { LedgerEntry } from '@/lib/api/types';
import { downloadBlob } from '@/lib/download';
import { formatDateTime } from '@/lib/time';
import { LEDGER_FILTER_LABELS } from './billing-copy';
import {
  LEDGER_FILTERS,
  LEDGER_PAGE,
  allowanceNote,
  costStateOf,
  dimensionLabel,
  filterLedger,
  isZeroCostRun,
  ledgerCounts,
  ledgerCsv,
  stepLabel,
  type LedgerFilter
} from './billing-model';

/** "$0 run" and what the row did to an allowance (when the API says), as small markers. */
function Markers({ entry }: { entry: LedgerEntry }) {
  const note = allowanceNote(entry);
  const zero = isZeroCostRun(entry);
  if (!note && !zero) return null;
  return (
    <span className='flex flex-wrap gap-1'>
      {zero && <span className='rafii-quiet text-muted-foreground rounded-md px-1.5 py-0.5 text-[11px] font-medium'>$0 run</span>}
      {note && <span className='rafii-quiet text-muted-foreground rounded-md px-1.5 py-0.5 text-[11px] font-medium'>{note}</span>}
    </span>
  );
}

function StateBadge({ entry }: { entry: LedgerEntry }) {
  const state = costStateOf(entry.costState);
  return (
    <AnimatedBadge status={state.tone} size='sm' showIcon={false} contentKey={entry.costState}>
      {state.label}
    </AnimatedBadge>
  );
}

function rowKey(entry: LedgerEntry, index: number) {
  return `${entry.at}-${entry.kind}-${entry.dimension}-${index}`;
}

/** One entry per row on a narrow container: when and what first, then estimate → actual and the state. */
function StackedRows({ entries }: { entries: LedgerEntry[] }) {
  return (
    <ul className='flex flex-col gap-1.5 @3xl:hidden'>
      {entries.map((entry, index) => (
        <li key={rowKey(entry, index)} className='rafii-quiet flex flex-col gap-1.5 rounded-[var(--rafii-radius-control)] p-3 text-sm'>
          <div className='flex items-baseline justify-between gap-3'>
            <span className='text-foreground font-medium'>
              {dimensionLabel(entry.dimension)} <span className='text-muted-foreground font-normal'>· {stepLabel(entry.kind)}</span>
            </span>
            <span className='text-muted-foreground shrink-0 text-xs'>{formatDateTime(entry.at)}</span>
          </div>
          {entry.model && <span className='text-muted-foreground truncate text-xs'>{entry.model}</span>}
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <span className='text-foreground tabular-nums'>
              {usd(entry.estimatedUsdMicro)} <span className='text-muted-foreground'>estimated →</span> {usd(entry.actualUsdMicro)}{' '}
              <span className='text-muted-foreground'>actual</span>
            </span>
            <StateBadge entry={entry} />
          </div>
          <Markers entry={entry} />
        </li>
      ))}
    </ul>
  );
}

function LedgerTable({ entries }: { entries: LedgerEntry[] }) {
  return (
    <div className='relative rafii-quiet hidden overflow-x-auto rounded-[var(--rafii-radius-card)] px-2 @3xl:block'>
      <Table>
        <TableHeader>
          <TableRow className='border-foreground/8 hover:bg-transparent'>
            <TableHead>When</TableHead>
            <TableHead>What</TableHead>
            <TableHead>Step</TableHead>
            <TableHead className='text-right'>Estimated</TableHead>
            <TableHead className='text-right'>Actual</TableHead>
            <TableHead>State</TableHead>
            <TableHead>Allowance</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map((entry, index) => (
            <TableRow key={rowKey(entry, index)} className='border-foreground/8 hover:bg-transparent'>
              <TableCell className='whitespace-nowrap'>{formatDateTime(entry.at)}</TableCell>
              <TableCell>
                <div className='flex flex-col'>
                  <span>{dimensionLabel(entry.dimension)}</span>
                  {entry.model && <span className='text-muted-foreground max-w-48 truncate text-xs'>{entry.model}</span>}
                </div>
              </TableCell>
              <TableCell className='whitespace-nowrap'>{stepLabel(entry.kind)}</TableCell>
              <TableCell className='text-right tabular-nums'>{usd(entry.estimatedUsdMicro)}</TableCell>
              <TableCell className='text-right tabular-nums'>{usd(entry.actualUsdMicro)}</TableCell>
              <TableCell>
                <StateBadge entry={entry} />
              </TableCell>
              <TableCell>
                <Markers entry={entry} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Every reservation, settlement and release the API returns (its latest 100), newest first. */
export function Ledger({ entries, canEdit }: { entries: LedgerEntry[]; canEdit: boolean }) {
  const [filter, setFilter] = useState<LedgerFilter>('all');
  const [showAll, setShowAll] = useState(false);
  const counts = ledgerCounts(entries);
  const filtered = filterLedger(entries, filter);
  const visible = showAll ? filtered : filtered.slice(0, LEDGER_PAGE);

  function exportCsv() {
    const stamp = new Date().toISOString().slice(0, 10);
    const name = filter === 'all' ? `usage-${stamp}.csv` : `usage-${filter}-${stamp}.csv`;
    downloadBlob(new Blob([ledgerCsv(filtered)], { type: 'text/csv;charset=utf-8' }), name);
  }

  return (
    <section className='@container flex flex-col gap-3' aria-labelledby='ledger-heading' data-tour='billing-ledger'>
      <div className='px-1'>
        <h3 id='ledger-heading' className='text-foreground text-lg font-medium tracking-tight'>
          Recent usage
        </h3>
        <p className='text-muted-foreground text-sm'>Each run reserves an estimate, then settles to the real cost or is released if it failed.</p>
      </div>

      {entries.length === 0 ? (
        <div data-tour='billing-ledger-empty'>
          <StateMessage
            kind='empty'
            media={
              <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 items-center justify-center rounded-full'>
                <Icons.creditCard className='size-5' />
              </span>
            }
            title='No usage yet'
            description='Every drafting run appears here: runs with no paid model at $0, paid runs as a reservation that then settles to the real cost.'
            action={
              canEdit ? (
                <Link href='/app/ideas?new=1' className={buttonVariants({ variant: 'glass', size: 'control' })}>
                  <Icons.sparkles className='size-4' /> Start an idea
                </Link>
              ) : undefined
            }
          />
        </div>
      ) : (
        <>
          {/* FIND / VIEW row (DNA §9.1): the filter narrows the view only; the export follows the filter. */}
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <SegmentedControl
              label='Filter usage'
              size='sm'
              widths='content'
              value={filter}
              onChange={(value) => {
                setFilter(value);
                setShowAll(false);
              }}
              options={LEDGER_FILTERS.map((value) => ({
                value,
                label: (
                  <span className='inline-flex items-center gap-1.5'>
                    {LEDGER_FILTER_LABELS[value]}
                    <DigitSwap value={counts[value]} className='text-xs opacity-75' />
                  </span>
                )
              }))}
            />
            <Button variant='glass' size='sm' className='min-h-10 px-3.5' onClick={exportCsv} disabled={filtered.length === 0}>
              <Icons.download className='size-4' />
              Export {filtered.length.toLocaleString()} {filtered.length === 1 ? 'row' : 'rows'} (CSV)
            </Button>
          </div>

          {filtered.length === 0 ? (
            <StateMessage kind='empty' layout='inline' title={`No ${LEDGER_FILTER_LABELS[filter].toLowerCase()} entries among the latest ${entries.length.toLocaleString()}.`} />
          ) : (
            <>
              <StackedRows entries={visible} />
              <LedgerTable entries={visible} />
            </>
          )}

          <div className='text-muted-foreground flex flex-wrap items-center justify-between gap-2 px-1 text-xs'>
            <span>
              {filtered.length > 0 && `Showing ${visible.length.toLocaleString()} of ${filtered.length.toLocaleString()} · `}
              {filtered.length > 0 ? 'the' : 'The'} workspace lists its latest {entries.length.toLocaleString()} {entries.length === 1 ? 'entry' : 'entries'} here
              (up to 100)
            </span>
            {filtered.length > LEDGER_PAGE && (
              <Button variant='quiet' size='sm' className='min-h-9' onClick={() => setShowAll((value) => !value)}>
                {showAll ? `Show latest ${LEDGER_PAGE}` : `Show all ${filtered.length.toLocaleString()}`}
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
