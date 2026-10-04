'use client';

import Link from 'next/link';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useIsMobile } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';
import { CustomerActions } from '../actions';
import { useFounderMode, useRecords } from './kit/api';
import { useAsk } from './kit/ask';
import { ReceiptChip, useEvidenceDrawer } from './kit/evidence';
import { count, minor, recordLabel, stateLabel, usdMicro, whenDate, whenDateTime } from './kit/format';
import { DataStateChip, QueryState } from './kit/page-frame';
import { SimpleTable, type SimpleColumn } from './kit/simple-table';
import type { RecordRow } from './kit/types';
import { flagIndex, joinFlags } from './customer-risk';
import { FlagCell, FlagCoverage } from './risk-views';
import { useCustomerRisk } from './use-customer-risk';
import { DemoWorkspaceActions } from './demo-workspace-actions';

/**
 * Customer 360 (PRD §5.4): a summary band of server fields and the tabs Summary · Billing · Usage & AI cost ·
 * Connections · Support · Activity · Advanced. Linked records come with the detail query in both Live and Demo.
 * Live uses approved metadata projections, never private workspace content. "Ask Rafii about this account" carries the opaque customer id only. Risk flags are the
 * server's (`GET /customers/risk?view=flagged`, the list's own cached answer), joined onto this customer's workspaces,
 * so the sheet and the list never disagree. Founder actions (block, credits, refund intent; CONTRACTS §8.F) sit under
 * the summary band and run only through their confirm dialog.
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

/** The customer's workspaces from the detail query's `workspaces` list, in the order of the row's `workspaceIds` (a join only). */
function linkedWorkspaces(customer: RecordRow, workspaces: readonly RecordRow[]): RecordRow[] {
  const ids = Array.isArray(customer.workspaceIds) ? (customer.workspaceIds as unknown[]).filter((id): id is string => typeof id === 'string') : [];
  const byId = new Map(workspaces.map((workspace) => [workspace.id, workspace]));
  return ids.map((id) => byId.get(id)).filter((workspace): workspace is RecordRow => workspace !== undefined);
}

function LinkedUnavailable({ what }: { what: string }) {
  return <StateMessage kind='partial' layout='inline' title={`${what} are unavailable`} description='This source did not return linked records. Check the connection in Settings before relying on this account history.' />;
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
  { key: 'recorded', label: 'Recorded', render: (row) => whenDate(row.recordedAt ?? row.issuedAt) }
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
  { key: 'kind', label: 'Entry', render: (row) => stateLabel(row.op ?? row.kind) },
  { key: 'quantity', label: 'Credits', align: 'right', render: (row) => count(row.quantity as number) },
  { key: 'balance', label: 'Balance after', align: 'right', render: (row) => count(row.balanceAfter as number) }
];

const ticketColumns: SimpleColumn<RecordRow>[] = [
  { key: 'title', label: 'Request', render: (row) => recordLabel(row) },
  { key: 'kind', label: 'Kind', render: (row) => stateLabel(row.category ?? row.kind) },
  { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.status)}</StatusChip> },
  { key: 'at', label: 'Opened', render: (row) => whenDate(row.at) }
];

const memberColumns: SimpleColumn<RecordRow>[] = [
  { key: 'name', label: 'Member', render: (row) => recordLabel(row) },
  { key: 'role', label: 'Role', render: (row) => stateLabel(row.role) },
  { key: 'status', label: 'Status', render: (row) => stateLabel(row.status) },
  { key: 'joined', label: 'Joined', render: (row) => whenDate(row.joinedAt) }
];

const connectionColumns: SimpleColumn<RecordRow>[] = [
  { key: 'provider', label: 'Provider', render: (row) => stateLabel(row.provider) },
  { key: 'capability', label: 'Use', render: (row) => stateLabel(row.capability) },
  { key: 'state', label: 'Health', render: (row) => <StatusChip icon={null}>{stateLabel(row.state)}</StatusChip> },
  { key: 'connectionState', label: 'Connection', render: (row) => stateLabel(row.connectionState) },
  { key: 'expiresAt', label: 'Expires', render: (row) => whenDateTime(row.expiresAt) },
  { key: 'lastSyncAt', label: 'Last sync', render: (row) => whenDateTime(row.lastSyncAt) }
];

