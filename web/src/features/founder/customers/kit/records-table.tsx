'use client';

import type { ReactNode } from 'react';
import { type Table as TanstackTable, flexRender } from '@tanstack/react-table';
import { motion } from 'motion/react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DataTableSkeleton } from '@/components/ui/table/data-table-skeleton';
import { getCommonPinningStyles } from '@/lib/data-table';
import { cn } from '@/lib/utils';
import { failureOf } from './api';
import { count } from './format';
import { pageCount } from './records';
import type { RecordRow } from './types';

/**
 * A server-paged table over the DataTable kit's table instance (`useDataTable` keeps page and sort in the URL via
 * nuqs). The server fixes the page size at 50 and does the searching, so the pager is Previous / Next with the
 * server's own total; there is no "rows per page" control to mislead. Every empty, loading and error state is a
 * `StateMessage` with wording the page supplies.
 */
export interface RecordsStatus {
  isPending: boolean;
  isFetching: boolean;
  error: unknown;
  total: number | undefined;
  pageSize: number | undefined;
  refetch: () => unknown;
}

export interface RecordsTableProps {
  table: TanstackTable<RecordRow>;
  status: RecordsStatus;
  label: string;
  caption: ReactNode;
  onOpen?: (row: RecordRow) => void;
  /** True while a search or filter narrows the list, so the empty state offers to clear it. */
  filtered?: boolean;
  onClear?: () => void;
  emptyTitle?: ReactNode;
  emptyDescription?: ReactNode;
  className?: string;
}

export function RecordsTable({ table, status, label, caption, onOpen, filtered = false, onClear, emptyTitle, emptyDescription, className }: RecordsTableProps) {
  const rows = table.getRowModel().rows;
  const columnCount = table.getAllColumns().length;
  if (status.isPending && rows.length === 0) return <DataTableSkeleton columnCount={Math.max(3, columnCount)} rowCount={6} withViewOptions={false} withPagination={false} />;
  if (status.error) {
    const failure = failureOf(status.error);
    return (
      <StateMessage
        kind={failure.status === 403 ? 'permission' : 'error'}
        title={`${label} could not be loaded`}
        description={failure.message}
        action={
          <Button variant='glass' size='default' onClick={() => void status.refetch()}>
            <Icons.refresh /> Retry
          </Button>
        }
      />
    );
  }
  const page = table.getState().pagination.pageIndex + 1;
  const pages = pageCount(status.total, status.pageSize);
  return (
    <div className={cn('flex min-w-0 flex-col gap-3', className)}>
      {rows.length === 0 ? (
        <StateMessage
          kind='empty'
          title={emptyTitle ?? (filtered ? 'No matching records' : `No ${label.toLowerCase()} yet`)}
          description={emptyDescription ?? (filtered ? 'Try a different search or status.' : 'This source returned no records.')}
          action={
            filtered && onClear ? (
              <Button variant='glass' size='default' onClick={onClear}>
                Clear filters
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className={cn('rafii-quiet overflow-hidden rounded-[var(--rafii-radius-card)]', status.isFetching && 'opacity-80 transition-opacity')} aria-busy={status.isFetching}>
          <ScrollArea className='w-full'>
            <Table>
              <caption className='sr-only'>{caption}</caption>
              <TableHeader>
                {table.getHeaderGroups().map((group) => (
                  <TableRow key={group.id} className='hover:bg-transparent'>
                    {group.headers.map((header) => (
                      <TableHead key={header.id} colSpan={header.colSpan} style={getCommonPinningStyles({ column: header.column })} className='whitespace-nowrap'>
                        {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <motion.tr
                    key={row.original.id}
                    layout
                    layoutId={`founder-customer-${row.original.id}`}
                    data-slot='table-row'
                    data-state={row.getIsSelected() ? 'selected' : undefined}
                    data-founder-detail-source={row.original.id}
                    data-founder-motion='15'
                    className={cn('border-b transition-[background,box-shadow,transform] duration-200 hover:bg-muted/50 has-aria-expanded:bg-muted/50 data-[state=selected]:bg-muted data-[state=selected]:shadow-[inset_3px_0_0_var(--foreground)]', onOpen && 'cursor-pointer hover:translate-x-0.5')}
                    onClick={onOpen ? () => onOpen(row.original) : undefined}
                    onKeyDown={
                      onOpen
                        ? (event) => {
                            if (event.key === 'Enter' && event.target === event.currentTarget) onOpen(row.original);
                          }
                        : undefined
                    }
                    tabIndex={onOpen ? 0 : undefined}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id} style={getCommonPinningStyles({ column: cell.column })}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </motion.tr>
                ))}
              </TableBody>
            </Table>
            <ScrollBar orientation='horizontal' />
          </ScrollArea>
        </div>
      )}
      <nav aria-label={`${label} pages`} className='flex flex-wrap items-center justify-between gap-2'>
        <span className='text-muted-foreground text-xs tabular-nums' role='status' aria-live='polite'>
          {typeof status.total === 'number' ? `${count(rows.length)} of ${count(status.total)} records · page ${page} of ${pages}` : `Page ${page}`}
        </span>
        <div className='flex items-center gap-1'>
          <Button variant='glass' size='sm' aria-label='Previous page' disabled={!table.getCanPreviousPage() || status.isFetching} onClick={() => table.previousPage()}>
            <Icons.chevronLeft /> Previous
          </Button>
          <Button variant='glass' size='sm' aria-label='Next page' disabled={!table.getCanNextPage() || status.isFetching} onClick={() => table.nextPage()}>
            Next <Icons.chevronRight />
          </Button>
        </div>
      </nav>
    </div>
  );
}