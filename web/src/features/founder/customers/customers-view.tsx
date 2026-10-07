'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { parseAsInteger, parseAsString, useQueryState, useQueryStates } from 'nuqs';
import { Icons } from '@/components/icons';
import { ActiveFilters, FilterPanel, FilterSelect, SegmentedControl, StateMessage, Workbar, type SegmentOption } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { DataTableColumnHeader } from '@/components/ui/table/data-table-column-header';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useDataTable } from '@/hooks/use-data-table';
import { useDebounce } from '@/hooks/use-debounce';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { getSortingStateParser } from '@/lib/parsers';
import { useFounderMode, useRecords } from './kit/api';
import { useAsk } from './kit/ask';
import { count, recordLabel, stateLabel, whenDate } from './kit/format';
import { DataStateChip, FounderPage, Panel } from './kit/page-frame';
import { DEMO_SORTS, RECORDS_PAGE_SIZE, pageCount } from './kit/records';
import { RecordsTable } from './kit/records-table';
import { useTabState } from './kit/tabs';
import type { RecordRow } from './kit/types';
import { CustomerSheet } from './customer-sheet';
import { RISK_VIEWS, flagIndex, joinFlags, resolveSavedView, riskView, type FlagIndex, type SavedViewId } from './customer-risk';
import { observedPlans } from './query';
import { FlagCoverage, RiskChips, RiskRulesList, RiskViewPanel } from './risk-views';
import { useCustomerRisk } from './use-customer-risk';
import { WorkspacesTab } from './workspaces-tab';

/**
 * Customers (PRD §5.3, §7.4, §9; CONTRACTS §8.C). Three tabs: the customer list (server-searched, 50 per page) with
 * the saved views High value · High AI cost · Quota ≥80% · Inactive 30d · Payment risk · At-risk; the workspace list
 * (`?tab=workspaces`, where `/control/workspaces` lands); and the risk rules with every flagged workspace. Flags come
 * from `GET /customers/risk`: versioned rules the server evaluated over the whole population, each with trigger,
 * evidence and since, shown side by side and never folded into a score. Search, status, plan, view, page and tab live
 * in the address; the Customer 360 sheet opens by `?record=` (pushed, so Back closes it).
 */

type RiskQuery = ReturnType<typeof useCustomerRisk>;

interface CustomerRow extends RecordRow {
  linkedWorkspaces: RecordRow[];
}

interface ListFilters {
  q: string;
  status: string;
  plan: string;
  view: string;
}

const SORTABLE: Record<string, string> = { name: 'name', status: 'status', plan: 'plan', createdAt: 'createdAt' };
const ATTENTION_STATUSES = new Set(['past_due', 'unpaid', 'grace']);

