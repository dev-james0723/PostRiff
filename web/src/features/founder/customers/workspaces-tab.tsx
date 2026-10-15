'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Icons } from '@/components/icons';
import { ActiveFilters, FilterPanel, FilterSelect, Workbar } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useDataTable } from '@/hooks/use-data-table';
import { failureOf, useFounderMode, useRecords, useRenameLiveWorkspace } from './kit/api';
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

function columns(
  risk: RiskQuery,
  index: FlagIndex,
  onOpenCustomer: (customerId: string) => void,
  onRenameWorkspace: (workspace: RecordRow) => void,
  canRenameLive: boolean
): ColumnDef<RecordRow>[] {
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
      header: () => <span className='sr-only'>Actions</span>,
      cell: ({ row }) => {
        const owner = text(row.original.ownerId);
        const renameAllowed = canRenameLive && row.original.renameAllowed === true;
        return (
          <div className='flex items-center justify-end gap-1'>
            {renameAllowed && (
              <Button
                variant='quiet'
                size='sm'
                aria-label={`Rename approved test workspace ${recordLabel(row.original)}`}
                onClick={(event) => {
                  event.stopPropagation();
                  onRenameWorkspace(row.original);
                }}
              >
                Rename
              </Button>
            )}
            {owner ? (
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
            )}
          </div>
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
  const renameWorkspace = useRenameLiveWorkspace();
  const [editing, setEditing] = useState<RecordRow | null>(null);
  const [name, setName] = useState('');
  const [renameError, setRenameError] = useState('');
  const [renameNotice, setRenameNotice] = useState('');
  const beginRename = useCallback((workspace: RecordRow) => {
    setEditing(workspace);
    setName(text(workspace.name) ?? '');
    setRenameError('');
  }, []);
  const query = useRecords({ collection: 'workspaces', search, status: filters.status, page, recordId: '' });
  const data = query.data?.data;
  const [knownStatuses, setKnownStatuses] = useState<string[]>([]);
  useEffect(() => {
    const listed = data?.statuses;
    if (listed && listed.join('|') !== knownStatuses.join('|')) setKnownStatuses(listed);
  }, [data?.statuses, knownStatuses]);
  const statuses = data?.statuses ?? knownStatuses;
  const rows = useMemo(() => data?.rows ?? [], [data?.rows]);
  const tableColumns = useMemo(
    () => columns(risk, index, onOpenCustomer, beginRename, mode === 'live'),
    [risk, index, onOpenCustomer, beginRename, mode]
  );
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
  const originalName = editing ? text(editing.name) ?? '' : '';
  const editingRevision = editing && typeof editing.revision === 'number' ? editing.revision : null;
  const trimmedName = name.trim();
  const canSubmitRename = Boolean(editing && editing.renameAllowed === true && mode === 'live' && editingRevision !== null && trimmedName && trimmedName !== originalName && !renameWorkspace.isPending);

  async function saveRename() {
    if (!editing || editing.renameAllowed !== true || mode !== 'live' || editingRevision === null || !trimmedName || trimmedName === originalName) return;
    setRenameError('');
    try {
      await renameWorkspace.mutateAsync({ workspaceId: editing.id, name: trimmedName, revision: editingRevision });
      setRenameNotice(`Saved “${trimmedName}”. Restore “${originalName}” after acceptance verification.`);
      setEditing(null);
      setName('');
    } catch (error) {
      setRenameError(failureOf(error).message ?? 'The workspace name could not be saved.');
    }
  }

  return (
    <div className='flex min-w-0 flex-col gap-4'>
      {renameNotice && <p role='status' className='text-muted-foreground text-xs'>{renameNotice}</p>}
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
      <Dialog
        open={Boolean(editing)}
        onOpenChange={(open) => {
          if (!open && !renameWorkspace.isPending) {
            setEditing(null);
            setName('');
            setRenameError('');
          }
        }}
      >
        <DialogContent>
          <form
            className='flex flex-col gap-4'
            onSubmit={(event) => {
              event.preventDefault();
              void saveRename();
            }}
          >
            <DialogHeader>
              <DialogTitle>Rename approved test workspace</DialogTitle>
              <DialogDescription>
                Live acceptance only · {editing?.id}. This control appears only when the server returned an exact, expiring rename grant. Saving changes the canonical Rafii workspace name, so restore the original name after verification.
              </DialogDescription>
            </DialogHeader>
            <div className='flex flex-col gap-2'>
              <Label htmlFor='founder-live-workspace-name'>Workspace name</Label>
              <Input
                id='founder-live-workspace-name'
                value={name}
                maxLength={80}
                autoFocus
                onChange={(event) => setName(event.target.value)}
              />
              {originalName && <p className='text-muted-foreground text-xs'>Original name: {originalName}</p>}
              {renameError && <p role='alert' className='text-destructive text-sm'>{renameError}</p>}
            </div>
            <DialogFooter>
              <Button type='button' variant='quiet' disabled={renameWorkspace.isPending} onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button type='submit' variant='action' disabled={!canSubmitRename}>
                {renameWorkspace.isPending ? 'Saving…' : 'Save name'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
