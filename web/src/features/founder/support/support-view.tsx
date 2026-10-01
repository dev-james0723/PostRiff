'use client';

import { useCallback, useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { parseAsInteger, parseAsString, useQueryState, useQueryStates } from 'nuqs';
import { Icons } from '@/components/icons';
import { ActiveFilters, FilterPanel, FilterSelect, StateMessage, Workbar } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useDataTable } from '@/hooks/use-data-table';
import { useDebounce } from '@/hooks/use-debounce';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { useFounderMode, useMetric, useRecords, useTileMetric } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { CategoryBars } from '../customers/kit/charts';
import { useEvidenceDrawer } from '../customers/kit/evidence';
import { count, recordLabel, stateLabel, whenDate } from '../customers/kit/format';
import { categoriesFromRows } from '../customers/kit/metric';
import { DataStateChip, FounderPage, MetricChartCard, MetricTileFromQuery, Panel, PanelGrid, TileGrid } from '../customers/kit/page-frame';
import { RECORDS_PAGE_SIZE, pageCount } from '../customers/kit/records';
import { RecordsTable } from '../customers/kit/records-table';
import { TabAnchor, useSectionTab } from '../customers/kit/tabs';
import type { RecordRow } from '../customers/kit/types';

/**
 * Support (PRD §5.3, §9): the data-request backlog and its aging from the receipt path, and the request list from
 * the workspace query (`tickets` → `business_requests` in Live). There is no ticket system; the page says so
 * rather than drawing response-time charts from nothing.
 */
function columns(onOpen: (row: RecordRow) => void): ColumnDef<RecordRow>[] {
  return [
    { id: 'title', header: 'Request', cell: ({ row }) => <span className='text-foreground font-medium'>{recordLabel(row.original)}</span> },
    { id: 'kind', header: 'Kind', cell: ({ row }) => stateLabel(row.original.kind) },
    { id: 'status', header: 'Status', cell: ({ row }) => <StatusChip status={['open', 'requested', 'pending'].includes(String(row.original.status)) ? 'warning' : 'neutral'}>{stateLabel(row.original.status)}</StatusChip> },
    { id: 'workspace', header: 'Workspace', cell: ({ row }) => <span className='font-mono text-xs'>{typeof row.original.workspaceId === 'string' ? `…${row.original.workspaceId.slice(-8)}` : 'Not recorded'}</span> },
    { id: 'at', header: 'Opened', cell: ({ row }) => <span className='whitespace-nowrap'>{whenDate(row.original.at ?? row.original.requestedAt)}</span> },
    {
      id: 'open',
      header: () => <span className='sr-only'>Open</span>,
      cell: ({ row }) => (
        <Button
          variant='quiet'
          size='sm'
          aria-label={`Open ${recordLabel(row.original)}`}
          onClick={(event) => {
            event.stopPropagation();
            onOpen(row.original);
          }}
        >
          Evidence <Icons.chevronRight />
        </Button>
      )
    }
  ];
}

