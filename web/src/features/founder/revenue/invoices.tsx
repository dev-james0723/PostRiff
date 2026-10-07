'use client';

import Link from 'next/link';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { founderSafeHref } from '@/features/founder/shared';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useFounderMode } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { count, minor, stateLabel, whenDate } from '../customers/kit/format';
import { Panel, QueryState } from '../customers/kit/page-frame';
import type { PeriodKey } from '../customers/kit/period';
import { SimpleTable, type SimpleColumn } from '../customers/kit/simple-table';
import { useRevenueInvoices } from './hooks';
import { draftReminderPrompt, dunningRows, reasonText, shortId } from './rows';
import type { InvoiceRow, InvoicesData } from './types';

/**
 * Invoices of every plan (`GET /revenue/invoices`, 057 pr_invoices) and the dunning list: invoices still owed. A row's
 * customer links to Customer 360; "Draft reminder" asks Founder Rafii for a payment-reminder draft (founder_draft_message),
 * which it shows for review and never sends. Amounts are the invoice's own minor units in its own currency.
 */

function CustomerCell({ row }: { row: InvoiceRow }) {
  const href = founderSafeHref(row.href);
  if (!href) return <span className='text-muted-foreground'>{row.workspaceId ? shortId(row.workspaceId) : 'Not attributed'}</span>;
  return (
    <Link href={href} className='rafii-focus text-foreground inline-flex items-center gap-1 underline-offset-4 hover:underline'>
      {shortId(row.customerId)} <Icons.arrowUpRight className='size-3.5' aria-hidden />
      <span className='sr-only'>Open Customer 360</span>
    </Link>
  );
}

const BASE_COLUMNS: SimpleColumn<InvoiceRow>[] = [
  { key: 'invoice', label: 'Invoice', render: (row) => <span className='font-mono text-xs'>{shortId(row.invoiceId)}</span> },
  { key: 'customer', label: 'Customer', render: (row) => <CustomerCell row={row} /> },
  { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.status)}</StatusChip> },
  { key: 'due', label: 'Amount due', align: 'right', render: (row) => minor(row.amountDueMinor, row.currency) },
  { key: 'paid', label: 'Paid', align: 'right', render: (row) => minor(row.amountPaidMinor, row.currency) },
  { key: 'reason', label: 'Reason', render: (row) => stateLabel(row.billingReason) },
  { key: 'at', label: 'Last event', render: (row) => whenDate(row.eventAt) }
];

function Unrecorded({ data, what }: { data: InvoicesData; what: string }) {
  return <StateMessage kind='unsupported' layout='inline' title={`No ${what} recorded`} description={[reasonText(data.reason), data.collectingSince ? `Collecting since ${whenDate(data.collectingSince)}.` : null].filter(Boolean).join(' ')} />;
}

export function InvoicesPanel({ period }: { period: PeriodKey }) {
  const query = useRevenueInvoices(period);
  const mode = useFounderMode();
  return (
    <Panel title='Invoices' description={`Every plan's invoices with their latest state, newest first${mode === 'demo' ? ' · Candidate v2 catalog (not active)' : ''}.`}>
      <QueryState query={query} label='invoices'>
        {(result) =>
          result.data.reason ? (
            <Unrecorded data={result.data} what='invoices' />
          ) : (
            <div className='flex min-w-0 flex-col gap-2'>
              <SimpleTable rows={result.data.rows} rowKey={(row) => row.invoiceId} caption={`Invoices · ${mode === 'demo' ? 'fictional Demo records' : 'Live records'}`} emptyTitle='No invoice in this period' columns={BASE_COLUMNS} />
              {result.data.truncated && <p className='text-muted-foreground text-xs'>Showing the newest {count(result.data.limit)} invoices.</p>}
            </div>
          )
        }
      </QueryState>
    </Panel>
  );
}

export function DunningPanel({ period }: { period: PeriodKey }) {
  const open = useRevenueInvoices(period, 'open');
  const uncollectible = useRevenueInvoices(period, 'uncollectible');
  const ask = useAsk();
  const columns: SimpleColumn<InvoiceRow>[] = [
    ...BASE_COLUMNS.filter((column) => column.key !== 'reason' && column.key !== 'paid'),
    {
      key: 'action',
      label: <span className='sr-only'>Action</span>,
      render: (row) => (
        <Button
          variant='glass'
          size='sm'
          onClick={(event) => {
            event.stopPropagation();
            ask({ prompt: draftReminderPrompt(row), selectedEntity: row.customerId ? { type: 'customer', id: row.customerId } : null, period });
          }}
        >
          <Icons.sparkles /> Draft reminder
        </Button>
      )
    }
  ];
  return (
    <Panel title='Dunning' description='Invoices still owed (open or uncollectible). Stripe owns the retry schedule; a reminder is only ever a draft for you to review.'>
      <QueryState query={open} label='open invoices'>
        {(result) => {
          if (result.data.reason) return <Unrecorded data={result.data} what='open invoices' />;
          const owed = dunningRows([...result.data.rows, ...(uncollectible.data?.data.reason ? [] : (uncollectible.data?.data.rows ?? []))]);
          return <SimpleTable rows={owed} rowKey={(row) => row.invoiceId} caption='Invoices still owed' emptyTitle='Nothing is owed right now' emptyDescription='No open or uncollectible invoice in this period.' columns={columns} />;
        }}
      </QueryState>
    </Panel>
  );
}
