'use client';

import { useState } from 'react';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useFounderScope } from '../customers/kit/api';
import { stateLabel, whenDateTime } from '../customers/kit/format';
import { DataStateChip, QueryState } from '../customers/kit/page-frame';
import { SimpleTable } from '../customers/kit/simple-table';
import { useFounderActions } from './api';
import { ActionSummary } from './facts';
import { BLOCKER_COPY, DEMO_REASON, KIND_LABEL, STATE_LABEL } from './model';
import type { ActiveBlock, FounderAction } from './types';

/**
 * Advanced › Actions (`GET /actions`, `audit.read`): every founder action request — previews, confirmations, refusals,
 * refund intents — newest first, and the account blocks in force. Read only; a row opens what the preview showed and
 * what happened. Demo has no founder actions and says so instead of asking the server.
 */
const STATE_STATUS = { previewed: 'info', confirmed: 'loading', executed: 'success', failed: 'danger', expired: 'neutral' } as const;

function shortId(value: string | null | undefined): string {
  return value ? `…${value.slice(-8)}` : 'Not recorded';
}

function outcome(action: FounderAction): string {
  if (action.blocker && BLOCKER_COPY[action.blocker]) return BLOCKER_COPY[action.blocker];
  if (action.errorCode) return stateLabel(action.errorCode.toLowerCase());
  if (action.state === 'executed') return action.result?.duplicate ? 'Already applied before; ran once' : 'Carried out';
  return STATE_LABEL[action.state] ?? stateLabel(action.state);
}

function ActionDetails({ action, onClose }: { action: FounderAction | null; onClose: () => void }) {
  return (
    <RafiiDialog open={action !== null} onOpenChange={(open) => !open && onClose()}>
      <RafiiDialogContent size='md'>
        {action && (
          <>
            <RafiiDialogHeader eyebrow={KIND_LABEL[action.kind]} title={STATE_LABEL[action.state] ?? stateLabel(action.state)} intro={`Requested ${whenDateTime(action.createdAt)}${action.finishedAt ? ` · finished ${whenDateTime(action.finishedAt)}` : ''}. Preview ${action.previewId}.`} />
            <RafiiDialogBody className='flex flex-col gap-4 pb-6'>
              {(action.blocker || action.errorCode) && <StateMessage kind={action.state === 'failed' ? 'error' : 'unsupported'} layout='inline' title={outcome(action)} />}
              <ActionSummary action={action} showResult={action.state === 'executed'} />
            </RafiiDialogBody>
          </>
        )}
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

export function FounderActionsLog() {
  const scope = useFounderScope();
  const listing = useFounderActions({ limit: 100 });
  const [selected, setSelected] = useState<FounderAction | null>(null);
  if (scope.mode === 'demo') return <StateMessage kind='unsupported' title='Demo has no founder actions' description={DEMO_REASON} />;
  if (scope.ready && !scope.capabilities.includes('audit.read')) {
    return <StateMessage kind='permission' title='The action log needs audit.read' description='Founder action requests are listed for operators holding the audit.read capability.' />;
  }
  return (
    <QueryState query={listing} label='founder actions'>
      {(result) => {
        const data = result.data;
        return (
          <div className='flex flex-col gap-5'>
            <div className='flex flex-wrap items-center gap-2'>
              <DataStateChip state={result.dataState} />
              <span className='text-muted-foreground text-xs'>As of {whenDateTime(result.asOf)} · previews expire after five minutes</span>
            </div>
            {data.actionsState === 'not_installed' ? (
              <StateMessage kind='partial' layout='inline' title='The action log is not installed yet (migration 068)' description='Founder action requests are recorded once migration 068 is applied.' />
            ) : (
              <SimpleTable<FounderAction>
                rows={data.actions}
                rowKey={(row) => row.previewId}
                caption='Founder action requests, newest first'
                emptyTitle='No founder actions yet'
                emptyDescription='Previews and confirmations of reconciliations, credit adjustments, blocks and refund intents appear here.'
                onRowClick={setSelected}
                columns={[
                  { key: 'at', label: 'Requested', render: (row) => whenDateTime(row.createdAt) },
                  { key: 'kind', label: 'Action', render: (row) => KIND_LABEL[row.kind] ?? stateLabel(row.kind) },
                  { key: 'target', label: 'Target', render: (row) => <span className='font-mono text-xs'>{`${stateLabel(row.targetType)} ${shortId(row.targetId)}`}</span> },
                  { key: 'state', label: 'State', render: (row) => <StatusChip status={STATE_STATUS[row.state] ?? 'neutral'}>{STATE_LABEL[row.state] ?? stateLabel(row.state)}</StatusChip> },
                  { key: 'outcome', label: 'Outcome', className: 'min-w-56 whitespace-normal', render: (row) => <span className='text-xs'>{outcome(row)}</span> }
                ]}
              />
            )}
            {data.truncated && <p className='text-muted-foreground text-xs'>Showing the latest {data.limit} requests.</p>}
            <section className='flex flex-col gap-2' aria-label='Account blocks in force'>
              <h3 className='rafii-eyebrow'>Account blocks in force</h3>
              {data.activeBlocksState === 'not_installed' ? (
                <StateMessage kind='partial' layout='inline' title='Account blocks are not installed yet (migrations 062 and 068)' description='Blocks are listed once migrations 062 and 068 are applied.' />
              ) : (
                <SimpleTable<ActiveBlock>
                  rows={data.activeBlocks}
                  rowKey={(row) => row.blockId}
                  caption='Account blocks in force'
                  emptyTitle='No account is blocked'
                  columns={[
                    { key: 'scope', label: 'Blocked', render: (row) => <span className='font-mono text-xs'>{row.userId ? `person ${shortId(row.userId)}` : `workspace ${shortId(row.workspaceId)}`}</span> },
                    { key: 'reason', label: 'Reason', render: (row) => stateLabel(row.reasonCode) },
                    { key: 'since', label: 'Since', render: (row) => whenDateTime(row.blockedAt) }
                  ]}
                />
              )}
            </section>
            <ActionDetails action={selected} onClose={() => setSelected(null)} />
          </div>
        );
      }}
    </QueryState>
  );
}
