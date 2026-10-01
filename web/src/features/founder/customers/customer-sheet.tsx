'use client';

import Link from 'next/link';
import { useEffect, useState, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useIsMobile } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';
import { useFounderMode, useRecords } from './kit/api';
import { useAsk } from './kit/ask';
import { ReceiptChip, useEvidenceDrawer } from './kit/evidence';
import { count, minor, recordLabel, stateLabel, usdMicro, whenDate, whenDateTime } from './kit/format';
import { DataStateChip, QueryState } from './kit/page-frame';
import { SimpleTable, type SimpleColumn } from './kit/simple-table';
import type { RecordRow } from './kit/types';
import { linkedWorkspaces, riskFlags, type RiskFlag } from './risk-flags';

/**
 * Customer 360 (PRD §5.4): a summary band of server fields and the tabs Summary · Billing · Usage & AI cost ·
 * Connections · Support · Activity · Advanced. Linked records come with the detail query (`linkedRecords`, Demo
 * today; Live says so per tab). "Ask Rafii about this account" carries the opaque customer id only.
 */
const TABS = ['summary', 'billing', 'usage', 'connections', 'support', 'activity', 'advanced'] as const;
type TabId = (typeof TABS)[number];

const TAB_LABEL: Record<TabId, string> = {
  summary: 'Summary',
  billing: 'Billing',
  usage: 'Usage & AI cost',
  connections: 'Connections',
  support: 'Support',
  activity: 'Activity',
  advanced: 'Advanced'
};

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className='rafii-quiet flex min-w-0 flex-col gap-0.5 rounded-[var(--rafii-radius-control)] px-3 py-2.5'>
      <dt className='text-muted-foreground text-[11px] font-medium'>{label}</dt>
      <dd className='text-foreground truncate text-sm font-medium tabular-nums'>{children}</dd>
    </div>
  );
}

export function RiskFlagChips({ flags, className }: { flags: RiskFlag[]; className?: string }) {
  if (flags.length === 0) return <span className='text-muted-foreground text-xs'>No flags</span>;
  return (
    <span className={cn('flex flex-wrap gap-1', className)}>
      {flags.map((flag) => (
        <StatusChip key={flag.id} status={flag.kind === 'hypothesis' ? 'info' : 'warning'} title={`${flag.evidence} · rule ${flag.rule}`}>
          {flag.label}
          {flag.kind === 'hypothesis' && <span className='text-muted-foreground ml-1 font-normal'>(hypothesis)</span>}
        </StatusChip>
      ))}
    </span>
  );
}

function LinkedUnavailable({ what }: { what: string }) {
  return <StateMessage kind='partial' layout='inline' title={`${what} are not part of the Live query yet`} description='The Live workspace query returns the customer row only; linked records land with the 054 views (P1). Demo shows the full sandbox.' />;
}

const subscriptionColumns: SimpleColumn<RecordRow>[] = [
  { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.plan) },
  { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.status)}</StatusChip> },
  { key: 'amount', label: 'Amount', align: 'right', render: (row) => minor(row.amountMinor as number, row.currency as string) },
  { key: 'renews', label: 'Renews', render: (row) => whenDate(row.renewsAt) }
];

const invoiceColumns: SimpleColumn<RecordRow>[] = [
  { key: 'number', label: 'Invoice', render: (row) => <span className='font-mono text-xs'>{String(row.number ?? row.id)}</span> },
  { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.status)}</StatusChip> },
  { key: 'amount', label: 'Amount', align: 'right', render: (row) => minor(row.amountMinor as number, row.currency as string) },
  { key: 'issued', label: 'Issued', render: (row) => whenDate(row.issuedAt) }
];

const paymentColumns: SimpleColumn<RecordRow>[] = [
  { key: 'at', label: 'When', render: (row) => whenDateTime(row.at) },
  { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.status)}</StatusChip> },
  { key: 'amount', label: 'Amount', align: 'right', render: (row) => minor(row.amountMinor as number, row.currency as string) },
  { key: 'method', label: 'Method', render: (row) => stateLabel(row.method) }
];

