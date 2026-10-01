'use client';

import type { UseQueryResult } from '@tanstack/react-query';
import { StateMessage } from '@/components/rafii';
import { failureOf } from '../customers/kit/api';
import { headlineRow, tileFromResult, type TileData, type TileInput } from '../customers/kit/metric';
import { RetryAction, periodLabelFor } from '../customers/kit/page-frame';
import { MetricTile } from '../customers/kit/shared';
import type { MetricResult } from '../customers/kit/types';

/**
 * `MetricTileFromQuery` plus the definition's note: a Demo MRR row carries `measures.catalogLabel` ("Candidate v2
 * catalog (not active)"), shown under the value so fictional catalog prices never read as live pricing.
 */
export function NotedMetricTile({ query, input, onAsk }: { query: Pick<UseQueryResult<MetricResult>, 'data' | 'error' | 'isPending' | 'refetch'>; input: TileInput; onAsk?: (tile: TileData) => void }) {
  if (query.isPending) return <StateMessage kind='loading' title={`Loading ${input.label}…`} />;
  if (query.error) {
    const failure = failureOf(query.error);
    return <StateMessage kind={failure.status === 403 ? 'permission' : 'error'} title={input.label} description={failure.message} action={<RetryAction onRetry={() => void query.refetch()} />} />;
  }
  const tile = tileFromResult(query.data, input);
  const row = headlineRow(query.data, input.id);
  const measures = row?.measures as { catalogLabel?: unknown } | undefined;
  const note = typeof measures?.catalogLabel === 'string' ? measures.catalogLabel : null;
  // A partial or stale row still carries the server's value; the tile's coverage dot and state say how complete it is.
  const value = row && typeof row.value === 'number' && (row.dataState === 'partial' || row.dataState === 'stale') ? row.value : tile.value;
  return (
    <MetricTile
      id={tile.id}
      label={tile.label}
      value={value}
      unit={tile.unit}
      currency={tile.currency}
      delta={tile.delta}
      deltaPeriod={tile.deltaPeriod}
      sparkline={tile.sparkline}
      dataState={tile.dataState}
      coverage={tile.coverage}
      href={tile.href ?? null}
      receiptId={tile.receiptId}
      collectingSince={tile.collectingSince}
      periodLabel={periodLabelFor(input.period)}
      definition={tile.reason ? `Not measured: ${tile.reason.replaceAll('_', ' ')}` : null}
      note={note}
      onAsk={onAsk ? () => onAsk(tile) : undefined}
    />
  );
}
