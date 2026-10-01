'use client';

import { StateMessage } from '@/components/rafii';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { whenDateTime } from '../customers/kit/format';
import { SimpleTable } from '../customers/kit/simple-table';
import type { MetricRow } from '../customers/kit/types';
import {
  CONNECTION_STATES,
  burnBySlo,
  byDimension,
  cellKey,
  connectionMatrix,
  dimension,
  formatAge,
  formatBurn,
  formatCount,
  formatMs,
  formatRatio,
  humanize,
  queueGroups,
  routeHealth,
  shownValue,
  sourceTone,
  sourceViews,
  type ConnectionState,
  type QueueCounterView,
  type RouteHealth
} from './ops-model';

/**
 * The bodies of the Operations panels (CONTRACTS §8.D). Each renders server rows through `ops-model`: values are the
 * server's, a row it did not measure reads "Unavailable", and wide tables scroll inside their own `relative` box so the
 * page never scrolls sideways.
 */

function stateTone(state: string | null | undefined): 'success' | 'warning' | 'neutral' {
  if (state === 'measured' || state === 'synthetic') return 'success';
  if (state === 'partial' || state === 'stale') return 'warning';
  return 'neutral';
}

function StateChip({ row }: { row: Pick<MetricRow, 'dataState' | 'reason'> | null }) {
  if (!row) return <span className='text-muted-foreground'>—</span>;
  return (
    <StatusChip status={stateTone(row.dataState)} tone={stateTone(row.dataState) === 'success' ? 'neutral' : 'attention'} title={row.reason ? humanize(row.reason) : undefined}>
      {humanize(row.dataState)}
      {row.reason && row.dataState !== 'measured' ? ` · ${humanize(row.reason)}` : ''}
    </StatusChip>
  );
}

function Value({ text, shown }: { text: string; shown: boolean }) {
  return <span className={cn('tabular-nums', !shown && 'text-muted-foreground italic')}>{text}</span>;
}

/* ---------- source health ---------- */

export function SourceHealthItems({ rows, compact = false }: { rows: readonly MetricRow[]; compact?: boolean }) {
  const sources = sourceViews(rows);
  if (sources.length === 0) return <StateMessage kind='empty' layout='inline' title='No source probed yet' description='The founder cron writes one row per source each minute; none has been recorded in this environment.' />;
  return (
    <ul className={cn('grid gap-2', compact ? 'sm:grid-cols-2' : 'sm:grid-cols-2 xl:grid-cols-3')} aria-label='Source health'>
      {sources.map((source) => (
        <li key={source.source} className='rafii-quiet flex items-start justify-between gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2'>
          <span className='flex min-w-0 flex-col'>
            <span className='text-foreground text-sm font-medium'>{source.label}</span>
            <span className='text-muted-foreground text-xs'>
              Last good {whenDateTime(source.lastGoodAt)}
              {source.reason ? ` · ${humanize(source.reason)}` : ''}
            </span>
          </span>
          <StatusChip status={sourceTone(source.state)} tone={sourceTone(source.state) === 'success' ? 'neutral' : 'attention'}>
            {humanize(source.state)}
          </StatusChip>
        </li>
      ))}
    </ul>
  );
}

/** Every probed source with its state, last good read, age and reason (Advanced → Data health). */
export function SourceHealthTable({ rows }: { rows: readonly MetricRow[] }) {
  const sources = sourceViews(rows);
  return (
    <SimpleTable
      className='relative'
      rows={sources}
      rowKey={(source) => source.source}
      caption='Every probed source: state, last good read, age and reason'
      emptyTitle='No source probed yet'
      emptyDescription='The founder cron writes one row per source each minute; none has been recorded in this environment.'
      columns={[
        { key: 'source', label: 'Source', render: (source) => <span className='text-foreground font-medium'>{source.label}</span> },
        { key: 'state', label: 'State', render: (source) => <StatusChip status={sourceTone(source.state)} tone={sourceTone(source.state) === 'success' ? 'neutral' : 'attention'}>{humanize(source.state)}</StatusChip> },
        { key: 'last', label: 'Last good', render: (source) => <span className='whitespace-nowrap'>{whenDateTime(source.lastGoodAt)}</span> },
        { key: 'age', label: 'Age', align: 'right', render: (source) => <Value text={formatAge(source.ageSeconds)} shown={source.ageSeconds !== null} /> },
        { key: 'reason', label: 'Reason', render: (source) => (source.reason ? humanize(source.reason) : <span className='text-muted-foreground'>—</span>) },
        { key: 'id', label: 'Id', render: (source) => <span className='font-mono text-xs'>{source.source}</span> }
      ]}
    />
  );
}

/* ---------- API health ---------- */