const usageColumns: SimpleColumn<RecordRow>[] = [
  { key: 'dimension', label: 'Dimension', render: (row) => stateLabel(row.dimension ?? row.kind) },
  { key: 'quantity', label: 'Quantity', align: 'right', render: (row) => `${count(row.quantity as number)} ${String(row.unit ?? '')}`.trim() },
  { key: 'credits', label: 'Credits used', align: 'right', render: (row) => count(row.creditsUsed as number) },
  { key: 'cost', label: 'Recorded cost', align: 'right', render: (row) => (typeof row.actualUsdMicro === 'number' ? usdMicro(row.actualUsdMicro) : <span className='text-muted-foreground italic'>Not recorded</span>) },
  { key: 'state', label: 'Cost state', render: (row) => <StatusChip icon={null}>{stateLabel(row.costState)}</StatusChip> }
];

const creditColumns: SimpleColumn<RecordRow>[] = [
  { key: 'at', label: 'When', render: (row) => whenDateTime(row.at) },
  { key: 'kind', label: 'Entry', render: (row) => stateLabel(row.kind) },
  { key: 'quantity', label: 'Credits', align: 'right', render: (row) => count(row.quantity as number) },
  { key: 'balance', label: 'Balance after', align: 'right', render: (row) => count(row.balanceAfter as number) }
];

const ticketColumns: SimpleColumn<RecordRow>[] = [
  { key: 'title', label: 'Request', render: (row) => recordLabel(row) },
  { key: 'kind', label: 'Kind', render: (row) => stateLabel(row.kind) },
  { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.status)}</StatusChip> },
  { key: 'at', label: 'Opened', render: (row) => whenDate(row.at) }
];

const memberColumns: SimpleColumn<RecordRow>[] = [
  { key: 'name', label: 'Member', render: (row) => recordLabel(row) },
  { key: 'role', label: 'Role', render: (row) => stateLabel(row.role) },
  { key: 'status', label: 'Status', render: (row) => stateLabel(row.status) },
  { key: 'joined', label: 'Joined', render: (row) => whenDate(row.joinedAt) }
];

