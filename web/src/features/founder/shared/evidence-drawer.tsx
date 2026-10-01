'use client';

import { useQuery } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useWide } from '@/features/queue/use-wide';
import { founderPanelStore } from '@/features/founder/agent/store';
import { useFounderSession } from '@/features/founder/shell/founder-session';
import { founderKeys } from '@/lib/founder/api';
import type { MetricReceipt } from '@/lib/founder/types';
import { useEvidence } from './evidence-state';
import { formatDateTime, humanize } from './format';
import { QueryBoundary, DataStateChip } from './state-fallbacks';

/**
 * The shared evidence drawer (PRD §5.4): receipt id, query digest, data state, source watermarks, coverage and the
 * stored rows, plus "Explain" which hands the receipt to Founder Rafii. The shell mounts one addressed by
 * `?evidence=`; a page may mount its own controlled instance (`open`, `onOpenChange`, `receiptId`, `record`) when it
 * already has the row on screen. A side sheet on wide screens, a bottom sheet on phones. Identifiers are shown as
 * the server masked them; nothing is cached here.
 */

/** Receipts were written camelCase and some rows read back snake_case; one accessor reads either. */
function field(receipt: MetricReceipt, camel: string, snake: string): unknown {
  return receipt[camel] ?? receipt[snake];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asRows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((row): row is Record<string, unknown> => Boolean(asRecord(row))) : [];
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return '';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

const MAX_ROWS = 20;

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className='flex flex-col gap-0.5'>
      <dt className='rafii-eyebrow'>{label}</dt>
      <dd className='text-foreground text-sm break-words'>{children}</dd>
    </div>
  );
}

/** The record a page already had on screen, as a masked key/value list (objects are summarised, ids kept opaque). */
function RecordView({ record }: { record: Record<string, unknown> }) {
  const entries = Object.entries(record).filter(([, value]) => value !== null && value !== undefined);
  return (
    <section className='flex flex-col gap-2' aria-label='Related record'>
      <h3 className='rafii-eyebrow'>Related record</h3>
      <dl className='grid grid-cols-1 gap-2 sm:grid-cols-2'>
        {entries.map(([key, value]) => (
          <Row key={key} label={humanize(key)}>
            <span className={typeof value === 'object' ? 'font-mono text-xs' : undefined}>{cell(value)}</span>
          </Row>
        ))}
      </dl>
    </section>
  );
}

