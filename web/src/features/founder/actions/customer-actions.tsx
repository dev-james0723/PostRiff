'use client';

import { useId, useState } from 'react';
import { Icons } from '@/components/icons';
import { FounderExpandableActionBar } from '@/features/founder/motion/founder-motion';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useFounderScope } from '../customers/kit/api';
import { stateLabel, whenDate } from '../customers/kit/format';
import { AdjustCreditsDialog, BlockAccountDialog, RefundIntentDialog, UnblockAccountDialog, type WorkspaceChoice } from './account-dialogs';
import { useFounderActions } from './api';
import { activeBlockFor, unavailableReason } from './model';

type DialogId = 'block' | 'unblock' | 'credits' | 'refund';

/**
 * Customer 360 founder actions (CONTRACTS §8.F): block or lift a block, adjust credits, prepare a refund intent. Each
 * opens the shared confirm dialog; nothing runs from here. Whether the account is blocked and whether credits are on
 * come from `GET /actions` (Live, `audit.read`); a disabled action always says why, in words, next to the buttons.
 */
export function CustomerActions({ customerId, workspaces }: { customerId: string; workspaces: WorkspaceChoice[] }) {
  const scope = useFounderScope();
  const headingId = useId();
  const reasonsId = useId();
  const [dialog, setDialog] = useState<DialogId | null>(null);
  const listing = useFounderActions();
  const list = listing.data?.data;
  const block = list ? activeBlockFor(list.activeBlocks, customerId, workspaces.map((workspace) => workspace.id)) : null;
  const policies = list?.policies ?? null;
  const readsBlocks = scope.mode === 'live' && scope.capabilities.includes('audit.read');
  const base = { mode: scope.mode, capabilities: scope.capabilities, policies };

  const blockReason = unavailableReason({ ...base, kind: block ? 'account_unblock' : 'account_block' }) ?? (readsBlocks && listing.isPending ? 'Checking whether this account is blocked…' : null);
  const creditsReason = unavailableReason({ ...base, kind: 'credits_adjust' }) ?? (workspaces.length === 0 ? 'This customer has no workspace whose credits could change.' : null);
  const refundReason = unavailableReason({ ...base, kind: 'refund_intent' }) ?? (workspaces.length === 0 ? 'This customer has no workspace with a payment.' : null);
  const reasons = [...new Set([blockReason, creditsReason, refundReason].filter((reason): reason is string => reason !== null))];

  return (
    <section aria-labelledby={headingId} className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-3'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <h3 id={headingId} className='rafii-eyebrow'>
          Founder actions
        </h3>
        {block ? (
          <StatusChip status='warning'>
            Blocked since {whenDate(block.blockedAt)} · {stateLabel(block.reasonCode)}
          </StatusChip>
        ) : (
          list && <StatusChip icon={null}>Not blocked</StatusChip>
        )}
      </div>
      <FounderExpandableActionBar
        aria-describedby={blockReason ? reasonsId : undefined}
        actions={[
          { id: 'founder-block-action', label: block ? 'Lift block' : 'Block account', icon: <Icons.lock className='size-4' />, disabled: blockReason !== null, reason: blockReason, onClick: () => setDialog(block ? 'unblock' : 'block') },
          { id: 'founder-credits-action', label: 'Adjust credits', icon: <Icons.creditCard className='size-4' />, disabled: creditsReason !== null, reason: creditsReason, onClick: () => setDialog('credits') },
          { id: 'founder-refund-action', label: 'Prepare refund intent', icon: <Icons.billing className='size-4' />, disabled: refundReason !== null, reason: refundReason, onClick: () => setDialog('refund') }
        ]}
      />
      {reasons.length > 0 && (
        <ul id={reasonsId} className='text-muted-foreground flex flex-col gap-1 text-xs leading-relaxed'>
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      <BlockAccountDialog open={dialog === 'block'} onOpenChange={(open) => setDialog(open ? 'block' : null)} customerId={customerId} workspaces={workspaces} />
      <UnblockAccountDialog open={dialog === 'unblock'} onOpenChange={(open) => setDialog(open ? 'unblock' : null)} block={block} />
      <AdjustCreditsDialog open={dialog === 'credits'} onOpenChange={(open) => setDialog(open ? 'credits' : null)} workspaces={workspaces} />
      <RefundIntentDialog open={dialog === 'refund'} onOpenChange={(open) => setDialog(open ? 'refund' : null)} workspaces={workspaces} />
    </section>
  );
}