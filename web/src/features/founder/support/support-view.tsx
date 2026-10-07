'use client';

import { SupportInbox } from './support-inbox';
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
import { DataStateChip, FounderPage, MetricChartCard, MetricTileFromQuery, Panel, PanelGrid, QueryState, TileGrid } from '../customers/kit/page-frame';
import { RECORDS_PAGE_SIZE, pageCount } from '../customers/kit/records';
import { RecordsTable } from '../customers/kit/records-table';
import { TabAnchor, useSectionTab } from '../customers/kit/tabs';
import type { MetricRow, RecordRow } from '../customers/kit/types';
import { REQUEST_KIND_LABELS, ageBandItems, byDimension, formatAge, measure, openRequestsRow, opsSpec, ticketSource } from '../operations/ops-model';

/**
 * Support (PRD §5.3, §7.1 M31–M32, §9; CONTRACTS §8.D): the inbox of account data requests with its aging histogram and
 * kinds (`support_aging`, receipted), and the request list from the workspace query (`tickets` → `business_requests`
 * in Live). There is no ticket system: the server reports the support-ticket source as not collected until decision D7
 * picks one, and the page says so rather than drawing response-time charts from nothing.
 */
const PERIOD = '30d' as const;

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

/** The support-ticket source as the server reports it; "not chosen (D7)" until a ticket source exists. */
function TicketSourceState({ rows, demo }: { rows: readonly MetricRow[]; demo: boolean }) {
  const tickets = ticketSource(rows);
  if (tickets?.collected) return <StateMessage kind='success' layout='inline' title='A ticket source is connected' description='Support conversations are collected; response and resolution times follow from it.' />;
  return (
    <StateMessage
      kind='unsupported'
      title='In-app support'
      description={
        demo
          ? 'Demo shows sandbox requests. Open Live to see customer tickets and reply.'
          : 'Tickets and replies stay in their customer workspace. The inbox shows available response and resolution times. Business-hour targets and satisfaction surveys have not been configured.'
      }
    />
  );
}

export function SupportView() {
  const mode = useFounderMode();
  const ask = useAsk();
  const evidence = useEvidenceDrawer();
  const [filters, setFilters] = useQueryStates({ q: parseAsString.withDefault(''), status: parseAsString.withDefault('all') }, { history: 'replace', clearOnDefault: true });
  const [page, setPage] = useQueryState('page', parseAsInteger.withDefault(1).withOptions({ history: 'replace', clearOnDefault: true }));
  const search = useDebounce(filters.q, 250);
  const tab = useSectionTab('support');
  useFounderPageContext({ section: 'support', period: PERIOD, filters: { status: filters.status, q: search } });
  const update = useCallback(
    (next: Partial<typeof filters>) => {
      void setFilters(next);
      void setPage(1);
    },
    [setFilters, setPage]
  );

  const openRequests = useTileMetric(opsSpec('supportOpen', PERIOD));
  const aging = useMetric(opsSpec('supportAging', PERIOD));
  const kinds = useMetric(opsSpec('supportKinds', PERIOD));
  const sources = useMetric(opsSpec('supportSources', PERIOD));
  const oldest = measure(openRequestsRow(openRequests.data?.rows), 'oldestSeconds');
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
      <TileGrid>
        <MetricTileFromQuery query={openRequests} input={{ id: 'support_aging', label: 'Open data requests', period: PERIOD }} onAsk={() => ask({ prompt: 'How many data requests are open, how old is the oldest, and which kinds are waiting?', chart: 'support_aging', period: PERIOD })} />
      </TileGrid>

      <PanelGrid>
        <TabAnchor section='support' tab='aging' active={tab}>
          <MetricChartCard query={aging} id='support_aging' title='Backlog aging' subtitle='Open data requests by how long they have waited' period={PERIOD} unavailableDescription='Aging comes from the data-request projection; no open request was measured.'>
            {(result) => (
              <div className='flex flex-col gap-2'>
                <CategoryBars items={ageBandItems(result.rows)} unit='count' emptyTitle='No open request is waiting' />
                {oldest !== null && <p className='text-muted-foreground text-xs'>The oldest open request has waited {formatAge(oldest)}.</p>}
              </div>
            )}
          </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='support' tab='status' active={tab}>
          <MetricChartCard query={kinds} id='support_aging' title='Open requests by kind' subtitle='Requests still waiting: export, deletion, diagnostics' period={PERIOD} unavailableDescription='No open request was measured by kind.'>
            {(result) => <CategoryBars items={byDimension(result.rows, 'kind', REQUEST_KIND_LABELS)} unit='count' emptyTitle='No open request is waiting' />}
          </MetricChartCard>
        </TabAnchor>
      </PanelGrid>

      <Panel title='Support sources' description='Where support work is collected from. Missing sources are said, never drawn as zero.' actions={sources.data && <DataStateChip state={sources.data.dataState} />}>
        <QueryState query={sources} label='support sources'>
          {(result) => <TicketSourceState rows={result.rows} demo={mode === 'demo'} />}
        </QueryState>
      </Panel>

      <TabAnchor section='support' tab='inbox' active={tab}>
        <Panel title='Inbox' description='Data requests, server-searched, 50 per page. A row opens as evidence; the customer is on Customers.' actions={requests.data && <DataStateChip state={requests.data.dataState} />}>
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
      <SupportInbox />
      {evidence.drawer}
    </FounderPage>
  );
}
