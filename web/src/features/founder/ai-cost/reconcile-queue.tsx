'use client';

import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useReconcileAction } from '../actions';
import { useUnknownUsage } from '../customers/kit/api';
import type { EvidenceTarget } from '../customers/kit/evidence';
import { count, stateLabel, usdMicro, whenDateTime } from '../customers/kit/format';
import { QueryState } from '../customers/kit/page-frame';
import { SimpleTable } from '../customers/kit/simple-table';
import type { UnknownUsageRow } from '../customers/kit/types';
import { queueTarget } from './adapters';

/**
 * The reconcile queue (`GET /usage/unknown`): usage rows whose provider cost is still unknown. Each row's Reconcile opens
 * slice F's preview → confirm flow (`useReconcileAction`: `POST /usage/reconcile/preview` then `/confirm`, capability
 * `usage.reconcile`, a fresh second factor); the queue refreshes after a confirmed reconciliation. Rows open as evidence.
 * In Demo, or without the capability, the buttons stay disabled and the reason is written above the table.
 */
export function ReconcileQueue({ onEvidence }: { onEvidence: (target: EvidenceTarget) => void }) {
  const queue = useUnknownUsage();
  const reconcile = useReconcileAction();
  return (
    <>
      <QueryState query={queue} label='reconcile queue' isEmpty={(result) => result.rows.length === 0} emptyTitle='No unknown-cost rows' emptyDescription='Every usage row in this source has a recorded provider cost.'>
        {(result) => (
          <div className='flex flex-col gap-3'>
            <div className='flex flex-col gap-1'>
              <span className='text-muted-foreground text-xs'>
                {count(result.rows.length)} {result.rows.length === 1 ? 'row' : 'rows'} waiting · as of {whenDateTime(result.asOf)}
              </span>
              {reconcile.disabledReason && (
                <p className='text-muted-foreground text-xs' role='note'>
                  {reconcile.disabledReason}
                </p>
              )}
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
                { key: 'estimate', label: 'Estimated', align: 'right', render: (row) => (typeof row.estimatedUsdMicro === 'number' ? usdMicro(row.estimatedUsdMicro) : <span className='text-muted-foreground italic'>Not recorded</span>) },
                { key: 'state', label: 'Cost state', render: (row) => <StatusChip status='warning'>{stateLabel(row.costState ?? 'estimated_unknown')}</StatusChip> },
                { key: 'workspace', label: 'Workspace', render: (row) => <span className='font-mono text-xs'>{row.workspaceId ? `…${String(row.workspaceId).slice(-8)}` : 'Not recorded'}</span> },
                {
                  key: 'action',
                  label: <span className='sr-only'>Action</span>,
                  align: 'right',
                  render: (row) => {
                    const target = queueTarget(row);
                    const ready = reconcile.canStart(target);
                    return (
                      <Button
                        variant='glass'
                        size='sm'
                        disabled={!ready}
                        aria-label={`Reconcile the ${stateLabel(row.feature ?? row.kind)} row from ${whenDateTime(row.at)}`}
                        title={ready ? undefined : (reconcile.disabledReason ?? 'This row has no reservation id to reconcile.')}
                        onClick={(event) => {
                          event.stopPropagation();
                          reconcile.start(target);
                        }}
                        onKeyDown={(event) => event.stopPropagation()}
                      >
                        <Icons.checks /> Reconcile
                      </Button>
                    );
                  }
                }
              ]}
            />
          </div>
        )}
      </QueryState>
      {reconcile.dialog}
    </>
  );
}
