'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { parseAsInteger, parseAsString, parseAsStringLiteral, useQueryState, useQueryStates } from 'nuqs';
import { Icons } from '@/components/icons';
import { ActiveFilters, FilterPanel, FilterSelect, SegmentedControl, StateMessage, Workbar, type SegmentOption } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { DataTableColumnHeader } from '@/components/ui/table/data-table-column-header';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useDataTable } from '@/hooks/use-data-table';
import { useDebounce } from '@/hooks/use-debounce';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { getSortingStateParser } from '@/lib/parsers';
import { useFounderMode, useRecords } from './kit/api';
import { useAsk } from './kit/ask';
import { count, recordLabel, stateLabel, whenDate } from './kit/format';
import { DataStateChip, FounderPage } from './kit/page-frame';
import { DEMO_SORTS, RECORDS_PAGE_SIZE, pageCount } from './kit/records';
import { RecordsTable } from './kit/records-table';
import type { RecordRow } from './kit/types';
import { CustomerSheet, RiskFlagChips } from './customer-sheet';
import { SAVED_VIEWS, SAVED_VIEW_IDS, observedPlans, paymentRiskAvailable, savedView, serverStatusForView, type SavedViewId } from './query';
import { riskFlags, type RiskFlag } from './risk-flags';

/**
 * Customers (PRD §5.3, §9): a server-searched table over `POST /workspace/{mode}/query` in 50-row pages, saved
 * views as a segmented control, Live/Demo-aware filters, and the Customer 360 sheet opened by `?record=`. Search,
 * status, plan, page and sort live in the address so a view can be shared; the record id is pushed so Back closes
 * the sheet. Risk flags are observed rules on the returned fields (§7.4) and never a score.
 */
interface CustomerRow extends RecordRow {
  computedFlags: RiskFlag[];
  linkedWorkspaces: RecordRow[];
}

const SORTABLE: Record<string, string> = { name: 'name', status: 'status', plan: 'plan', createdAt: 'createdAt' };

function columns(sortable: boolean, onOpen: (row: RecordRow) => void): ColumnDef<RecordRow>[] {
  return [
    {
      id: 'name',
      accessorFn: (row) => recordLabel(row),
      enableSorting: sortable,
      header: ({ column }) => <DataTableColumnHeader column={column} title='Customer' />,
      cell: ({ row }) => (
        <div className='flex min-w-44 flex-col'>
          <span className='text-foreground font-medium'>{recordLabel(row.original)}</span>
          <span className='text-muted-foreground truncate text-xs'>{typeof row.original.company === 'string' && row.original.company !== recordLabel(row.original) ? row.original.company : typeof row.original.email === 'string' ? row.original.email : row.original.id}</span>
        </div>
      )
    },
    {
      id: 'plan',
      accessorFn: (row) => row.plan,
      enableSorting: sortable,
      header: ({ column }) => <DataTableColumnHeader column={column} title='Plan' />,
      cell: ({ row }) => <StatusChip icon={null}>{stateLabel(row.original.plan)}</StatusChip>
    },
    {
      id: 'workspaces',
      enableSorting: false,
      header: 'Workspaces',
      cell: ({ row }) => {
        const linked = (row.original as CustomerRow).linkedWorkspaces;
        const ids = Array.isArray(row.original.workspaceIds) ? row.original.workspaceIds.length : linked.length;
        return (
          <span className='flex min-w-0 flex-col'>
            <span className='tabular-nums'>{count(ids)}</span>
            {linked.length > 0 && <span className='text-muted-foreground truncate text-xs'>{linked.map((workspace) => recordLabel(workspace)).join(', ')}</span>}
          </span>
        );
      }
    },
    {
      id: 'status',
      accessorFn: (row) => row.status,
      enableSorting: sortable,
      header: ({ column }) => <DataTableColumnHeader column={column} title='Status' />,
      cell: ({ row }) => <StatusChip status={typeof row.original.status === 'string' && ['past_due', 'unpaid', 'grace'].includes(row.original.status) ? 'warning' : 'neutral'}>{stateLabel(row.original.status)}</StatusChip>
    },
    {
      id: 'flags',
      enableSorting: false,
      header: 'Flags',
      cell: ({ row }) => <RiskFlagChips flags={(row.original as CustomerRow).computedFlags} />
    },
    {
      id: 'createdAt',
      accessorFn: (row) => row.createdAt,
      enableSorting: sortable,
      header: ({ column }) => <DataTableColumnHeader column={column} title='Since' />,
      cell: ({ row }) => <span className='whitespace-nowrap tabular-nums'>{whenDate(row.original.createdAt)}</span>
    },
    {
      id: 'open',
      enableSorting: false,
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
          Open <Icons.chevronRight />
        </Button>
      )
    }
  ];
}