export function RouteHealthTable({ errors, latency }: { errors: readonly MetricRow[]; latency: readonly MetricRow[] }) {
  const routes = routeHealth(errors, latency);
  return (
    <SimpleTable<RouteHealth>
      className='relative'
      rows={routes}
      rowKey={(route) => route.route}
      caption='Error rate and latency by route pattern'
      emptyTitle='No route recorded in this period'
      emptyDescription='Every request records its route pattern with identifiers masked; nothing was recorded for this window.'
      columns={[
        { key: 'route', label: 'Route pattern', render: (route) => <span className='font-mono text-xs break-all'>{route.route}</span> },
        { key: 'requests', label: 'Requests', align: 'right', render: (route) => <Value text={formatCount(route.requests)} shown={route.requests !== null} /> },
        { key: 'errors', label: '5xx rate', align: 'right', render: (route) => <Value text={formatRatio(route.errorRate)} shown={route.errorRate !== null} /> },
        { key: 'p50', label: 'p50', align: 'right', render: (route) => <Value text={formatMs(route.p50)} shown={route.p50 !== null} /> },
        { key: 'p95', label: 'p95', align: 'right', render: (route) => <Value text={formatMs(route.p95, route.p95OpenEnded)} shown={route.p95 !== null} /> },
        { key: 'state', label: 'State', render: (route) => <StateChip row={route.errorRow ?? route.p95Row} /> }
      ]}
    />
  );
}

