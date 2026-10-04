'use client';
import { Button } from '@/components/ui/button';
import { parseCreditLimit } from '@/features/agent/credit-limit';
import type { RewriteApproval } from './rewrite-with-credit';

const credits = (milli: number) => (milli / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 });
export function RewriteCreditReview({ approval, maximum, onMaximum, onApprove, onCancel, busy, available }: {
  approval: RewriteApproval; maximum: string; onMaximum: (value: string) => void; onApprove: () => void; onCancel: () => void; busy: boolean; available: boolean;
}) {
  const cap = parseCreditLimit(maximum), estimate = approval.estimate;
  return <section aria-label='Review rewrite maximum' className='rafii-quiet flex flex-col gap-3 rounded-xl p-3'>
    <h4 className='font-medium'>Review the complete rewrite maximum</h4>
    <p className='text-sm'>MAX {credits(estimate.ceilingMilliCredits)} credits covers writing, grounding, recheck, comparisons and bounded retries. You pay the actual credits charged, up to your approved maximum.</p>
    <label className='flex flex-wrap items-center justify-between gap-2 text-sm'>Maximum credits for this rewrite
      <input aria-label='Maximum credits for this rewrite' inputMode='decimal' value={maximum} onChange={e => onMaximum(e.target.value)} disabled={busy} placeholder='Set a limit' className='rafii-field min-h-11 w-28 rounded-lg px-3 text-base' />
    </label>
    <p className='text-muted-foreground text-xs'>Available: {credits(estimate.availableMilliCredits)} credits. Approval covers this exact check, writer and facts.</p>
    <div className='flex flex-wrap gap-2'><Button disabled={!available || busy || cap === null || cap < estimate.ceilingMilliCredits || cap > estimate.availableMilliCredits} onClick={onApprove}>Approve MAX & rewrite</Button><Button variant='quiet' disabled={busy} onClick={onCancel}>Cancel review</Button></div>
  </section>;
}
