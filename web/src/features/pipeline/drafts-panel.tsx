'use client';

/**
 * Queue → Drafts: every draft that is not scheduled yet. Rafii v9 folded the Pipeline board into Queue: its
 * other columns repeated Queue (approval, the queue, published) and Ideas (sources), so only the drafts column
 * moved, with its cards, details and the Schedule…, Edit and Set aside actions. Set-aside drafts stay in the
 * column's footer; nothing is dropped.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useReducedMotion } from 'motion/react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { StateMessage } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ScheduleDialog } from '@/features/queue/schedule-dialog';
import { ApiError } from '@/lib/api/client';
import { keys, useAct, useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useHoverCapable } from '@/lib/hooks/use-hover-capable';
import { useWorkspace } from '@/lib/workspace/provider';
import { boardInvariants, deriveBoard, type BoardCard, type PipelineJob } from './board';
import { COLUMN_CLASS, ColumnView } from './column-view';
import { DetailSheet } from './detail-sheet';
import { EditDraftDialog } from './edit-draft-dialog';
import type { CardActions, CardPermissions } from './pipeline-card';
import { SetAsideDialog } from './set-aside-dialog';

/** How many drafts wait to be scheduled (the Queue tab's count); set-aside drafts are not counted. */
export function useDraftCount(): number | null {
  const snapshot = useSnapshot();
  const state = snapshot.data?.state;
  return useMemo(() => (state ? (deriveBoard(state, null, Date.now() / 1000).columns.find((column) => column.key === 'drafts')?.items.length ?? 0) : null), [state]);
}

export function DraftsPanel() {
  const snapshot = useSnapshot();
  const act = useAct();
  const access = useWorkspaceAccess();
  const reduce = useReducedMotion();
  // The lift is a hover affordance: a touch device would keep a tapped card raised.
  const hoverCapable = useHoverCapable();
  const lift = hoverCapable && !reduce;
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canApprove = checkAccess(access, { permission: 'approve' });
  const state = snapshot.data?.state;
  const readOnly = Boolean(state?.workspace?.sample);
  const permissions = useMemo<CardPermissions>(() => ({ canEdit, canApprove, readOnly }), [canEdit, canApprove, readOnly]);

  const [now, setNow] = useState(() => Date.now() / 1000);
  // Every snapshot that arrives re-reads the clock, so "expired" stays true to it.
  useEffect(() => setNow(Date.now() / 1000), [snapshot.dataUpdatedAt]);
  const [opened, setOpened] = useState<BoardCard | null>(null);
  const [scheduling, setScheduling] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [settingAside, setSettingAside] = useState<string | null>(null);
  const [holdEpoch, setHoldEpoch] = useState(0);

  const board = useMemo(() => deriveBoard(state, null, now), [state, now]);
  const drafts = board.columns.find((column) => column.key === 'drafts');

  useEffect(() => {
    if (process.env.NODE_ENV === 'production' || !state) return;
    const problems = boardInvariants(state, board, now);
    if (problems.length > 0) console.warn('[drafts] board invariants failed', problems);
  }, [state, board, now]);

  const revision = snapshot.data?.revision ?? 0;
  const client = useQueryClient();
  const { workspaceId } = useWorkspace();

  // Focus goes back to the card that opened the sheet; if it re-rendered or moved, to that card's new copy.
  const opener = useRef<{ element: HTMLElement | null; key: string } | null>(null);
  const returnFocus = useCallback(() => {
    const from = opener.current;
    if (!from) return null;
    if (from.element?.isConnected) return from.element;
    return document.querySelector<HTMLElement>(`[data-card-key="${CSS.escape(from.key)}"] [data-card-open]`);
  }, []);

  const actions: CardActions = {
    open: (card) => {
      const active = document.activeElement;
      opener.current = { element: active instanceof HTMLElement && active !== document.body ? active : null, key: card.key };
      setOpened(card);
    },
    // A dialog replaces the sheet instead of stacking two modal layers.
    edit: (variantId) => {
      setOpened(null);
      setEditing(variantId);
    },
    schedule: (variantId) => {
      setOpened(null);
      setScheduling(variantId);
    },
    setAside: (variantId) => {
      setOpened(null);
      setSettingAside(variantId);
    },
    // The details of a draft can lead to its job (a later successor); cancelling there works as in the Queue.
    cancel: (job: PipelineJob) => {
      act.mutate(
        { revision, action: 'p2_cancel', payload: { jobId: job.id } },
        {
          onSuccess: () => toast.success('Cancel requested.'),
          onError: (err) => {
            toast.error(err instanceof ApiError ? err.message : 'Could not cancel.');
            setHoldEpoch((epoch) => epoch + 1);
            if (err instanceof ApiError && err.status === 409 && workspaceId) void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
          }
        }
      );
    }
  };

  if (!snapshot.data || !drafts) {
    return (
      <div className={COLUMN_CLASS + ' gap-2 p-2'} role='status' aria-busy='true' aria-label='Loading drafts'>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className='h-28 w-full rounded-[var(--rafii-radius-card)]' />
        ))}
      </div>
    );
  }

  const nothing = drafts.items.length === 0 && (drafts.footer?.items.length ?? 0) === 0;
  return (
    <div data-tour='queue-drafts' className='flex min-w-0 flex-col gap-4'>
      {scheduling !== null && <ScheduleDialog key={scheduling} open onOpenChange={(open) => !open && setScheduling(null)} variantId={scheduling} />}
      {editing !== null && <EditDraftDialog key={editing} open onOpenChange={(open) => !open && setEditing(null)} variantId={editing} />}
      {settingAside !== null && <SetAsideDialog key={settingAside} open onOpenChange={(open) => !open && setSettingAside(null)} variantId={settingAside} />}
      <DetailSheet
        opened={opened}
        board={board}
        state={state}
        now={now}
        permissions={permissions}
        actions={actions}
        cancelPending={act.isPending}
        holdEpoch={holdEpoch}
        onShow={setOpened}
        onClose={() => setOpened(null)}
        returnFocus={returnFocus}
      />
      {readOnly && <StateMessage kind='unsupported' layout='inline' title='This is a sample workspace, so drafts are read-only.' />}
      {nothing ? (
        <StateMessage
          kind='empty'
          title='No drafts waiting'
          description='Drafts from Home, conversations and automations wait here until you schedule them. Schedule… picks the account and time and prepares the exact post for approval.'
          action={
            canEdit && !readOnly ? (
              <Link href='/app' className={buttonVariants({ variant: 'action', size: 'control' })}>
                Draft a post
              </Link>
            ) : undefined
          }
        />
      ) : (
        <ColumnView column={drafts} single platform={null} now={now} permissions={permissions} actions={actions} cancelPending={act.isPending} holdEpoch={holdEpoch} lift={lift} menu={hoverCapable} />
      )}
    </div>
  );
}