export function SloBurnView({ rows }: { rows: readonly MetricRow[] }) {
  const slos = burnBySlo(rows);
  if (slos.length === 0) return <StateMessage kind='empty' layout='inline' title='No burn rate reported' />;
  return (
    <div className='flex flex-col gap-4'>
      {slos.map((slo) => (
        <section key={slo.slo} aria-label={`${slo.label} burn rate`} className='flex flex-col gap-2'>
          <div className='flex flex-wrap items-center gap-2'>
            <h3 className='text-foreground text-sm font-medium'>{slo.label}</h3>
            <StatusChip icon='info' tone='attention'>{slo.sloLabel ?? 'proposed SLO, not approved'}</StatusChip>
          </div>
          {slo.unavailable ? (
            <StateMessage kind='unsupported' layout='inline' title={`${slo.label} burn is not measured`} description={humanize(slo.unavailable.reason ?? 'not collected')} />
          ) : (
            <>
              <dl className='grid grid-cols-2 gap-2 sm:grid-cols-4'>
                {slo.windows.map((window) => (
                  <div key={window.window} className='rafii-quiet flex min-w-0 flex-col gap-0.5 rounded-[var(--rafii-radius-control)] px-3 py-2'>
                    <dt className='text-muted-foreground text-xs'>{window.window} window</dt>
                    <dd className='text-foreground text-lg font-medium tabular-nums'>
                      <Value text={formatBurn(window.value)} shown={window.value !== null} />
                    </dd>
                    <dd className='text-muted-foreground text-xs'>
                      {window.total !== null ? `${formatCount(window.bad)} bad of ${formatCount(window.total)}` : humanize(window.reason)}
                      {window.dataState !== 'measured' && window.reason && window.total !== null ? ` · ${humanize(window.reason)}` : ''}
                    </dd>
                  </div>
                ))}
              </dl>
              <ul className='flex flex-wrap gap-2' aria-label={`${slo.label} alert pairs`}>
                {slo.pairs.map((pair) => (
                  <li key={pair.pair}>
                    <StatusChip status={pair.alerting ? 'danger' : 'neutral'} tone={pair.alerting ? 'attention' : 'neutral'}>
                      {pair.pair}: {pair.alerting ? 'burning' : 'not alerting'}
                      {pair.threshold !== null ? ` (over ${formatBurn(pair.threshold)} in both)` : ''}
                    </StatusChip>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      ))}
    </div>
  );
}

/* ---------- jobs ---------- */

export function QueueTable({ rows }: { rows: readonly MetricRow[] }) {
  const groups = queueGroups(rows);
  const counters: Array<QueueCounterView & { queueLabel: string }> = groups.flatMap((group) => group.counters.map((counter) => ({ ...counter, queueLabel: group.label })));
  return (
    <SimpleTable
      className='relative'
      rows={counters}
      rowKey={(counter) => counter.counter}
      caption='Operational counters per minute snapshot: peak over the period and the latest reading'
      emptyTitle='No snapshot in this period'
      columns={[
        { key: 'queue', label: 'Queue', render: (counter) => counter.queueLabel },
        { key: 'counter', label: 'Signal', render: (counter) => <span className='text-foreground'>{counter.label}</span> },
        { key: 'peak', label: 'Peak', align: 'right', render: (counter) => <Value text={formatCount(counter.peak)} shown={counter.peak !== null} /> },
        { key: 'latest', label: 'Latest', align: 'right', render: (counter) => <Value text={formatCount(counter.latest)} shown={counter.latest !== null} /> },
        { key: 'at', label: 'Latest at', render: (counter) => <span className='whitespace-nowrap'>{whenDateTime(counter.latestAt)}</span> }
      ]}
    />
  );
}

/* ---------- connections ---------- */

const STATE_LABEL: Record<ConnectionState, string> = { ok: 'ok', expiring: 'expiring', expired: 'expired', blocked: 'blocked' };

function stateStatus(state: ConnectionState | null): 'success' | 'warning' | 'danger' | 'neutral' {
  if (state === 'blocked' || state === 'expired') return 'danger';
  if (state === 'expiring') return 'warning';
  if (state === 'ok') return 'success';
  return 'neutral';
}

export function ConnectionMatrixTable({ rows }: { rows: readonly MetricRow[] }) {
  const matrix = connectionMatrix(rows);
  if (matrix.providers.length === 0) return <StateMessage kind='empty' layout='inline' title='No connection in the projection' description='The hourly refresh found no connected channel in a customer workspace.' />;
  return (
    <div className='flex flex-col gap-2'>
      <div className='rafii-quiet relative overflow-x-auto rounded-[var(--rafii-radius-card)]'>
        <table className='w-full min-w-max border-collapse text-sm'>
          <caption className='sr-only'>Connections by provider and capability: how many are ok, expiring, expired or blocked</caption>
          <thead>
            <tr>
              <th scope='col' className='text-muted-foreground px-3 py-2 text-left text-xs font-medium whitespace-nowrap'>
                Provider
              </th>
              {matrix.capabilities.map((capability) => (
                <th key={capability} scope='col' className='text-muted-foreground px-3 py-2 text-left text-xs font-medium whitespace-nowrap'>
                  {humanize(capability)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.providers.map((provider) => (
              <tr key={provider} className='border-t'>
                <th scope='row' className='text-foreground px-3 py-2 text-left font-medium whitespace-nowrap'>
                  {humanize(provider)}
                </th>
                {matrix.capabilities.map((capability) => {
                  const cell = matrix.cells[cellKey(provider, capability)];
                  return (
                    <td key={capability} className='px-3 py-2 align-top'>
                      {cell ? (
                        <span className='flex flex-col items-start gap-1'>
                          <StatusChip status={stateStatus(cell.worst)} tone={cell.worst === 'ok' ? 'neutral' : 'attention'}>
                            {cell.worst ? STATE_LABEL[cell.worst] : 'none'}
                          </StatusChip>
                          <span className='text-muted-foreground text-xs whitespace-nowrap'>
                            {CONNECTION_STATES.filter((state) => cell.counts[state] !== undefined)
                              .map((state) => `${formatCount(cell.counts[state])} ${STATE_LABEL[state]}`)
                              .join(' · ')}
                          </span>
                        </span>
                      ) : (
                        <>
                          <span aria-hidden className='text-muted-foreground'>
                            —
                          </span>
                          <span className='sr-only'>No connection</span>
                        </>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className='text-muted-foreground text-xs'>Expiring means the token expires within 7 days; blocked means revoked, scopes missing or identity unverified. Reconnect stays in each customer workspace.</p>
    </div>
  );
}

/* ---------- publishing, notifications ---------- */

export function PublishOutcomesTable({ rows }: { rows: readonly MetricRow[] }) {
  const items = byDimension(rows, 'platform');
  return (
    <SimpleTable
      className='relative'
      rows={items}
      rowKey={(item) => item.key}
      caption='Publish outcomes by platform and status'
      emptyTitle='No publish outcome in this period'
      columns={[
        { key: 'platform', label: 'Platform', render: (item) => item.label },
        { key: 'status', label: 'Outcome', render: (item) => <StatusChip icon={null}>{humanize(dimension(item.row, 'status'))}</StatusChip> },
        { key: 'count', label: 'Publications', align: 'right', render: (item) => <Value text={formatCount(item.value)} shown={item.value !== null} /> }
      ]}
    />
  );
}

export function DeliveryTable({ rows }: { rows: readonly MetricRow[] }) {
  const items = byDimension(rows, 'status');
  return (
    <SimpleTable
      className='relative'
      rows={items}
      rowKey={(item) => item.key}
      caption='Notification deliveries by channel and status'
      emptyTitle='No delivery in this period'
      columns={[
        { key: 'channel', label: 'Channel', render: (item) => humanize(dimension(item.row, 'channel')) },
        { key: 'status', label: 'Status', render: (item) => <StatusChip icon={null}>{item.label}</StatusChip> },
        { key: 'count', label: 'Deliveries', align: 'right', render: (item) => <Value text={formatCount(item.value)} shown={item.value !== null} /> }
      ]}
    />
  );
}

/** The value of a single-row answer (no dimension), as the server sent it. */
export function headline(rows: readonly MetricRow[] | undefined): number | null {
  const row = (rows ?? []).find((candidate) => !candidate.dimensions || Object.keys(candidate.dimensions).length === 0);
  return shownValue(row);
}