const activityColumns: SimpleColumn<RecordRow>[] = [
  { key: 'label', label: 'Event', render: (row) => stateLabel(row.label) },
  { key: 'at', label: 'When', render: (row) => whenDateTime(row.at) }
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
  const returnFocus = useRef<HTMLElement | null>(null);
  const focusRecord = useRef<string | null>(recordId);
  const detail = useRecords(recordId ? { collection: 'customers', search: '', status: 'all', page: 1, recordId } : null);
  // The list's flagged-workspace answer (same key, so no extra request), asked only when the operator may read it.
  const risk = useCustomerRisk('flagged');
  const index = useMemo(() => flagIndex(risk.query.data?.data.rows), [risk.query.data]);
  useEffect(() => {
    setTab('summary');
    if (recordId) focusRecord.current = recordId;
  }, [recordId]);

  const data = detail.data?.data;
  const customer = data?.rows[0] ?? null;
  const linked = data?.linkedRecords;
  const truncated = Object.entries(data?.linkedRecordCoverage ?? {}).filter(([, coverage]) => coverage.truncated);
  const workspaces = customer ? linkedWorkspaces(customer, data?.workspaces ?? []) : [];
  const flags = customer ? joinFlags(customer.workspaceIds, index) : [];
  const subscription = linked?.subscriptions?.[0] ?? null;
  const workspace = workspaces[0] ?? null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange} onOpenChangeComplete={(opened) => {
      if (!opened && focusRecord.current) document.querySelector<HTMLElement>(`[data-customer-open="${CSS.escape(focusRecord.current)}"]`)?.focus();
    }}>
      <SheetContent
        side={isMobile ? 'bottom' : 'right'}
        className={cn('rafii-elevated gap-0 overflow-y-auto border-0 p-0 data-[side=right]:sm:max-w-[36rem]', isMobile ? 'max-h-[88dvh] rounded-t-[var(--rafii-radius-mobile-dialog)]' : 'rounded-l-[var(--rafii-radius-dialog)]')}
        aria-label='Customer 360'
        initialFocus={() => { if (!returnFocus.current && document.activeElement instanceof HTMLElement && document.activeElement !== document.body) returnFocus.current = document.activeElement; return true; }}
        finalFocus={() => {
          // Updating the record in the URL may recreate its table cell while the drawer is open.
          const target = returnFocus.current?.isConnected ? returnFocus.current : document.querySelector<HTMLElement>(`[data-customer-open="${CSS.escape(focusRecord.current ?? '')}"]`);
          returnFocus.current = null;
          return target ?? true;
        }}
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
                  <Fact label='Subscription'>{subscription ? `${typeof subscription.amountMinor === 'number' ? minor(subscription.amountMinor, subscription.currency as string) : 'Price not recorded'}${subscription.billingCycle ? ` / ${stateLabel(subscription.billingCycle)}` : ''}` : 'Not linked'}</Fact>
                  <Fact label='Credits'>{workspace && typeof workspace.creditsUsed === 'number' && typeof workspace.creditsQuota === 'number' ? `${count(workspace.creditsUsed)} of ${count(workspace.creditsQuota)}` : 'Not recorded'}</Fact>
                  <Fact label='Customer since'>{whenDate(customer.createdAt)}</Fact>
                </dl>
                <div className='flex flex-col gap-1.5'>
                  <div className='flex flex-wrap items-center gap-2'>
                    <span className='text-muted-foreground text-xs'>Risk flags</span>
                    <FlagCell risk={risk} flags={flags} />
                  </div>
                  <FlagCoverage risk={risk} />
                </div>

                {mode === 'demo' && workspace && typeof data?.revision === 'number' ? <DemoWorkspaceActions key={workspace.id} workspace={workspace} revision={data.revision} /> : <CustomerActions key={customer.id} customerId={customer.id} workspaces={workspaces.map((row) => ({ id: row.id, label: recordLabel(row) }))} />}

                {truncated.length > 0 && <p className='text-muted-foreground text-xs'>Showing up to 50 records per section. More records exist for: {truncated.map(([section]) => section).join(', ')}.</p>}

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
                    <h3 className='rafii-eyebrow'>Recorded account events</h3>
                    {linked ? (
                      <SimpleTable rows={linked.activity ?? []} columns={activityColumns} rowKey={(row) => row.id} caption='Recorded account events' emptyTitle='No events recorded' />
                    ) : (
                      <LinkedUnavailable what='Account events' />
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
                        {linked.payments ? <SimpleTable rows={linked.payments} columns={mode === 'live' ? paymentColumns.filter((column) => column.key !== 'method') : paymentColumns} rowKey={(row) => row.id} caption='Payments' emptyTitle='No payments linked' /> : <StateMessage kind='partial' layout='inline' title='Payment records are not connected' description='The required payment record source is missing. Account billing history is incomplete until this connection is configured.' />}
                        <p className='text-muted-foreground text-xs'>For refund and dispute records, open <Link href={`/founder/revenue?mode=${mode}`} className='text-foreground underline underline-offset-4'>Revenue</Link>.</p>
                      </>
                    ) : (
                      <LinkedUnavailable what='Billing records' />
                    )}
                  </TabsContent>

                  <TabsContent value='usage' className='flex flex-col gap-3 pt-3'>
                    {linked ? (
                      <>
                        <h3 className='rafii-eyebrow'>Usage</h3>
                        <SimpleTable rows={linked.usage ?? []} columns={mode === 'live' ? usageColumns.filter((column) => column.key !== 'credits') : usageColumns} rowKey={(row) => row.id} caption='Usage rows' emptyTitle='No usage recorded' />
                        <h3 className='rafii-eyebrow'>Credits</h3>
                        <SimpleTable rows={linked.credits ?? []} columns={mode === 'live' ? creditColumns.filter((column) => column.key !== 'balance') : creditColumns} rowKey={(row) => row.id} caption='Credit ledger' emptyTitle='No credit entries' />
                        {mode === 'live' && <p className='text-muted-foreground text-xs'>These are recorded credit entries. A verified current balance is not included in this history.</p>}
                      </>
                    ) : (
                      <LinkedUnavailable what='Usage rows' />
                    )}
                    <p className='text-muted-foreground text-xs'>
                      Explore cost by feature and model on the{' '}
                      <Link href={`/founder/ai-cost?mode=${mode}`} className='text-foreground underline underline-offset-4'>
                        AI & API cost
                      </Link>{' '}
                      page.
                    </p>
                  </TabsContent>

                  <TabsContent value='connections' className='pt-3'>
                    {linked?.connections ? <SimpleTable rows={linked.connections} columns={connectionColumns} rowKey={(row) => row.id} caption='Workspace connections' emptyTitle='No connections recorded for these workspaces' /> : <StateMessage
                      kind='partial'
                      layout='inline'
                      title={mode === 'demo' ? 'Connection health is not part of this Demo dataset' : 'Connection health is not configured'}
                      description='Account connection history is unavailable from this source. Open Operations to review connection setup and service health.'
                      action={
                        <Link href={`/founder/operations?mode=${mode}`} className={cn(buttonVariants({ variant: 'glass', size: 'default' }))}>
                          Open Operations
                        </Link>
                      }
                    />}
                  </TabsContent>

                  <TabsContent value='support' className='flex flex-col gap-3 pt-3'>
                    {linked ? <SimpleTable rows={linked.tickets ?? []} columns={ticketColumns} rowKey={(row) => row.id} caption='Support requests' emptyTitle='No requests from this customer' /> : <LinkedUnavailable what='Support requests' />}
                  </TabsContent>

                  <TabsContent value='activity' className='flex flex-col gap-3 pt-3'>
                    {linked ? (
                      <>
                        <h3 className='rafii-eyebrow'>Members</h3>
                        <SimpleTable rows={linked.members ?? []} columns={mode === 'live' ? memberColumns.filter((column) => column.key !== 'joined') : memberColumns} rowKey={(row) => row.id} caption='Workspace members' emptyTitle='No members linked' />
                        <h3 className='rafii-eyebrow'>Recorded account events</h3>
                        <SimpleTable rows={linked.activity ?? []} columns={activityColumns} rowKey={(row) => row.id} caption='Recorded account events' emptyTitle='No events recorded' />
                      </>
                    ) : (
                      <LinkedUnavailable what='Members' />
                    )}
                    {mode === 'live' && <p className='text-muted-foreground text-xs'>Account events include recorded session, MFA and token changes. Founder actions are in <Link href='/founder/advanced?mode=live&tab=audit' className='text-foreground underline underline-offset-4'>Advanced · Audit</Link>.</p>}
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
