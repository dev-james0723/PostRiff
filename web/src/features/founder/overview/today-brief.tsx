'use client';

import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Panel } from '@/features/workspace/rafii-parts';
import { RafiiAvatar } from '@/features/site-agent/rafii-avatar';
import { RichText } from '@/features/site-agent/answer';
import { formatRelative } from '@/features/founder/shared/format';
import { ReceiptChips } from '@/features/founder/shared/receipt-chip';
import type { FounderMode, OverviewBrief } from '@/lib/founder/types';

/**
 * Today brief (PRD §5.2 A): three to five sentences Founder Rafii wrote from today's receipts, each receipt a chip,
 * and "Ask about today". When the server has no brief, it says so rather than inventing one.
 */
export function TodayBrief({ brief, mode, onAsk }: { brief: OverviewBrief | null; mode: FounderMode; onAsk: () => void }) {
  return (
    <Panel eyebrow={`Today’s brief · ${mode === 'demo' ? 'Demo evidence' : 'Live records'}`} material='glass' data-tour='founder-brief' className='gap-3' actions={
      <Button type='button' variant='glass' size='sm' onClick={onAsk} className='gap-1.5'>
        <Icons.sparkles className='size-3.5' aria-hidden /> Ask about today
      </Button>
    }>
      <div className='flex items-start gap-3'>
        <RafiiAvatar size={36} className='mt-0.5' />
        <div className='flex min-w-0 flex-1 flex-col gap-2'>
          {brief?.text ? <RichText text={brief.text} className='text-[15px]' /> : <p className='text-muted-foreground text-sm leading-relaxed'>No brief has been written for today yet. Ask Rafii for one; it answers from today’s receipts only.</p>}
          <div className='flex flex-wrap items-center gap-2'>
            <ReceiptChips receiptIds={brief?.receiptIds} max={6} />
            {brief?.generatedAt && <span className='text-muted-foreground text-xs'>Written {formatRelative(brief.generatedAt)}</span>}
          </div>
        </div>
      </div>
    </Panel>
  );
}
