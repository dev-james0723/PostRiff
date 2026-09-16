'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { NumberTicker } from '@/components/motion/number-ticker';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { TRIAL } from '@/config/plans';
import { useChannels, useUsage } from '@/lib/api/hooks';
import { ApiError, cents, usd } from '@/lib/api/client';
import type { PlanTerms, Usage } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT } from '@/lib/ease';
import { daysUntil, formatDate, formatDateTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';

const infoContent = {
  title: 'How billing works',
  sections: [
    {
      title: 'Allowances stop, they never overcharge',
      description:
        'When a writing or media allowance runs out, drafting stops and tells you. Nothing is charged silently and there is no automatic overage.'
    },
    {
      title: 'Trial',
      description: `${TRIAL.days} days, ${TRIAL.connectedAccounts} connected accounts, ${TRIAL.writingBatches} writing batches. No card, no automatic conversion.`
    },
    {
      title: 'Cancelling',
      description: 'Your drafts stay readable and exportable after a cancellation. Publishing pauses at the end of the paid period.'
    }
  ]
};

function Meter({ value, max, label }: { value: number; max: number; label: string }) {
  const reduce = useReducedMotion();
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className='flex flex-col gap-1.5'>
      <div className='flex items-center justify-between text-sm'>
        <span>{label}</span>
        <span className='text-muted-foreground inline-flex items-center gap-1 tabular-nums'>
          <NumberTicker value={value} locale />
          <span>/ {max.toLocaleString()}</span>
        </span>
      </div>
      <div
        role='progressbar'
        aria-label={label}
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className='bg-muted h-2 w-full overflow-hidden rounded-full'
      >
        {/* Full-width fill slid in from the left (transform only), so its rounded end keeps its shape. */}
        <motion.div
          className={cn('h-full w-full rounded-full', pct >= 90 ? 'bg-amber-500' : 'bg-primary')}
          initial={reduce ? false : { x: '-100%' }}
          animate={{ x: `${pct - 100}%` }}
          transition={reduce ? { duration: 0 } : { duration: 0.9, ease: EASE_OUT }}
        />
      </div>
    </div>
  );
}

function statusLabel(usage: Usage) {
  const sub = usage.subscription;
  if (!sub) return 'Trial';
  return sub.status.replace(/_/g, ' ');
}

function allowanceOf(terms: PlanTerms | undefined, key: string, fallback: number) {
  const value = terms?.entitlements?.[key];
  return typeof value === 'number' ? value : fallback;
}

