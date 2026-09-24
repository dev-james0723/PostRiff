'use client';

import { useEffect, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { StatefulButton } from '@/components/motion/button';
import { StateMessage } from '@/components/rafii';
import { Skeleton } from '@/components/ui/skeleton';
import { useFlash } from '@/hooks/use-flash';
import { useChannels, useMembers, useUsage } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { relativeTime } from '@/lib/time';
import { Allowances } from './allowances';
import { CreditBalance } from './credit-balance';
import { CreditPacks } from './credit-packs';
import { PAGE, infoContent } from './billing-copy';
import { Ledger } from './ledger';
import { GLASS_STATEFUL, LifecycleAlert } from './lifecycle-alert';
import { PlanCard } from './plan-card';
import { CheckoutConfirmation, Plans } from './plans';
import { useBillingRedirect } from './use-billing-redirect';
import { useCheckoutReturn } from './use-checkout-return';

function loadErrorText(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Sign in again to see this page.';
    if (error.status === 403) return 'You no longer have access to this workspace.';
    return error.message;
  }
  return 'The workspace did not answer.';
}

/** First load failed (nothing to show) or a refresh failed (older numbers stay, marked with their age). */
function LoadError({ error, hasData, updatedAt, onRetry }: { error: unknown; hasData: boolean; updatedAt: number; onRetry: () => Promise<{ isError: boolean }> }) {
  const [outcome, flash] = useFlash<'success' | 'error'>();
  const [retrying, setRetrying] = useState(false);
  return (
    <StateMessage
      kind={hasData ? 'stale' : 'error'}
      layout={hasData ? 'inline' : 'panel'}
      title={hasData ? 'Usage could not be refreshed' : 'Usage could not be loaded'}
      description={`${loadErrorText(error)}${hasData ? ` Showing what was loaded ${relativeTime(updatedAt / 1000)}.` : ''}`}
      className={hasData ? 'rafii-quiet rounded-[var(--rafii-radius-card)] px-5 py-4' : undefined}
      action={
        <StatefulButton
          variant='outline'
          size='sm'
          className={GLASS_STATEFUL + ' h-10'}
          state={retrying ? 'loading' : (outcome ?? 'idle')}
          loadingText='Retrying…'
          successText='Loaded'
          errorText='Try again'
          onClick={async () => {
            setRetrying(true);
            const result = await onRetry();
            setRetrying(false);
            flash(result.isError ? 'error' : 'success');
          }}
        >
          Retry
        </StatefulButton>
      }
    />
  );
}

/** Shaped like the page it stands in for; no numbers and no progress it cannot know. */
function BillingSkeleton() {
  return (
    <div role='status' aria-label='Loading usage and plan' className='flex flex-col gap-8'>
      <div className='grid gap-4 lg:grid-cols-3'>
        <Skeleton className='h-56 rounded-[var(--rafii-radius-card)]' />
        <Skeleton className='h-56 rounded-[var(--rafii-radius-card)] lg:col-span-2' />
      </div>
      <div className='flex flex-col gap-3'>
        <Skeleton className='h-6 w-24' />
        <div className='grid gap-4 md:grid-cols-2'>
          <Skeleton className='h-52 rounded-[var(--rafii-radius-card)]' />
          <Skeleton className='h-52 rounded-[var(--rafii-radius-card)]' />
        </div>
      </div>
    </div>
  );
}

export function BillingView() {
  const usage = useUsage();
  const channels = useChannels();
  const members = useMembers();
  const access = useWorkspaceAccess();
  const isOwner = checkAccess(access, { permission: 'owner' });
  const canEdit = checkAccess(access, { permission: 'edit' });
  const redirect = useBillingRedirect();
  const phase = useCheckoutReturn(usage);

  // Dates ("3 days left") read the clock of the latest response, not a clock frozen at mount.
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => setNow(Date.now() / 1000), [usage.dataUpdatedAt]);

  const data = usage.data;

  return (
    <PageContainer pageTitle={PAGE.title} pageDescription={PAGE.description} infoContent={infoContent}>
      {!data ? (
        usage.isError ? (
          <LoadError error={usage.error} hasData={false} updatedAt={usage.dataUpdatedAt} onRetry={() => usage.refetch()} />
        ) : (
          <BillingSkeleton />
        )
      ) : (
        <div className='flex flex-col gap-8'>
          {phase !== 'idle' && <CheckoutConfirmation phase={phase} />}
          {usage.isError && <LoadError error={usage.error} hasData updatedAt={usage.dataUpdatedAt} onRetry={() => usage.refetch()} />}
          <LifecycleAlert usage={data} isOwner={isOwner} redirect={redirect} now={now} />

          <div className='grid gap-4 lg:grid-cols-3'>
            <PlanCard usage={data} isOwner={isOwner} redirect={redirect} now={now} />
            {data.credits ? <CreditBalance balance={data.credits} /> : <Allowances usage={data} channels={channels} members={members} isOwner={isOwner} now={now} />}
          </div>

          <Plans usage={data} isOwner={isOwner} redirect={redirect} />
          {data.credits && isOwner && <CreditPacks />}

          {isOwner ? (
            <Ledger entries={data.ledger} canEdit={canEdit} />
          ) : (
            <section className='flex flex-col gap-1 px-1' aria-labelledby='ledger-heading'>
              <h3 id='ledger-heading' className='text-foreground text-lg font-medium tracking-tight'>
                Recent usage
              </h3>
              <p className='text-muted-foreground text-sm'>Run-by-run costs are shown to the workspace owner.</p>
            </section>
          )}
        </div>
      )}
    </PageContainer>
  );
}
