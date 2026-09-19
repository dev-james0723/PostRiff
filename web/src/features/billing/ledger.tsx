'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Tabs, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Button, buttonVariants } from '@/components/ui/button';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
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
      {zero && <span className='bg-muted text-muted-foreground rounded px-1.5 py-0.5 text-[11px] font-medium'>$0 run</span>}
      {note && <span className='bg-muted text-muted-foreground rounded px-1.5 py-0.5 text-[11px] font-medium'>{note}</span>}
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
    <ul className='divide-y rounded-lg border @3xl:hidden'>
      {entries.map((entry, index) => (
        <li key={rowKey(entry, index)} className='flex flex-col gap-1.5 p-3 text-sm'>
          <div className='flex items-baseline justify-between gap-3'>
            <span className='font-medium'>
              {dimensionLabel(entry.dimension)} <span className='text-muted-foreground font-normal'>· {stepLabel(entry.kind)}</span>
            </span>
            <span className='text-muted-foreground shrink-0 text-xs'>{formatDateTime(entry.at)}</span>
          </div>
          {entry.model && <span className='text-muted-foreground truncate text-xs'>{entry.model}</span>}
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <span className='tabular-nums'>
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
    <div className='hidden overflow-x-auto rounded-lg border @3xl:block'>
      <Table>
        <TableHeader>
          <TableRow>
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
            <TableRow key={rowKey(entry, index)}>
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
      <div>
        <h3 id='ledger-heading' className='text-lg font-semibold'>
          Recent usage
        </h3>
        <p className='text-muted-foreground text-sm'>Each run reserves an estimate, then settles to the real cost or is released if it failed.</p>
      </div>

      {entries.length === 0 ? (
        <Empty className='border' data-tour='billing-ledger-empty'>
          <EmptyHeader>
            <EmptyMedia variant='icon'>
              <Icons.creditCard />
            </EmptyMedia>
            <EmptyTitle>No usage yet</EmptyTitle>
            <EmptyDescription>
              Every drafting run appears here: runs with no paid model at $0, paid runs as a reservation that then settles to the real cost.
            </EmptyDescription>
          </EmptyHeader>
          {canEdit && (
            <EmptyContent>
              <Link href='/app/ideas?new=1' className={buttonVariants({ variant: 'outline', size: 'sm' })}>
                <Icons.sparkles className='size-4' /> Start an idea
              </Link>
            </EmptyContent>
          )}
        </Empty>
      ) : (
        <>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <Tabs
              value={filter}
              onValueChange={(value) => {
                setFilter(value as LedgerFilter);
                setShowAll(false);
              }}
              variant='segment'
              className='min-w-0 max-w-full'
            >
              <TabsList aria-label='Filter usage' className='max-w-full overflow-x-auto border'>
                {LEDGER_FILTERS.map((value) => (
                  <TabsTrigger key={value} value={value} className='gap-1.5 px-3 py-1'>
                    {LEDGER_FILTER_LABELS[value]}
                    <DigitSwap value={counts[value]} className='text-xs opacity-75' />
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            <Button variant='outline' size='sm' onClick={exportCsv} disabled={filtered.length === 0}>
              <Icons.download className='size-4' />
              Export {filtered.length.toLocaleString()} {filtered.length === 1 ? 'row' : 'rows'} (CSV)
            </Button>
          </div>

          {filtered.length === 0 ? (
            <p className='text-muted-foreground rounded-lg border p-4 text-sm'>
              No {LEDGER_FILTER_LABELS[filter].toLowerCase()} entries among the latest {entries.length.toLocaleString()}.
            </p>
          ) : (
            <>
              <StackedRows entries={visible} />
              <LedgerTable entries={visible} />
            </>
          )}

          <div className='text-muted-foreground flex flex-wrap items-center justify-between gap-2 text-xs'>
            <span>
              {filtered.length > 0 && `Showing ${visible.length.toLocaleString()} of ${filtered.length.toLocaleString()} · `}
              {filtered.length > 0 ? 'the' : 'The'} workspace lists its latest {entries.length.toLocaleString()} {entries.length === 1 ? 'entry' : 'entries'} here
              (up to 100)
            </span>
            {filtered.length > LEDGER_PAGE && (
              <Button variant='ghost' size='sm' onClick={() => setShowAll((value) => !value)}>
                {showAll ? `Show latest ${LEDGER_PAGE}` : `Show all ${filtered.length.toLocaleString()}`}
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