export function SupportView() {
  const mode = useFounderMode();
  const ask = useAsk();
  const evidence = useEvidenceDrawer();
  const [filters, setFilters] = useQueryStates({ q: parseAsString.withDefault(''), status: parseAsString.withDefault('all') }, { history: 'replace', clearOnDefault: true });
  const [page, setPage] = useQueryState('page', parseAsInteger.withDefault(1).withOptions({ history: 'replace', clearOnDefault: true }));
  const search = useDebounce(filters.q, 250);
  const tab = useSectionTab('support');
  useFounderPageContext({ section: 'support', period: '30d', filters: { status: filters.status, q: search } });
  const update = useCallback(
    (next: Partial<typeof filters>) => {
      void setFilters(next);
      void setPage(1);
    },
    [setFilters, setPage]
  );

  const backlog = useTileMetric({ id: 'data_requests_backlog', period: '30d' });
  const aging = useMetric({ id: 'data_requests_backlog', period: '90d', groupBy: ['age_band'] });
  const byKind = useMetric({ id: 'data_requests_backlog', period: '90d', groupBy: ['kind'] });
  const requests = useRecords({ collection: 'tickets', search, status: filters.status, page, recordId: '' });
  const data = requests.data?.data;
  const rows = useMemo(() => data?.rows ?? [], [data?.rows]);
  const open = useCallback((row: RecordRow) => evidence.open({ receiptId: requests.data?.receiptIds?.[0] ?? null, record: row }), [evidence, requests.data?.receiptIds]);
  const tableColumns = useMemo(() => columns(open), [open]);
  const { table } = useDataTable<RecordRow>({ data: rows, columns: tableColumns, pageCount: pageCount(data?.total, data?.pageSize ?? RECORDS_PAGE_SIZE), initialState: { pagination: { pageSize: RECORDS_PAGE_SIZE, pageIndex: 0 } }, getRowId: (row) => row.id, enableSorting: false, clearOnDefault: true });
  const statuses = data?.statuses ?? [];
  const activeFilterCount = filters.status !== 'all' ? 1 : 0;

  return (
    <FounderPage
      eyebrow='Support'
      title='Support'
      description='Account requests waiting on you, how long they have waited, and the customer behind each one.'
      actions={
        <Button variant='glass' size='control' onClick={() => ask({ prompt: 'Which support requests have waited longest, and which customers are behind them?', filters: { status: filters.status, search } })}>
          <Icons.sparkles /> Ask Rafii
        </Button>
      }
    >
      <StateMessage kind='partial' layout='inline' title='No ticket system is connected' description={mode === 'demo' ? 'Demo shows sandbox requests. Live shows account data requests (export, deletion) only; customer conversations and replies need an approved support connection.' : 'Live shows account data requests (export, deletion) from pr_data_requests. Response and resolution times appear once a ticket source exists.'} />

      <TileGrid>
        <MetricTileFromQuery query={backlog} input={{ id: 'data_requests_backlog', label: 'Open data requests', period: '30d' }} onAsk={() => ask({ prompt: 'How many data requests are open, and which are overdue?', chart: 'data_requests_backlog', period: '30d' })} />
      </TileGrid>

      <PanelGrid>
        <TabAnchor section='support' tab='aging' active={tab}>
          <MetricChartCard query={aging} id='data_requests_backlog' title='Backlog aging' subtitle='Open requests by age band' period='90d' unavailableDescription='Aging comes from business_data_requests_v2; no open request was measured.'>
            {(result) => <CategoryBars items={categoriesFromRows(result.rows, 'age_band')} unit={result.rows[0]?.unit ?? 'count'} />}
          </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='support' tab='status' active={tab}>
          <MetricChartCard query={byKind} id='data_requests_backlog' title='Open requests by kind' subtitle='Requests still waiting, by kind (export, deletion…)' period='90d'>
            {(result) => <CategoryBars items={categoriesFromRows(result.rows, 'kind')} unit={result.rows[0]?.unit ?? 'count'} />}
          </MetricChartCard>
        </TabAnchor>
      </PanelGrid>

      <TabAnchor section='support' tab='inbox' active={tab}>
      <Panel title='Requests' description='Server-searched, 50 per page. A row opens as evidence; the customer is on Customers.' actions={requests.data && <DataStateChip state={requests.data.dataState} />}>
        <Workbar
          search={filters.q}
          onSearch={(value) => update({ q: value })}
          searchPlaceholder='Search titles or record ids'
          searchLabel='Search requests'
          filters={
            <FilterPanel count={activeFilterCount} onClear={() => update({ status: 'all' })} eyebrow='Requests'>
              <FilterSelect label='Status' value={filters.status} onChange={(value) => update({ status: value })} options={[{ value: 'all', label: 'All statuses' }, ...statuses.map((status) => ({ value: status, label: stateLabel(status) }))]} />
            </FilterPanel>
          }
          summary={<ActiveFilters count={activeFilterCount} summary={`status ${stateLabel(filters.status)}`} onClear={() => update({ status: 'all' })} />}
          count={data ? `${count(rows.length)} of ${count(data.total)}` : null}
        />
        <RecordsTable table={table} status={{ isPending: requests.isPending, isFetching: requests.isFetching, error: requests.error, total: data?.total, pageSize: data?.pageSize ?? RECORDS_PAGE_SIZE, refetch: requests.refetch }} label='Requests' caption={`Requests · ${mode === 'demo' ? 'fictional sample data' : 'Live records'}`} onOpen={open} filtered={Boolean(search) || activeFilterCount > 0} onClear={() => update({ q: '', status: 'all' })} />
      </Panel>
      </TabAnchor>
      {evidence.drawer}
    </FounderPage>
  );
}