export function CustomersView() {
  const mode = useFounderMode();
  const ask = useAsk();
  const [filters, setFilters] = useQueryStates(
    {
      q: parseAsString.withDefault(''),
      status: parseAsString.withDefault('all'),
      plan: parseAsString.withDefault('all'),
      view: parseAsStringLiteral(SAVED_VIEW_IDS).withDefault('all')
    },
    { history: 'replace', clearOnDefault: true }
  );
  const [page, setPage] = useQueryState('page', parseAsInteger.withDefault(1).withOptions({ history: 'replace', clearOnDefault: true }));
  const [record, setRecord] = useQueryState('record', parseAsString.withOptions({ history: 'push', clearOnDefault: true }));
  const columnIds = useMemo(() => new Set(Object.keys(SORTABLE)), []);
  const [sorting] = useQueryState('sort', getSortingStateParser<RecordRow>(columnIds).withDefault([]));
  const search = useDebounce(filters.q, 250);
  const view = savedView(filters.view);

  const open = useCallback((row: RecordRow) => void setRecord(row.id), [setRecord]);
  const update = useCallback(
    (next: Partial<typeof filters>) => {
      void setFilters(next);
      void setPage(1);
    },
    [setFilters, setPage]
  );
  const clear = useCallback(() => update({ q: '', status: 'all', plan: 'all', view: 'all' }), [update]);

  // The source lists its statuses with every answer; a payment-risk view resolves to one of them on the next
  // request, and `keepPreviousData` keeps the last page on screen while that refinement loads.
  const [knownStatuses, setKnownStatuses] = useState<string[]>([]);
  const serverStatus = serverStatusForView(view, knownStatuses, filters.status);
  // Founder Rafii sees the open account (an opaque id) and the view the list is narrowed to, never the rows (CONTRACTS §6).
  useFounderPageContext({ section: 'customers', selectedEntity: record ? { type: 'customer', id: record } : null, filters: { view: filters.view, status: serverStatus, ...(search ? { q: search } : {}) } });
  const sort = mode === 'demo' && sorting[0] && DEMO_SORTS.has(SORTABLE[sorting[0].id] ?? '') ? SORTABLE[sorting[0].id] : undefined;
  const query = useRecords({
    collection: 'customers',
    search,
    status: serverStatus,
    page,
    recordId: '',
    plan: mode === 'demo' ? filters.plan : undefined,
    sort,
    direction: sorting[0]?.desc ? 'desc' : 'asc'
  });
  const statuses = query.data?.data.statuses ?? knownStatuses;
  useEffect(() => {
    const listed = query.data?.data.statuses;
    if (listed && listed.join('|') !== knownStatuses.join('|')) setKnownStatuses(listed);
  }, [query.data, knownStatuses]);
  const active = query;
  const data = active.data?.data;
  const workspaces = useMemo(() => data?.workspaces ?? [], [data?.workspaces]);

  const rows = useMemo<CustomerRow[]>(() => {
    const all = (data?.rows ?? []).map((row) => {
      const linked = workspaces.filter((workspace) => Array.isArray(row.workspaceIds) && (row.workspaceIds as unknown[]).includes(workspace.id));
      return { ...row, computedFlags: riskFlags(row, workspaces), linkedWorkspaces: linked } as CustomerRow;
    });
    return view.mode === 'flag' && view.flag ? all.filter((row) => row.computedFlags.some((flag) => flag.id === view.flag)) : all;
  }, [data?.rows, workspaces, view]);

  const tableColumns = useMemo(() => columns(mode === 'demo', open), [mode, open]);
  const { table } = useDataTable<RecordRow>({
    data: rows,
    columns: tableColumns,
    pageCount: pageCount(data?.total, data?.pageSize ?? RECORDS_PAGE_SIZE),
    initialState: { pagination: { pageSize: RECORDS_PAGE_SIZE, pageIndex: 0 } },
    getRowId: (row) => row.id,
    enableSorting: mode === 'demo',
    clearOnDefault: true
  });

  const activeFilterCount = (filters.status !== 'all' ? 1 : 0) + (filters.plan !== 'all' ? 1 : 0);
  const filtered = Boolean(search) || activeFilterCount > 0 || view.mode !== 'all';
  const segments: SegmentOption<SavedViewId>[] = SAVED_VIEWS.map((item) => ({
    value: item.id,
    label: item.label,
    title: item.description,
    disabled: item.mode === 'status' && query.data !== undefined && !paymentRiskAvailable(statuses)
  }));
  const plans = mode === 'demo' ? observedPlans(data?.rows ?? []) : [];

  return (
    <FounderPage
      eyebrow='Customers'
      title='Customers'
      description='Find an account and follow its workspace, billing, usage and support in one place. The server searches every record; this page shows 50 at a time.'
      actions={
        <Button variant='glass' size='control' onClick={() => ask({ prompt: 'Which customers need attention right now, and why?', filters: { view: filters.view, status: serverStatus, search } })}>
          <Icons.sparkles /> Ask Rafii
        </Button>
      }
    >
      <Workbar
        search={filters.q}
        onSearch={(value) => update({ q: value })}
        searchPlaceholder='Search names, companies or record ids'
        searchLabel='Search customers'
        tabs={<SegmentedControl options={segments} value={filters.view} onChange={(value) => update({ view: value })} label='Saved views' size='sm' widths='content' />}
        filters={
          <FilterPanel count={activeFilterCount} onClear={() => update({ status: 'all', plan: 'all' })} eyebrow='Customers'>
            <FilterSelect label='Status' value={filters.status} onChange={(value) => update({ status: value })} options={[{ value: 'all', label: 'All statuses' }, ...statuses.map((status) => ({ value: status, label: stateLabel(status) }))]} />
            {mode === 'demo' ? (
              <FilterSelect label='Plan' value={filters.plan} onChange={(value) => update({ plan: value })} options={[{ value: 'all', label: 'All paid plans' }, ...plans.map((plan) => ({ value: plan, label: plan }))]} />
            ) : (
              <p className='text-muted-foreground text-xs'>Plan and risk filters for Live arrive with the 054 views (P1). Status and search are served today.</p>
            )}
          </FilterPanel>
        }
        summary={<ActiveFilters count={activeFilterCount} summary={[filters.status !== 'all' ? `status ${stateLabel(filters.status)}` : null, filters.plan !== 'all' ? `plan ${filters.plan}` : null].filter(Boolean).join(' · ')} onClear={() => update({ status: 'all', plan: 'all' })} />}
        count={
          data ? (
            <span className='flex items-center gap-2'>
              {count(rows.length)} of {count(data.total)}
              <DataStateChip state={active.data?.dataState} />
            </span>
          ) : null
        }
      />

      {view.mode === 'flag' && data && <StateMessage kind='partial' layout='inline' title={`${view.label} applies to this page of ${count(data.rows.length)} records`} description='Risk rules run on the fields the server returned for the current page; a whole-population risk filter lands with the 054 views (P1).' />}
      {view.mode === 'status' && query.data && !paymentRiskAvailable(statuses) && <StateMessage kind='empty' layout='inline' title='This source reports no payment-risk status' description='No customer is past due, unpaid or ending in the loaded statuses.' />}

      <RecordsTable
        table={table}
        status={{ isPending: active.isPending, isFetching: active.isFetching, error: active.error, total: data?.total, pageSize: data?.pageSize ?? RECORDS_PAGE_SIZE, refetch: active.refetch }}
        label='Customers'
        caption={`Customers · ${mode === 'demo' ? 'fictional sample data' : 'Live records'}`}
        onOpen={open}
        filtered={filtered}
        onClear={clear}
      />

      <CustomerSheet recordId={record} open={Boolean(record)} onOpenChange={(next) => !next && void setRecord(null)} />
    </FounderPage>
  );
}