function customerColumns(sortable: boolean, renderFlags: (row: RecordRow) => ReactNode, onOpen: (row: RecordRow) => void): ColumnDef<RecordRow>[] {
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
      cell: ({ row }) => <StatusChip status={typeof row.original.status === 'string' && ATTENTION_STATUSES.has(row.original.status) ? 'warning' : 'neutral'}>{stateLabel(row.original.status)}</StatusChip>
    },
    {
      id: 'flags',
      enableSorting: false,
      header: 'Flags',
      cell: ({ row }) => renderFlags(row.original)
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
          data-customer-open={row.original.id}
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

/** Customers › List: the server-searched table, or one saved view's workspaces from the risk route. */
function CustomerList({ filters, search, page, update, clear, risk, index, onOpenCustomer }: { filters: ListFilters; search: string; page: number; update: (next: Partial<ListFilters>) => void; clear: () => void; risk: RiskQuery; index: FlagIndex; onOpenCustomer: (customerId: string) => void }) {
  const mode = useFounderMode();
  const view = resolveSavedView(filters.view);
  const saved = view === 'all' ? null : riskView(view);
  const viewRisk = useCustomerRisk(saved ? saved.id : null);
  const columnIds = useMemo(() => new Set(Object.keys(SORTABLE)), []);
  const [sorting] = useQueryState('sort', getSortingStateParser<RecordRow>(columnIds).withDefault([]));
  const sort = mode === 'demo' && sorting[0] && DEMO_SORTS.has(SORTABLE[sorting[0].id] ?? '') ? SORTABLE[sorting[0].id] : undefined;
  const query = useRecords(
    saved
      ? null
      : {
          collection: 'customers',
          search,
          status: filters.status,
          page,
          recordId: '',
          plan: mode === 'demo' ? filters.plan : undefined,
          sort,
          direction: sorting[0]?.desc ? 'desc' : 'asc'
        }
  );
  const data = query.data?.data;
  const [knownStatuses, setKnownStatuses] = useState<string[]>([]);
  useEffect(() => {
    const listed = data?.statuses;
    if (listed && listed.join('|') !== knownStatuses.join('|')) setKnownStatuses(listed);
  }, [data?.statuses, knownStatuses]);
  const statuses = data?.statuses ?? knownStatuses;
  const workspaces = useMemo(() => data?.workspaces ?? [], [data?.workspaces]);
  const rows = useMemo<CustomerRow[]>(
    () =>
      (data?.rows ?? []).map((row) => ({
        ...row,
        linkedWorkspaces: workspaces.filter((workspace) => Array.isArray(row.workspaceIds) && (row.workspaceIds as unknown[]).includes(workspace.id))
      })),
    [data?.rows, workspaces]
  );
  const openRow = useCallback((row: RecordRow) => onOpenCustomer(row.id), [onOpenCustomer]);
  // Query observers return a fresh wrapper on each render. Keep cell components stable when only the drawer URL changes.
  const flagsAllowed = risk.allowed;
  const flagsPending = risk.query.isPending;
  const flagsError = risk.query.error;
  const flagsData = risk.query.data;
  const renderFlags = useCallback((row: RecordRow) => {
    if (!flagsAllowed || flagsError || !flagsData || flagsData.dataState === 'unavailable') return <span className='text-muted-foreground text-xs'>{flagsPending && flagsAllowed ? 'Checking…' : '—'}</span>;
    if (flagsPending) return <span className='text-muted-foreground text-xs'>Checking…</span>;
    return <RiskChips flags={joinFlags(row.workspaceIds, index)} empty={flagsData.data.truncated ? `Not among the first ${count(flagsData.data.limit)} flagged` : 'No flags'} />;
  }, [flagsAllowed, flagsPending, flagsError, flagsData, index]);
  const tableColumns = useMemo(() => customerColumns(mode === 'demo', renderFlags, openRow), [mode, renderFlags, openRow]);
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
  const segments: SegmentOption<SavedViewId>[] = [{ value: 'all', label: 'All', title: 'Every customer the source returns' }, ...RISK_VIEWS.map((item) => ({ value: item.id, label: item.label, title: item.id === 'at_risk' ? 'A hypothesis: inactive and a payment or connection risk' : undefined }))];
  const plans = mode === 'demo' ? observedPlans(data?.rows ?? []) : [];
  const viewTabs = <SegmentedControl options={segments} value={view} onChange={(value) => update({ view: value })} label='Saved views' size='sm' widths='content' />;

  if (saved) {
    return (
      <div className='flex min-w-0 flex-col gap-4'>
        <Workbar tabs={viewTabs} />
        <RiskViewPanel risk={viewRisk} rule={saved.rule} label={saved.label} onOpenCustomer={onOpenCustomer} />
      </div>
    );
  }
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <Workbar
        tabs={viewTabs}
        search={filters.q}
        onSearch={(value) => update({ q: value })}
        searchPlaceholder='Search names, companies, workspace or record ids'
        searchLabel='Search customers'
        filters={
          <FilterPanel count={activeFilterCount} onClear={() => update({ status: 'all', plan: 'all' })} eyebrow='Customers'>
            <FilterSelect label='Status' value={filters.status} onChange={(value) => update({ status: value })} options={[{ value: 'all', label: 'All statuses' }, ...statuses.map((status) => ({ value: status, label: stateLabel(status) }))]} />
            {mode === 'demo' ? (
              <FilterSelect label='Plan' value={filters.plan} onChange={(value) => update({ plan: value })} options={[{ value: 'all', label: 'All paid plans' }, ...plans.map((plan) => ({ value: plan, label: plan }))]} />
            ) : (
              <p className='text-muted-foreground text-xs'>Live narrows by status and search; the saved views above cover value, cost, quota, activity and payment risk.</p>
            )}
          </FilterPanel>
        }
        summary={<ActiveFilters count={activeFilterCount} summary={[filters.status !== 'all' ? `status ${stateLabel(filters.status)}` : null, filters.plan !== 'all' ? `plan ${filters.plan}` : null].filter(Boolean).join(' · ')} onClear={() => update({ status: 'all', plan: 'all' })} />}
        count={
          data ? (
            <span className='flex items-center gap-2'>
              {count(rows.length)} of {count(data.total)}
              <DataStateChip state={query.data?.dataState} />
            </span>
          ) : null
        }
      />
      <FlagCoverage risk={risk} />
      <RecordsTable
        table={table}
        status={{ isPending: query.isPending, isFetching: query.isFetching, error: query.error, total: data?.total, pageSize: data?.pageSize ?? RECORDS_PAGE_SIZE, refetch: query.refetch }}
        label='Customers'
        caption={`Customers · ${mode === 'demo' ? 'fictional sample data' : 'Live records'}`}
        onOpen={openRow}
        filtered={Boolean(search) || activeFilterCount > 0}
        onClear={clear}
      />
    </div>
  );
}

