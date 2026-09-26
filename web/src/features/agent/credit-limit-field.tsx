'use client';

import type { CreditEstimate } from '@/lib/api/types';

export interface CreditLimitFieldProps {
  value: string;
  onChange: (value: string) => void;
  availableMilliCredits: number;
  disabled?: boolean;
  /** The server's estimate for this exact request; absent while the brief is empty. */
  estimate?: CreditEstimate | null;
  estimating?: boolean;
  estimateError?: string | null;
  /** On Auto, the writer the browser resolved; when the server priced another one, the field says which. */
  autoModel?: string | null;
  /** A writer's name for that line; the raw id otherwise. */
  modelLabel?: (id: string) => string;
}

const credits = (milli: number) => (milli / 1000).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const asInput = (milli: number) => (milli / 1000).toFixed(1).replace(/\.0$/, '');

/** A spending limit next to the server's estimate. Shared by Home and follow-up turns. */
export function CreditLimitField({ value, onChange, availableMilliCredits, disabled, estimate, estimating, estimateError, autoModel, modelLabel }: CreditLimitFieldProps) {
  const ceiling = estimate?.ceilingMilliCredits ?? null;
  // Auto sends no model: the server prices the workspace default it resolves, which can differ from this browser's view.
  const pricedOther = Boolean(estimate && autoModel && estimate.model && estimate.model !== autoModel);
  const typed = Number(value);
  const belowCeiling = ceiling !== null && value.trim() !== '' && Number.isFinite(typed) && typed * 1000 < ceiling;
  return (
    <div className='rafii-quiet rounded-xl p-3'>
      <label className='flex flex-wrap items-center justify-between gap-2 text-sm'>
        Maximum credits
        <input aria-label='Maximum credits for this draft' inputMode='decimal' value={value} onChange={(event) => onChange(event.target.value)} placeholder='Set a limit' disabled={disabled} className='rafii-field min-h-11 w-28 rounded-lg px-3 text-base' />
      </label>
      {estimate ? (
        <div className='mt-2 space-y-1 text-xs'>
          <p>
            Usually about <span className='text-foreground font-medium'>{credits(estimate.estimateMilliCredits)}</span> credits. Up to{' '}
            <span className='text-foreground font-medium'>{credits(estimate.ceilingMilliCredits)}</span> is held until the draft settles; you pay the actual cost.{' '}
            <button type='button' className='rafii-focus underline underline-offset-2' onClick={() => onChange(asInput(estimate.ceilingMilliCredits))} disabled={disabled}>
              Use {credits(estimate.ceilingMilliCredits)}
            </button>
          </p>
          {pricedOther && <p role='status'>Estimated for {modelLabel ? modelLabel(estimate.model) : estimate.model}, the writer Auto uses for this workspace.</p>}
          {belowCeiling && <p role='status'>Set at least {credits(estimate.ceilingMilliCredits)} for this request.</p>}
          <details>
            <summary className='rafii-focus text-muted-foreground cursor-pointer'>How this is estimated</summary>
            <p className='text-muted-foreground mt-1'>Estimate: {estimate.basis}. Limit: the most this exact request can cost with retries.</p>
          </details>
        </div>
      ) : estimating ? (
        <p className='text-muted-foreground mt-2 text-xs' role='status'>Estimating…</p>
      ) : estimateError ? (
        <p className='mt-2 text-xs' role='status'>{estimateError}</p>
      ) : null}
      <p className='text-muted-foreground mt-2 text-xs'>Available: {credits(availableMilliCredits)} credits. Writing only.</p>
    </div>
  );
}
