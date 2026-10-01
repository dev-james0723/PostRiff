'use client';

import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useEvidence } from './evidence-state';

/**
 * A query receipt as a small chip; pressing it opens the evidence drawer on that receipt. Receipts are opaque ids,
 * shown shortened; the full id is the accessible name.
 */
export function ReceiptChip({ receiptId, label, className }: { receiptId: string; label?: string; className?: string }) {
  const { open } = useEvidence();
  const short = receiptId.length > 12 ? `${receiptId.slice(0, 8)}…` : receiptId;
  return (
    <button
      type='button'
      onClick={() => open(receiptId)}
      aria-label={`Open evidence for receipt ${receiptId}`}
      title={receiptId}
      className={cn('rafii-quiet rafii-focus text-muted-foreground hover:text-foreground inline-flex h-7 max-w-full items-center gap-1 rounded-full px-2.5 font-mono text-[11px] whitespace-nowrap', className)}
    >
      <Icons.page className='size-3 shrink-0' aria-hidden />
      <span className='truncate'>{label ?? `Receipt ${short}`}</span>
    </button>
  );
}

/** Up to `max` chips and a count for the rest; nothing renders for an empty list. */
export function ReceiptChips({ receiptIds, max = 4, className }: { receiptIds: readonly string[] | null | undefined; max?: number; className?: string }) {
  const ids = [...new Set(receiptIds ?? [])];
  if (ids.length === 0) return null;
  const shown = ids.slice(0, max);
  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', className)} role='group' aria-label='Evidence receipts'>
      {shown.map((id) => (
        <ReceiptChip key={id} receiptId={id} />
      ))}
      {ids.length > shown.length && <span className='text-muted-foreground text-[11px]'>+{ids.length - shown.length} more</span>}
    </div>
  );
}