function ReceiptView({ receipt }: { receipt: MetricReceipt }) {
  const dataState = String(field(receipt, 'dataState', 'data_state') ?? 'measured');
  const watermarks = asRecord(field(receipt, 'sourceWatermarks', 'source_watermarks'));
  const coverage = asRecord(field(receipt, 'coverage', 'coverage'));
  const versions = asRecord(field(receipt, 'metricVersions', 'metric_versions'));
  const query = asRecord(field(receipt, 'normalizedQuery', 'normalized_query'));
  const rows = asRows(field(receipt, 'rows', 'result_rows'));
  const columns = rows.length ? Object.keys(rows[0]).slice(0, 6) : [];
  return (
    <>
      <DataStateChip state={dataState} className='self-start' />
      <dl className='grid grid-cols-1 gap-3 sm:grid-cols-2'>
        <Row label='Receipt'>
          <span className='font-mono text-xs'>{receipt.id}</span>
        </Row>
        <Row label='Query digest'>
          <span className='font-mono text-xs'>{cell(field(receipt, 'queryDigest', 'query_digest')) || 'Not recorded'}</span>
        </Row>
        <Row label='Calculated'>{formatDateTime(cell(field(receipt, 'calculatedAt', 'calculated_at')))}</Row>
        <Row label='Execution'>{humanize(field(receipt, 'executionState', 'execution_state'))}</Row>
        <Row label='Rows'>{cell(field(receipt, 'rowCount', 'row_count')) || String(rows.length)}</Row>
        {versions && <Row label='Metric versions'>{Object.entries(versions).map(([key, value]) => `${key} ${cell(value)}`).join(' · ') || 'Not recorded'}</Row>}
      </dl>
      {watermarks && Object.keys(watermarks).length > 0 && (
        <section className='flex flex-col gap-2' aria-label='Source watermarks'>
          <h3 className='rafii-eyebrow'>Source watermarks</h3>
          <ul className='flex flex-col gap-1 text-sm'>
            {Object.entries(watermarks).map(([source, at]) => (
              <li key={source} className='flex items-center justify-between gap-3'>
                <span className='truncate'>{humanize(source)}</span>
                <span className='text-muted-foreground shrink-0 text-xs'>{formatDateTime(cell(at))}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {coverage && (
        <section className='flex flex-col gap-2' aria-label='Coverage'>
          <h3 className='rafii-eyebrow'>Coverage</h3>
          <ul className='text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs'>
            {Object.entries(coverage).map(([key, value]) => (
              <li key={key}>
                {humanize(key)}: <span className='text-foreground tabular-nums'>{cell(value)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {query && (
        <section className='flex flex-col gap-2' aria-label='Normalized query'>
          <h3 className='rafii-eyebrow'>Query</h3>
          <pre className='rafii-quiet overflow-x-auto rounded-[var(--rafii-radius-control)] p-3 font-mono text-[11px] leading-relaxed'>{JSON.stringify(query, null, 2)}</pre>
        </section>
      )}
      <section className='flex flex-col gap-2' aria-label='Stored rows'>
        <h3 className='rafii-eyebrow'>Stored rows</h3>
        {rows.length === 0 ? (
          <p className='text-muted-foreground text-sm'>No rows were stored with this receipt.</p>
        ) : (
          // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a horizontally scrolling table must be reachable by keyboard (WCAG 2.1.1)
          <div className='overflow-x-auto' role='region' aria-label='Receipt rows' tabIndex={0}>
            <table className='w-full text-left text-xs'>
              <caption className='sr-only'>
                First {Math.min(rows.length, MAX_ROWS)} of {rows.length} rows; identifiers are masked by the server.
              </caption>
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th key={column} scope='col' className='text-muted-foreground pr-3 pb-1 font-medium'>
                      {humanize(column)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, MAX_ROWS).map((row, index) => (
                  <tr key={index} className='border-foreground/8 border-t'>
                    {columns.map((column) => (
                      <td key={column} className='py-1 pr-3 align-top tabular-nums'>
                        {cell(row[column])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length > MAX_ROWS && <p className='text-muted-foreground pt-2 text-xs'>{rows.length - MAX_ROWS} more rows are in the receipt; ask Rafii for the full breakdown.</p>}
          </div>
        )}
      </section>
    </>
  );
}

export interface EvidenceDrawerProps {
  /** Controlled use by a page; omitted, the drawer follows `?evidence=`. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  receiptId?: string | null;
  /** A row the page already shows, listed beside (or instead of) the receipt. */
  record?: Record<string, unknown> | null;
}

export function EvidenceDrawer({ open: controlledOpen, onOpenChange, receiptId: controlledReceipt, record }: EvidenceDrawerProps = {}) {
  const url = useEvidence();
  const controlled = controlledOpen !== undefined;
  const receiptId = controlled ? (controlledReceipt ?? null) : url.receiptId;
  const open = controlled ? Boolean(controlledOpen) : Boolean(url.receiptId);
  const close = () => (controlled ? onOpenChange?.(false) : url.close());
  const { api, environment } = useFounderSession();
  const wide = useWide();
  const query = useQuery({
    queryKey: founderKeys.receipt(environment ?? 'unknown', receiptId ?? ''),
    queryFn: ({ signal }) => api.receipt(receiptId as string, { signal }),
    enabled: open && Boolean(receiptId),
    retry: false,
    staleTime: 5 * 60_000
  });
  const explain = () => {
    const subject = receiptId ? `receipt ${receiptId}` : record && typeof record.id === 'string' ? `record ${record.id}` : 'this evidence';
    founderPanelStore.ask(`Explain ${subject}: what it measured, its coverage and what it cannot tell me.`);
  };
  return (
    <Sheet open={open} onOpenChange={(next) => !next && close()}>
      <SheetContent
        side={wide ? 'right' : 'bottom'}
        aria-label='Evidence'
        className={wide ? 'rafii-elevated gap-0 p-0 shadow-none data-[side=right]:w-full data-[side=right]:rounded-l-[var(--rafii-radius-dialog)] data-[side=right]:border-l-0 data-[side=right]:sm:max-w-lg' : 'rafii-elevated max-h-[85dvh] gap-0 rounded-t-3xl p-0 shadow-none'}
      >
        <SheetHeader className='pr-14'>
          <SheetTitle>Evidence</SheetTitle>
          <SheetDescription>The receipt behind this value: what was queried, from which sources, and how complete it is.</SheetDescription>
        </SheetHeader>
        <div className='flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 pb-[calc(1rem+env(safe-area-inset-bottom))]'>
          <Button type='button' variant='glass' size='sm' onClick={explain} className='w-fit gap-1.5'>
            <Icons.sparkles className='size-3.5' aria-hidden /> Explain with Rafii
          </Button>
          {record && <RecordView record={record} />}
          {receiptId ? (
            <QueryBoundary query={query} loadingTitle='Reading the receipt…'>
              {(envelope) => <ReceiptView receipt={envelope.data.receipt} />}
            </QueryBoundary>
          ) : (
            !record && <p className='text-muted-foreground text-sm'>No receipt is attached to this item.</p>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
