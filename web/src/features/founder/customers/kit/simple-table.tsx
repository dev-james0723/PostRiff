'use client';

import type { ReactNode } from 'react';
import { StateMessage } from '@/components/rafii';
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';

/**
 * A small read-only table for short server lists (metric breakdowns, linked records, audit rows): no client sorting,
 * paging or filtering, so nothing is reordered or derived in the browser. Rows that would be empty say so.
 */
export interface SimpleColumn<T> {
  key: string;
  label: ReactNode;
  render: (row: T) => ReactNode;
  align?: 'left' | 'right';
  className?: string;
}

export function SimpleTable<T>({ rows, columns, rowKey, caption, emptyTitle = 'Nothing to show', emptyDescription, onRowClick, className }: { rows: readonly T[]; columns: SimpleColumn<T>[]; rowKey: (row: T, index: number) => string; caption: ReactNode; emptyTitle?: ReactNode; emptyDescription?: ReactNode; onRowClick?: (row: T) => void; className?: string }) {
  if (rows.length === 0) return <StateMessage kind='empty' layout='inline' title={emptyTitle} description={emptyDescription} />;
  return (
    <div className={cn('rafii-quiet overflow-hidden rounded-[var(--rafii-radius-card)]', className)}>
      <ScrollArea className='w-full'>
        <Table>
          <caption className='sr-only'>{caption}</caption>
          <TableHeader>
            <TableRow className='hover:bg-transparent'>
              {columns.map((column) => (
                <TableHead key={column.key} className={cn('whitespace-nowrap', column.align === 'right' && 'text-right', column.className)}>
                  {column.label}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row, index) => (
              <TableRow
                key={rowKey(row, index)}
                className={cn(onRowClick && 'cursor-pointer')}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key === 'Enter' && event.target === event.currentTarget) onRowClick(row);
                      }
                    : undefined
                }
              >
                {columns.map((column) => (
                  <TableCell key={column.key} className={cn(column.align === 'right' && 'text-right tabular-nums', column.className)}>
                    {column.render(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <ScrollBar orientation='horizontal' />
      </ScrollArea>
    </div>
  );
}
