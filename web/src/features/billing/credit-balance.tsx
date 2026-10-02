import type { CreditBalance as Balance } from '@/lib/api/types';
import { formatDate } from '@/lib/time';
import { managedCreditState } from './billing-model';

const count = (value: number | null) => value === null ? 'Unavailable' : (value / 1000).toLocaleString(undefined, { maximumFractionDigits: 3 });
const SPEND_REASON = {
  credits_disabled: 'Managed tasks are unavailable.', policy_inactive: 'Managed tasks are unavailable.',
  ai_paused: 'Managed tasks are paused.', credit_debt: 'New paid tasks are paused until the billing adjustment is resolved.'
};

/** Absolute ledger readings only. A wallet is not a current-period usage counter. */
export function CreditBalance({ balance, exempt = false }: { balance: Balance | null; exempt?: boolean }) {
  const state = managedCreditState(balance);
  return (
    <section className='rafii-glass rounded-[var(--rafii-radius-card)] p-5' aria-label='Managed credits'>
      <h2 className='text-lg font-medium'>Managed credits</h2>
      {state.kind === 'unavailable' ? (
        <p className='text-muted-foreground mt-3 text-sm'>{exempt ? 'Application usage quota exemption applies. Credit balance is unavailable.' : 'Credit balance unavailable.'}</p>
      ) : (
        <>
          <dl className='mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3'>
            {([['Available', state.available], ['Held', state.held], ['Lifetime used', state.lifetimeUsed], ['Current-period grant', state.periodGrant]] as const).map(([label, value]) => (
              <div key={label}><dt className='text-muted-foreground text-sm'>{label}</dt><dd className='mt-1 text-2xl tabular-nums'>{count(value)}</dd></div>
            ))}
          </dl>
          <p className='text-muted-foreground mt-4 text-sm'>Held credits are reserved for tasks in progress, not used. Unused holds return when the task finishes.</p>
          <p className='text-muted-foreground mt-2 text-sm'>The current-period grant is the full verified grant. Available credits may include other periods or purchases; current-period usage is unavailable.</p>
          <p className='text-muted-foreground mt-2 text-sm'>{state.periodExpiresAt === null ? 'Current-period expiry unavailable.' : `Current-period credits expire ${formatDate(state.periodExpiresAt)}.`}</p>
          {state.debt !== null && state.debt > 0 && <p role='alert' className='mt-3 text-sm'>Billing adjustment pending: {count(state.debt)} credits. New paid tasks are paused.</p>}
          {!state.spendAvailable && state.spendUnavailableReason && state.spendUnavailableReason !== 'credit_debt' && <p role='status' className='mt-3 text-sm'>{SPEND_REASON[state.spendUnavailableReason]}</p>}
          {state.purchasedLots.length > 0 && (
            <div className='mt-5 border-t border-foreground/10 pt-4'>
              <h3 className='text-sm font-medium'>Purchased credits</h3>
              <ul className='mt-2 flex flex-col gap-2 text-sm'>
                {state.purchasedLots.map(lot => <li key={lot.grantId} className='flex flex-wrap justify-between gap-2'><span>{count(lot.available)} available · {count(lot.held)} held</span><span className='text-muted-foreground'>{lot.expiresAt === null ? 'Expiry unavailable' : `Expires ${formatDate(lot.expiresAt)}`}</span></li>)}
              </ul>
            </div>
          )}
        </>
      )}
      <p className='text-muted-foreground mt-4 text-sm'>No silent overage. Paid tasks pause when credits run out. Extra credits require a separate confirmed purchase.</p>
    </section>
  );
}