function SafeFields({ row }: { row: RecordRow }) {
  const entries = Object.entries(row).filter(([key, value]) => key !== 'id' && value !== null && typeof value !== 'object');
  return (
    <dl className='grid grid-cols-[minmax(7rem,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm'>
      {entries.map(([key, value]) => (
        <div key={key} className='contents'>
          <dt className='text-muted-foreground text-xs'>{key}</dt>
          <dd className='min-w-0 font-mono text-xs break-all'>{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function CustomerSheet({ recordId, open, onOpenChange }: { recordId: string | null; open: boolean; onOpenChange: (open: boolean) => void }) {
  const isMobile = useIsMobile();
  const mode = useFounderMode();
  const ask = useAsk();
  const evidence = useEvidenceDrawer();
  const [tab, setTab] = useState<TabId>('summary');
  const detail = useRecords(recordId ? { collection: 'customers', search: '', status: 'all', page: 1, recordId } : null);
  useEffect(() => {
    setTab('summary');
  }, [recordId]);

  const data = detail.data?.data;
  const customer = data?.rows[0] ?? null;
  const linked = data?.linkedRecords;
  const workspaces = customer ? linkedWorkspaces(customer, data?.workspaces ?? []) : [];
  const flags = customer ? riskFlags(customer, data?.workspaces ?? []) : [];
  const subscription = linked?.subscriptions?.[0] ?? null;
  const workspace = workspaces[0] ?? null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={isMobile ? 'bottom' : 'right'}
        className={cn('rafii-elevated gap-0 overflow-y-auto border-0 p-0 data-[side=right]:sm:max-w-[36rem]', isMobile ? 'max-h-[88dvh] rounded-t-[var(--rafii-radius-mobile-dialog)]' : 'rounded-l-[var(--rafii-radius-dialog)]')}
        aria-label='Customer 360'
      >
        <QueryState query={detail} label='customer' layout='panel' isEmpty={(result) => result.data.rows.length === 0} emptyTitle='Customer not found' emptyDescription='The record id in the address does not match a customer in this source.'>
          {() =>
            customer && (
              <div className='flex flex-col gap-4 p-4 md:p-5'>
                <SheetHeader className='p-0 pr-10'>
                  <SheetTitle className='flex flex-wrap items-center gap-2'>
                    {recordLabel(customer)}
                    <DataStateChip state={detail.data?.dataState} />
                  </SheetTitle>
                  <SheetDescription className='flex flex-wrap items-center gap-x-2'>
                    {typeof customer.company === 'string' && customer.company !== recordLabel(customer) && <span>{customer.company}</span>}
                    <span className='font-mono text-xs'>{customer.id}</span>
                    <span>· {mode === 'demo' ? 'Demo record' : 'Live record'}</span>
                  </SheetDescription>
                </SheetHeader>

                <div className='flex flex-wrap items-center gap-2'>
                  <Button variant='action' size='default' onClick={() => ask({ prompt: 'Explain this account: its plan, billing, usage, connections and support history, and what I should do next.', selectedEntity: { type: 'customer', id: customer.id } })}>
                    <Icons.sparkles /> Ask Rafii about this account
                  </Button>
                  {detail.data?.receiptIds?.[0] && <ReceiptChip receiptId={detail.data.receiptIds[0]} />}
                </div>

                <dl className='grid grid-cols-2 gap-2 sm:grid-cols-3'>
                  <Fact label='Plan'>{stateLabel(customer.plan ?? workspace?.plan)}</Fact>
                  <Fact label='Status'>{stateLabel(customer.status)}</Fact>
                  <Fact label='Workspaces'>{Array.isArray(customer.workspaceIds) ? count(customer.workspaceIds.length) : count(workspaces.length)}</Fact>
                  <Fact label='Subscription'>{subscription ? `${minor(subscription.amountMinor as number, subscription.currency as string)} / ${stateLabel(subscription.billingCycle)}` : 'Not linked'}</Fact>
                  <Fact label='Credits'>{workspace && typeof workspace.creditsUsed === 'number' && typeof workspace.creditsQuota === 'number' ? `${count(workspace.creditsUsed)} of ${count(workspace.creditsQuota)}` : 'Not recorded'}</Fact>
                  <Fact label='Customer since'>{whenDate(customer.createdAt)}</Fact>
                </dl>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='text-muted-foreground text-xs'>Risk flags (observed rules v1)</span>
                  <RiskFlagChips flags={flags} />
                </div>

                <Tabs value={tab} onValueChange={(value) => setTab(value as TabId)}>
                  <div className='scrollbar-hide -mx-1 overflow-x-auto px-1'>
                    <TabsList variant='line' className='w-max'>
                      {TABS.map((id) => (
                        <TabsTrigger key={id} value={id}>
                          {TAB_LABEL[id]}
                        </TabsTrigger>
                      ))}
                    </TabsList>
                  </div>

                  <TabsContent value='summary' className='flex flex-col gap-3 pt-3'>
                    <h3 className='rafii-eyebrow'>Material events</h3>
                    {linked ? (
                      <SimpleTable rows={linked.activity ?? []} columns={[{ key: 'label', label: 'Event', render: (row) => stateLabel(row.label) }, { key: 'at', label: 'When', render: (row) => whenDateTime(row.at) }]} rowKey={(row) => row.id} caption='Timeline of material events' emptyTitle='No events recorded' />
                    ) : (
                      <LinkedUnavailable what='Material events' />
                    )}
                    {workspaces.length > 0 && (
                      <>
                        <h3 className='rafii-eyebrow'>Workspaces</h3>
                        <SimpleTable rows={workspaces} columns={[{ key: 'name', label: 'Workspace', render: (row) => recordLabel(row) }, { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.plan) }, { key: 'status', label: 'Status', render: (row) => stateLabel(row.status) }, { key: 'members', label: 'Members', align: 'right', render: (row) => count(row.memberCount as number) }]} rowKey={(row) => row.id} caption='Linked workspaces' />
                      </>
                    )}
                  </TabsContent>

                  <TabsContent value='billing' className='flex flex-col gap-3 pt-3'>
                    {linked ? (
                      <>
                        <h3 className='rafii-eyebrow'>Subscriptions</h3>
                        <SimpleTable rows={linked.subscriptions ?? []} columns={subscriptionColumns} rowKey={(row) => row.id} caption='Subscriptions' emptyTitle='No subscription linked' />
                        <h3 className='rafii-eyebrow'>Invoices</h3>
                        <SimpleTable rows={linked.invoices ?? []} columns={invoiceColumns} rowKey={(row) => row.id} caption='Invoices' emptyTitle='No invoices linked' />
                        <h3 className='rafii-eyebrow'>Payments</h3>
                        <SimpleTable rows={linked.payments ?? []} columns={paymentColumns} rowKey={(row) => row.id} caption='Payments' emptyTitle='No payments linked' />
                        <p className='text-muted-foreground text-xs'>Refunds and disputes per customer arrive with the 054 views (P1); the Revenue page shows them in aggregate.</p>
                      </>
                    ) : (
                      <LinkedUnavailable what='Billing records' />
                    )}
                  </TabsContent>

                  <TabsContent value='usage' className='flex flex-col gap-3 pt-3'>
                    {linked ? (
                      <>
                        <h3 className='rafii-eyebrow'>Usage</h3>
                        <SimpleTable rows={linked.usage ?? []} columns={usageColumns} rowKey={(row) => row.id} caption='Usage rows' emptyTitle='No usage recorded' />
                        <h3 className='rafii-eyebrow'>Credits</h3>
                        <SimpleTable rows={linked.credits ?? []} columns={creditColumns} rowKey={(row) => row.id} caption='Credit ledger' emptyTitle='No credit entries' />
                      </>
                    ) : (
                      <LinkedUnavailable what='Usage rows' />
                    )}
                    <p className='text-muted-foreground text-xs'>
                      Cost by feature and model for this account is on the{' '}
                      <Link href={`/founder/ai-cost?mode=${mode}`} className='text-foreground underline underline-offset-4'>
                        AI & API cost
                      </Link>{' '}
                      page once the ledger rollup carries a workspace dimension (P1).
                    </p>
                  </TabsContent>

                  <TabsContent value='connections' className='pt-3'>
                    <StateMessage
                      kind='partial'
                      layout='inline'
                      title='Connection health per customer is not collected yet'
                      description='Provider × capability, token expiry and last sync per workspace (M29) are a P1 view. Source-level health is on Operations.'
                      action={
                        <Link href={`/founder/operations?mode=${mode}`} className={cn(buttonVariants({ variant: 'glass', size: 'default' }))}>
                          Open Operations
                        </Link>
                      }
                    />
                  </TabsContent>

                  <TabsContent value='support' className='flex flex-col gap-3 pt-3'>
                    {linked ? <SimpleTable rows={linked.tickets ?? []} columns={ticketColumns} rowKey={(row) => row.id} caption='Support requests' emptyTitle='No requests from this customer' /> : <LinkedUnavailable what='Support requests' />}
                  </TabsContent>

                  <TabsContent value='activity' className='flex flex-col gap-3 pt-3'>
                    {linked ? (
                      <>
                        <h3 className='rafii-eyebrow'>Members</h3>
                        <SimpleTable rows={linked.members ?? []} columns={memberColumns} rowKey={(row) => row.id} caption='Workspace members' emptyTitle='No members linked' />
                      </>
                    ) : (
                      <LinkedUnavailable what='Members' />
                    )}
                    <StateMessage kind='partial' layout='inline' title='Security audit per customer is Live-only' description='Session, MFA and token events (business_audit_events) are listed on Advanced › Audit for the operator; a per-customer view is P1.' />
                  </TabsContent>

                  <TabsContent value='advanced' className='flex flex-col gap-3 pt-3'>
                    <div className='flex flex-wrap items-center gap-2'>
                      <DataStateChip state={detail.data?.dataState} />
                      <span className='text-muted-foreground text-xs'>As of {whenDateTime(detail.data?.asOf)}</span>
                      <Button variant='quiet' size='xs' onClick={() => evidence.open({ receiptId: detail.data?.receiptIds?.[0] ?? null, record: customer })}>
                        <Icons.listDetails className='size-3' /> Open as evidence
                      </Button>
                    </div>
                    <SafeFields row={customer} />
                  </TabsContent>
                </Tabs>
              </div>
            )
          }
        </QueryState>
        {evidence.drawer}
      </SheetContent>
    </Sheet>
  );
}
