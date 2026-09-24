import type { CreditBalance as Balance } from '@/lib/api/types';

const count = (value: number) => (value / 1000).toLocaleString(undefined, { maximumFractionDigits: 3 });

/** Aggregate values come from the authenticated usage ledger, never browser storage. */
export function CreditBalance({ balance }: { balance: Balance }) {
  return <section className='rafii-glass rounded-[var(--rafii-radius-card)] p-5 lg:col-span-2' aria-label='Cloud credits'>
    <h2 className='text-lg font-medium'>Cloud credits</h2>
    <dl className='mt-5 grid grid-cols-3 gap-3'>
      <div><dt className='text-muted-foreground text-sm'>Available</dt><dd className='mt-1 text-2xl tabular-nums'>{count(balance.availableMilliCredits)}</dd></div>
      <div><dt className='text-muted-foreground text-sm'>Reserved</dt><dd className='mt-1 text-2xl tabular-nums'>{count(balance.heldMilliCredits)}</dd></div>
      <div><dt className='text-muted-foreground text-sm'>Used</dt><dd className='mt-1 text-2xl tabular-nums'>{count(balance.usedMilliCredits)}</dd></div>
    </dl>
    <p className='text-muted-foreground mt-4 text-sm'>Reserved credits are pending, not an extra charge. Unused credits return after settlement.</p>
    {balance.debtMilliCredits > 0 && <p role='alert' className='mt-3 text-sm'>Billing adjustment pending: {count(balance.debtMilliCredits)} credits. New paid tasks are paused.</p>}
  </section>;
}
