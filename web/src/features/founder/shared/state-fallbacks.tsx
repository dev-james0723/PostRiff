'use client';

import type { ReactNode } from 'react';
import { StateMessage, type StateKind } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { describeFounderError, isFounderApiError } from '@/lib/founder/errors';
import type { DataState } from '@/lib/founder/types';
import { formatDateShort, formatRelative } from './format';

/**
 * The founder admin's state grammar (CONTRACTS §6): the shared `StateMessage` with fixed founder copy for empty,
 * loading, error, permission, stale and partial states. An unavailable value is the word, never a zero, and a metric
 * that is not yet instrumented says since when it has been collecting.
 */

export const UNAVAILABLE = 'Unavailable';

export type FallbackKind = 'loading' | 'error' | 'empty' | 'permission' | 'stale' | 'partial' | 'unavailable';

const DEFAULT_COPY: Record<FallbackKind, { kind: StateKind; title: string; description?: string }> = {
  loading: { kind: 'loading', title: 'Reading records…' },
  error: { kind: 'error', title: 'Couldn’t read this', description: 'Live values have not been substituted.' },
  empty: { kind: 'empty', title: 'Nothing recorded yet' },
  permission: { kind: 'permission', title: 'Not available to this operator', description: 'This view needs a capability your founder session does not carry.' },
  stale: { kind: 'stale', title: 'Source data is stale', description: 'These values are preserved evidence, not a measured change.' },
  partial: { kind: 'partial', title: 'Some sources are missing', description: 'What is shown is measured; the rest is marked unknown.' },
  unavailable: { kind: 'unsupported', title: 'Source not qualified', description: 'This source has not been connected or qualified for this environment.' }
};

export interface StateFallbackProps {
  kind: FallbackKind;
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  onRetry?: () => void;
  layout?: 'panel' | 'inline';
  className?: string;
}

export function StateFallback({ kind, title, description, action, onRetry, layout = 'panel', className }: StateFallbackProps) {
  const copy = DEFAULT_COPY[kind];
  const retry = onRetry ? (
    <Button type='button' variant='glass' size='sm' onClick={onRetry}>
      Retry
    </Button>
  ) : null;
  return <StateMessage kind={copy.kind} layout={layout} title={title ?? copy.title} description={description ?? copy.description} action={action ?? retry ?? undefined} className={className} />;
}

/** The slice of a React Query result the boundary reads, so any query (or a hand-built object) fits. */
export interface BoundaryQuery<T> {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => unknown;
}

export interface QueryBoundaryProps<T> {
  query: BoundaryQuery<T>;
  children: (data: T) => ReactNode;
  loadingTitle?: ReactNode;
  /** When the data counts as empty; the empty state replaces the children. */
  isEmpty?: (data: T) => boolean;
  emptyTitle?: ReactNode;
  emptyDescription?: ReactNode;
  emptyAction?: ReactNode;
  layout?: 'panel' | 'inline';
  className?: string;
}

/** Loading, error (permission on 403, stale on a stale source), empty, then the data — with the founder copy. */
export function QueryBoundary<T>({ query, children, loadingTitle, isEmpty, emptyTitle, emptyDescription, emptyAction, layout = 'panel', className }: QueryBoundaryProps<T>) {
  if (query.isPending) return <StateFallback kind='loading' title={loadingTitle} layout={layout} className={className} />;
  if (query.isError) {
    const permission = isFounderApiError(query.error) && query.error.status === 403;
    return <StateFallback kind={permission ? 'permission' : 'error'} description={permission ? undefined : describeFounderError(query.error)} onRetry={permission ? undefined : () => void query.refetch()} layout={layout} className={className} />;
  }
  if (query.data === undefined) return <StateFallback kind='empty' title={emptyTitle} description={emptyDescription} action={emptyAction} layout={layout} className={className} />;
  if (isEmpty?.(query.data)) return <StateFallback kind='empty' title={emptyTitle} description={emptyDescription} action={emptyAction} layout={layout} className={className} />;
  return <>{children(query.data)}</>;
}

/** The word in place of a number, with the reason for assistive tech. */
export function Unavailable({ reason, className }: { reason?: string; className?: string }) {
  return (
    <span className={className}>
      {UNAVAILABLE}
      {reason && <span className='sr-only'> — {reason}</span>}
    </span>
  );
}

/** A metric instrumented from a date with nothing measured yet. */
export function CollectingSince({ since, className }: { since?: string | null; className?: string }) {
  return <span className={className}>{since ? `Collecting since ${formatDateShort(since)}` : 'Not yet collected'}</span>;
}

const DATA_STATE: Record<DataState, { label: string; status: 'success' | 'warning' | 'info' | 'neutral' | 'danger' }> = {
  measured: { label: 'Measured', status: 'success' },
  partial: { label: 'Partial', status: 'warning' },
  stale: { label: 'Stale', status: 'warning' },
  unavailable: { label: 'Unavailable', status: 'danger' },
  collecting: { label: 'Collecting', status: 'info' },
  // Demo answers (QueryService.demo_data, founder agent turns in Demo mode) are marked synthetic by the server.
  synthetic: { label: 'Demo data', status: 'neutral' },
  suppressed: { label: 'Suppressed', status: 'neutral' },
  demo: { label: 'Demo', status: 'neutral' }
};

/** Monochrome state chip for an envelope or a tile: the data state word, optionally with its watermark. */
export function DataStateChip({ state, asOf, className }: { state: DataState | string; asOf?: string | null; className?: string }) {
  const meta = DATA_STATE[state as DataState] ?? { label: String(state), status: 'neutral' as const };
  return (
    <StatusChip status={meta.status} className={className} title={asOf ? `As of ${formatRelative(asOf)}` : undefined}>
      {meta.label}
      {asOf ? ` · ${formatRelative(asOf)}` : ''}
    </StatusChip>
  );
}
