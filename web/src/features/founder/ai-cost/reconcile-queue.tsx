'use client';

import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useCapability, useUnknownUsage } from '../customers/kit/api';
import type { EvidenceTarget } from '../customers/kit/evidence';
import { count, stateLabel, usdMicro, whenDateTime } from '../customers/kit/format';
import { QueryState } from '../customers/kit/page-frame';
import { SimpleTable } from '../customers/kit/simple-table';
import type { UnknownUsageRow } from '../customers/kit/types';

/**
 * The reconcile queue (`GET /usage/unknown`): usage rows whose provider cost is still unknown. Reading is P0;
 * reconciling needs the `usage.reconcile` capability, a step-up and an evidence string (PRD §7.5), so the action
 * stays disabled with its reason until that route exists. Rows open as evidence.
 */
export function ReconcileQueue({ onEvidence }: { onEvidence: (target: EvidenceTarget) => void }) {
  const queue = useUnknownUsage();
  const canReconcile = useCapability('usage.reconcile');
  return (
    <QueryState query={queue} label='reconcile queue' isEmpty={(result) => result.rows.length === 0} emptyTitle='No unknown-cost rows' emptyDescription='Every usage row in this source has a recorded provider cost.'>
      {(result) => (
        <div className='flex flex-col gap-3'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <span className='text-muted-foreground text-xs'>
              {count(result.rows.length)} {result.rows.length === 1 ? 'row' : 'rows'} waiting · as of {whenDateTime(result.asOf)}
            </span>
            <Tooltip>
              <TooltipTrigger render={<span className='inline-flex' />}>
                <Button variant='glass' size='sm' disabled aria-disabled aria-describedby='reconcile-reason'>
                  <Icons.checks /> Reconcile
                </Button>
              </TooltipTrigger>
              <TooltipContent side='bottom' className='rafii-elevated max-w-72 rounded-2xl px-3.5 py-3 text-left'>
                <p id='reconcile-reason' className='text-muted-foreground text-xs leading-relaxed'>
                  {canReconcile ? 'Reconciling from the browser ships with the usage.reconcile route (P1): it needs a step-up, an evidence string and a revision.' : 'This operator has no usage.reconcile capability. The route and its step-up are P1.'}
                </p>
              </TooltipContent>
            </Tooltip>
          </div>
          <SimpleTable<UnknownUsageRow>
            rows={result.rows}
            rowKey={(row) => row.id}
            caption='Usage rows without a recorded provider cost'
            onRowClick={(row) => onEvidence({ receiptId: result.receiptIds?.[0] ?? null, record: row })}
            columns={[
              { key: 'at', label: 'When', render: (row) => whenDateTime(row.at) },
              { key: 'feature', label: 'Feature', render: (row) => stateLabel(row.feature ?? row.kind) },
              { key: 'model', label: 'Provider · model', render: (row) => [row.provider, row.model].filter(Boolean).join(' · ') || 'Not recorded' },
              { key: 'quantity', label: 'Quantity', align: 'right', render: (row) => `${count(row.quantity)} ${row.unit ?? ''}`.trim() },
              { key: 'estimate', label: 'Estimated', align: 'right', render: (row) => (typeof row.estimatedUsdMicro === 'number' ? usdMicro(row.estimatedUsdMicro) : <span className='text-muted-foreground italic'>Not recorded</span>) },
              { key: 'state', label: 'Cost state', render: (row) => <StatusChip status='warning'>{stateLabel(row.costState ?? 'estimated_unknown')}</StatusChip> },
              { key: 'workspace', label: 'Workspace', render: (row) => <span className='font-mono text-xs'>{row.workspaceId ? `…${String(row.workspaceId).slice(-8)}` : 'Not recorded'}</span> }
            ]}
          />
        </div>
      )}
    </QueryState>
  );
}