export function BillingView() {
  const usage = useUsage();
  const channels = useChannels();
  const access = useWorkspaceAccess();
  const { api, workspaceId } = useWorkspaceApi();
  const params = useSearchParams();
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const outcome = params.get('checkout');
    if (outcome === 'success') toast.success('Thanks — your subscription is being confirmed. This page updates as soon as the provider notifies us.');
    if (outcome === 'cancelled') toast.info('Checkout cancelled. Nothing was charged.');
  }, [params]);

  const data = usage.data;
  const owner = checkAccess(access, { permission: 'owner' });
  const currentTerms = data?.planTerms.find((t) => t.id === data.entitlement.planTermsId);
  const purchasable = data?.planTerms.filter((t) => t.status !== 'retired' && t.plan !== 'trial') ?? [];
  const connectedCount = channels.data?.channels.length ?? 0;
  const trialDays = data?.subscription?.status === 'trial' ? daysUntil(data.entitlement.resetsAt) : null;

  async function checkout(terms: PlanTerms) {
    setBusy(terms.id);
    try {
      const { url } = await api.checkout(workspaceId, terms.id);
      window.location.assign(url);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Checkout could not be started.');
      setBusy(null);
    }
  }

  async function portal() {
    setBusy('portal');
    try {
      const { url } = await api.portal(workspaceId);
      window.location.assign(url);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The billing portal could not be opened.');
      setBusy(null);
    }
  }

  return (
    <PageContainer
      pageTitle='Usage & plan'
      pageDescription='What you have, what you’ve used, and what it costs.'
      infoContent={infoContent}
      access={owner}
      accessFallback={
        <p className='text-muted-foreground text-sm'>Only the workspace owner can see billing. Ask them if you need a change.</p>
      }
    >
      <div className='flex flex-col gap-6'>
        {usage.isLoading || !data ? (
          <Skeleton className='h-40 w-full' />
        ) : (
          <>
            {data.lifecycle.status === 'past_due' && (
              <Alert variant='destructive'>
                <Icons.warning className='size-4' />
                <AlertTitle>Payment failed</AlertTitle>
                <AlertDescription>
                  Publishing continues until {formatDate(data.subscription?.graceUntil)}. Update your payment method in the billing portal to keep it that way.
                </AlertDescription>
              </Alert>
            )}

            <div className='grid gap-4 lg:grid-cols-3'>
              <Card className='lg:col-span-1'>
                <CardHeader>
                  <CardDescription>Current plan</CardDescription>
                  <CardTitle className='flex items-center gap-2 text-2xl'>
                    {data.subscription?.label ?? 'Trial'}
                    <Badge variant='outline'>{statusLabel(data)}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className='text-muted-foreground flex flex-col gap-1 text-sm'>
                  {data.subscription?.live ? (
                    <>
                      <span>
                        {cents(data.subscription.priceCents, data.subscription.currency)} / month
                        {data.subscription.priceStatus !== 'active' && ' · introductory'}
                      </span>
                      {data.subscription.currentPeriodEnd && (
                        <span>
                          {data.subscription.cancelAtPeriodEnd ? 'Ends' : 'Renews'} {formatDate(data.subscription.currentPeriodEnd)}
                        </span>
                      )}
                    </>
                  ) : trialDays !== null ? (
                    <span>
                      {trialDays > 0 ? `${trialDays} day${trialDays === 1 ? '' : 's'} left` : 'Trial ended'} · no card on file · nothing converts automatically
                    </span>
                  ) : (
                    <span>No live subscription on this workspace.</span>
                  )}
                  <span>Export stays available: {data.lifecycle.exportAvailable === false ? 'no' : 'yes'}</span>
                </CardContent>
                <CardFooter className='flex flex-wrap gap-2'>
                  {data.billing?.portalAvailable ? (
                    <Button disabled={busy !== null} onClick={() => void portal()}>
                      Manage billing
                    </Button>
                  ) : (
                    <span className='text-muted-foreground text-xs'>Payment method, invoices and cancellation appear here after your first subscription.</span>
                  )}
                </CardFooter>
              </Card>

              <Card className='lg:col-span-2'>
                <CardHeader>
                  <CardDescription>This period</CardDescription>
                  <CardTitle>Allowances</CardTitle>
                </CardHeader>
                <CardContent className='flex flex-col gap-4'>
                  <Meter
                    label='AI writing batches'
                    value={data.entitlement.writingBatchesRemaining}
                    max={Math.max(data.entitlement.writingBatchesRemaining, allowanceOf(currentTerms, 'writingBatches', TRIAL.writingBatches))}
                  />
                  <Meter
                    label='Media credits'
                    value={data.entitlement.mediaCreditsRemaining}
                    max={Math.max(data.entitlement.mediaCreditsRemaining, allowanceOf(currentTerms, 'mediaCredits', TRIAL.mediaCredits))}
                  />
                  <Meter label='Connected accounts' value={connectedCount} max={data.entitlement.connectedAccounts} />
                  <div className='text-muted-foreground flex flex-wrap gap-x-6 gap-y-1 text-xs'>
                    <span>Storage: {data.entitlement.storageMb} MB included</span>
                    <span>Members: {data.entitlement.members}</span>
                    {data.entitlement.resetsAt && <span>Resets {formatDate(data.entitlement.resetsAt)}</span>}
                    <span>Overage: stop — nothing is charged silently</span>
                  </div>
                  <div className='rounded-lg border p-3 text-sm'>
                    <div className='flex items-center justify-between'>
                      <span className='font-medium'>Model spend this {data.budget.windowKind}</span>
                      <span className='tabular-nums'>
                        {usd(data.budget.spentUsdMicro)} <span className='text-muted-foreground'>of {usd(data.budget.stopUsdMicro)} stop-line</span>
                      </span>
                    </div>
                    <p className='text-muted-foreground mt-1 text-xs'>
                      Reserved {usd(data.budget.reservedUsdMicro)} · status {data.budget.status}. Requests are refused before any provider call once the stop-line would be crossed.
                    </p>
                  </div>
                </CardContent>
              </Card>
            </div>

            <section className='flex flex-col gap-3' aria-labelledby='plans-heading'>
              <div>
                <h3 id='plans-heading' className='text-lg font-semibold'>
                  Plans
                </h3>
                <p className='text-muted-foreground text-sm'>{data.note}</p>
              </div>
              <div className='grid gap-4 md:grid-cols-2'>
                {purchasable.map((terms) => {
                  const current = terms.id === data.entitlement.planTermsId;
                  const canBuy = Boolean(data.billing?.checkoutAvailable) && terms.status === 'active' && !current && !data.subscription?.live;
                  return (
                    <Card key={terms.id} className={cn(current && 'border-primary')}>
                      <CardHeader>
                        <CardDescription className='flex items-center gap-2'>
                          {terms.plan}
                          {current && <Badge>Current</Badge>}
                          {terms.status !== 'active' && <Badge variant='outline'>introductory pricing</Badge>}
                        </CardDescription>
                        <CardTitle className='text-2xl'>
                          {terms.label} <span className='text-muted-foreground text-base font-normal'>{cents(terms.priceCents, terms.currency)} / month</span>
                        </CardTitle>
                      </CardHeader>
                      <CardContent className='text-muted-foreground text-sm'>
                        {String(allowanceOf(terms, 'writingBatches', 0))} AI writing batches · {String(allowanceOf(terms, 'connectedAccounts', 0))} accounts ·{' '}
                        {String(allowanceOf(terms, 'storageMb', 0))} MB · v{terms.version}
                      </CardContent>
                      <CardFooter>
                        {canBuy ? (
                          <Button disabled={busy !== null} onClick={() => void checkout(terms)}>
                            {busy === terms.id ? 'Opening checkout…' : `Choose ${terms.label}`}
                          </Button>
                        ) : data.subscription?.live && !current ? (
                          <span className='text-muted-foreground text-xs'>Switch plans from the billing portal.</span>
                        ) : terms.status !== 'active' || !data.billing?.checkoutAvailable ? (
                          <span className='text-muted-foreground text-xs'>Not yet available for purchase on this deployment.</span>
                        ) : null}
                      </CardFooter>
                    </Card>
                  );
                })}
              </div>
            </section>

            <section className='flex flex-col gap-3' aria-labelledby='ledger-heading'>
              <h3 id='ledger-heading' className='text-lg font-semibold'>
                Recent usage
              </h3>
              {data.ledger.length === 0 ? (
                <p className='text-muted-foreground text-sm'>No usage recorded yet.</p>
              ) : (
                <div className='overflow-x-auto rounded-lg border'>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>When</TableHead>
                        <TableHead>Kind</TableHead>
                        <TableHead>Dimension</TableHead>
                        <TableHead className='text-right'>Estimated</TableHead>
                        <TableHead className='text-right'>Actual</TableHead>
                        <TableHead>State</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.ledger.slice(0, 20).map((entry, index) => (
                        <TableRow key={`${entry.at}-${index}`}>
                          <TableCell className='whitespace-nowrap'>{formatDateTime(entry.at)}</TableCell>
                          <TableCell>{entry.kind}</TableCell>
                          <TableCell>
                            {entry.dimension}
                            {entry.model ? ` · ${entry.model}` : ''}
                          </TableCell>
                          <TableCell className='text-right tabular-nums'>{usd(entry.estimatedUsdMicro)}</TableCell>
                          <TableCell className='text-right tabular-nums'>{usd(entry.actualUsdMicro)}</TableCell>
                          <TableCell>
                            <Badge variant='outline'>{entry.costState.replace(/_/g, ' ')}</Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </PageContainer>
  );
}
