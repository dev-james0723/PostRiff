'use client';

import { useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Icons } from '@/components/icons';
import { ActiveFilters, FilterPanel, FilterSelect, Workbar } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useDataTable } from '@/hooks/use-data-table';
import { useFounderMode, useRecords } from './kit/api';
import { count, recordLabel, stateLabel, whenDate } from './kit/format';
import { DataStateChip } from './kit/page-frame';
import { RECORDS_PAGE_SIZE, pageCount } from './kit/records';
import { RecordsTable } from './kit/records-table';
import type { RecordRow } from './kit/types';
import { joinFlags, type FlagIndex } from './customer-risk';
import { FlagCell, FlagCoverage } from './risk-views';
import type { useCustomerRisk } from './use-customer-risk';

/**
 * Customers › Workspaces (`?tab=workspaces`, where `/control/workspaces` now lands): the server-searched workspace
 * records in 50-row pages with the risk flags the server evaluated for each, and the owner's Customer 360 one click away.
 * Search, status and page live in the address (owned by the page, reset when the tab changes) so the view can be shared.
 */

type RiskQuery = ReturnType<typeof useCustomerRisk>;

const ATTENTION_STATUSES = new Set(['past_due', 'unpaid', 'grace', 'incomplete']);

function text(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

function columns(risk: RiskQuery, index: FlagIndex, onOpenCustomer: (customerId: string) => void): ColumnDef<RecordRow>[] {
  return [
    {
      id: 'name',
      accessorFn: (row) => recordLabel(row),
      enableSorting: false,
      header: 'Workspace',
      cell: ({ row }) => (
        <div className='flex min-w-44 flex-col'>
          <span className='text-foreground font-medium'>{text(row.original.name) ?? 'Unnamed workspace'}</span>
          <span className='text-muted-foreground truncate text-xs'>{row.original.id}</span>
        </div>
      )
    },
    {
      id: 'plan',
      enableSorting: false,
      header: 'Plan',
      cell: ({ row }) => <StatusChip icon={null}>{stateLabel(row.original.plan)}</StatusChip>
    },
    {
      id: 'status',
      enableSorting: false,
      header: 'Status',
      cell: ({ row }) => <StatusChip status={ATTENTION_STATUSES.has(text(row.original.status) ?? '') ? 'warning' : 'neutral'}>{stateLabel(row.original.status)}</StatusChip>
    },
    {
      id: 'members',
      enableSorting: false,
      header: 'Members',
      cell: ({ row }) => <span className='tabular-nums'>{typeof row.original.memberCount === 'number' ? count(row.original.memberCount) : '—'}</span>
    },
    {
      id: 'flags',
      enableSorting: false,
      header: 'Flags',
      cell: ({ row }) => <FlagCell risk={risk} flags={joinFlags(row.original.id, index)} />
    },
    {
      id: 'createdAt',
      enableSorting: false,
      header: 'Created',
      cell: ({ row }) => <span className='whitespace-nowrap tabular-nums'>{whenDate(row.original.createdAt)}</span>
    },
    {
      id: 'open',
      enableSorting: false,
      header: () => <span className='sr-only'>Open</span>,
      cell: ({ row }) => {
        const owner = text(row.original.ownerId);
        return owner ? (
          <Button
            variant='quiet'
            size='sm'
            aria-label={`Open the owner of ${recordLabel(row.original)}`}
            onClick={(event) => {
              event.stopPropagation();
              onOpenCustomer(owner);
            }}
          >
            Owner <Icons.chevronRight />
          </Button>
        ) : (
          <span className='text-muted-foreground text-xs'>No owner</span>
        );
      }
    }
  ];
}

export interface WorkspaceFilters {
  q: string;
  status: string;
}

export function WorkspacesTab({ filters, search, page, update, risk, index, onOpenCustomer }: { filters: WorkspaceFilters; search: string; page: number; update: (next: Partial<WorkspaceFilters>) => void; risk: RiskQuery; index: FlagIndex; onOpenCustomer: (customerId: string) => void }) {
  const mode = useFounderMode();
  const query = useRecords({ collection: 'workspaces', search, status: filters.status, page, recordId: '' });
  const data = query.data?.data;
  const [knownStatuses, setKnownStatuses] = useState<string[]>([]);
  useEffect(() => {
    const listed = data?.statuses;
    if (listed && listed.join('|') !== knownStatuses.join('|')) setKnownStatuses(listed);
  }, [data?.statuses, knownStatuses]);
  const statuses = data?.statuses ?? knownStatuses;
  const rows = useMemo(() => data?.rows ?? [], [data?.rows]);
  const tableColumns = useMemo(() => columns(risk, index, onOpenCustomer), [risk, index, onOpenCustomer]);
  const { table } = useDataTable<RecordRow>({
    data: rows,
    columns: tableColumns,
    pageCount: pageCount(data?.total, data?.pageSize ?? RECORDS_PAGE_SIZE),
    initialState: { pagination: { pageSize: RECORDS_PAGE_SIZE, pageIndex: 0 } },
    getRowId: (row) => row.id,
    enableSorting: false,
    clearOnDefault: true
  });
  const activeFilterCount = filters.status !== 'all' ? 1 : 0;
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <Workbar
        search={filters.q}
        onSearch={(value) => update({ q: value })}
        searchPlaceholder='Search workspace names, plans or ids'
        searchLabel='Search workspaces'
        filters={
          <FilterPanel count={activeFilterCount} onClear={() => update({ status: 'all' })} eyebrow='Workspaces'>
            <FilterSelect label='Status' value={filters.status} onChange={(value) => update({ status: value })} options={[{ value: 'all', label: 'All statuses' }, ...statuses.map((status) => ({ value: status, label: stateLabel(status) }))]} />
          </FilterPanel>
        }
        summary={<ActiveFilters count={activeFilterCount} summary={filters.status !== 'all' ? `status ${stateLabel(filters.status)}` : ''} onClear={() => update({ status: 'all' })} />}
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
        label='Workspaces'
        caption={`Workspaces · ${mode === 'demo' ? 'fictional sample data' : 'Live records'}`}
        filtered={Boolean(search) || activeFilterCount > 0}
        onClear={() => update({ q: '', status: 'all' })}
      />
    </div>
  );
}