/** Customers › Risk: every flagged workspace (most flags first) and the versioned rules behind the chips. */
function RiskTab({ risk, onOpenCustomer }: { risk: RiskQuery; onOpenCustomer: (customerId: string) => void }) {
  const data = risk.query.data?.data;
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <Panel title='Flagged workspaces' description='Every workspace with at least one observed flag, most flags first, at most 200. Open one to see its customer.'>
        <RiskViewPanel risk={risk} rule={null} label='Flagged workspaces' onOpenCustomer={onOpenCustomer} />
      </Panel>
      <Panel title={`Risk rules${data ? ` ${data.rulesVersion}` : ''}`} description='Each flag is one explainable rule with its trigger, evidence and since. Several flags sit side by side; they are never combined into a score.'>
        {!risk.allowed ? (
          <StateMessage kind='permission' layout='inline' title='Rules need customer access' description='The risk rules are read with the customers and workspaces read permissions.' />
        ) : risk.query.isPending ? (
          <StateMessage kind='loading' layout='inline' title='Loading risk rules…' />
        ) : data ? (
          <RiskRulesList rules={data.rules} />
        ) : (
          <StateMessage kind='error' layout='inline' title="Couldn't load the risk rules" description='Retry from the flagged list above.' />
        )}
      </Panel>
    </div>
  );
}

export function CustomersView() {
  const ask = useAsk();
  const [tab, setTab] = useTabState('customers', 'list');
  const [filters, setFilters] = useQueryStates(
    { q: parseAsString.withDefault(''), status: parseAsString.withDefault('all'), plan: parseAsString.withDefault('all'), view: parseAsString.withDefault('all') },
    { history: 'replace', clearOnDefault: true }
  );
  const [page, setPage] = useQueryState('page', parseAsInteger.withDefault(1).withOptions({ history: 'replace', clearOnDefault: true }));
  const [, setSort] = useQueryState('sort', parseAsString.withOptions({ history: 'replace' }));
  const [record, setRecord] = useQueryState('record', parseAsString.withOptions({ history: 'push', clearOnDefault: true }));
  const search = useDebounce(filters.q, 250);
  const view = resolveSavedView(filters.view);

  // One flagged-workspace answer feeds the chips on both tables and the risk tab.
  const risk = useCustomerRisk('flagged');
  const index = useMemo(() => flagIndex(risk.query.data?.data.rows), [risk.query.data]);

  const openCustomer = useCallback((id: string) => void setRecord(id), [setRecord]);
  const update = useCallback(
    (next: Partial<ListFilters>) => {
      void setFilters(next);
      void setPage(1);
    },
    [setFilters, setPage]
  );
  const clear = useCallback(() => update({ q: '', status: 'all', plan: 'all', view: 'all' }), [update]);
  const switchTab = useCallback(
    (next: string) => {
      // Statuses, search and paging belong to one collection; a new tab starts clean.
      void setFilters({ q: '', status: 'all', plan: 'all', view: 'all' });
      void setPage(1);
      void setSort(null);
      setTab(next);
    },
    [setFilters, setPage, setSort, setTab]
  );

  // Founder Rafii sees the tab, the view and the open account (an opaque id), never the rows (CONTRACTS §6).
  useFounderPageContext({
    section: 'customers',
    selectedEntity: record ? { type: 'customer', id: record } : null,
    filters: { tab, ...(tab === 'list' ? { view } : {}), ...(filters.status !== 'all' ? { status: filters.status } : {}), ...(search ? { q: search } : {}) }
  });

  const askPrompt =
    view === 'all' || tab !== 'list'
      ? 'Which customers need attention right now, and why? Use the risk flags and say which rules could not be evaluated.'
      : `Explain the "${riskView(view).label}" saved view: who is in it, what evidence put them there, and what I should do first.`;

  return (
    <FounderPage
      eyebrow='Customers'
      title='Customers'
      description='Find an account and follow its workspaces, billing, usage and support in one place. The server searches every record and evaluates every risk rule; this page shows the results.'
      actions={
        <Button variant='glass' size='control' onClick={() => ask({ prompt: askPrompt, filters: { tab, view } })}>
          <Icons.sparkles /> Ask Rafii
        </Button>
      }
    >
      <Tabs value={tab} onValueChange={(value) => switchTab(String(value))}>
        <TabsList variant='line' className='w-max'>
          <TabsTrigger value='list'>Customers</TabsTrigger>
          <TabsTrigger value='workspaces'>Workspaces</TabsTrigger>
          <TabsTrigger value='risk'>Risk</TabsTrigger>
        </TabsList>
        <TabsContent value='list' className='pt-4'>
          <CustomerList filters={filters} search={search} page={page} update={update} clear={clear} risk={risk} index={index} onOpenCustomer={openCustomer} />
        </TabsContent>
        <TabsContent value='workspaces' className='pt-4'>
          <WorkspacesTab filters={filters} search={search} page={page} update={update} risk={risk} index={index} onOpenCustomer={openCustomer} />
        </TabsContent>
        <TabsContent value='risk' className='pt-4'>
          <RiskTab risk={risk} onOpenCustomer={openCustomer} />
        </TabsContent>
      </Tabs>

      <CustomerSheet recordId={record} open={Boolean(record)} onOpenChange={(next) => !next && void setRecord(null)} />
    </FounderPage>
  );
}
