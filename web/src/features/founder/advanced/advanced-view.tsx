'use client';

import { useId, useState } from 'react';
import { parseAsString, useQueryState } from 'nuqs';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { FounderActionsLog } from '@/features/founder/actions';
import { FIELD_CLASS, StatusChip } from '@/features/workspace/rafii-parts';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { useAudit, useCapability, useReceipt } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { useEvidenceDrawer } from '../customers/kit/evidence';
import { count, stateLabel, whenDateTime } from '../customers/kit/format';
import { DataStateChip, FounderPage, Panel, QueryState } from '../customers/kit/page-frame';
import { SimpleTable } from '../customers/kit/simple-table';
import { useTabState } from '../customers/kit/tabs';
import type { AuditEvent } from '../customers/kit/types';
import { DataHealth } from './data-health';
import { EngineeringChecks } from './engineering';

/**
 * Advanced (PRD §5.1): the operator audit log (`GET /audit`, content-free), receipt lookup by id
 * (`GET /metrics/receipts/{id}` → EvidenceDrawer), source health in full, the founder action log (`GET /actions`)
 * and attested exact-SHA engineering evidence (`GET /engineering`). Nothing here acts; it shows what was recorded,
 * for whom, and when. The tab ids are the nav's (`audit` · `receipts` · `data-health` · `actions` · `engineering`);
 * older spellings (`sources`, `evidence`, the `/control/*` redirects) resolve through `customers/kit/tab-ids.ts`.
 */
const TABS = [
  ['audit', 'Audit'],
  ['receipts', 'Receipts'],
  ['data-health', 'Data health'],
  ['actions', 'Actions'],
  ['engineering', 'Engineering']
] as const;

const RECEIPT_ID = /^[A-Za-z0-9-]{8,80}$/;

function ReceiptLookup() {
  const evidence = useEvidenceDrawer();
  const [receiptId, setReceiptId] = useQueryState('receipt', parseAsString.withOptions({ history: 'replace', clearOnDefault: true }));
  const [value, setValue] = useState(receiptId ?? '');
  const [error, setError] = useState<string | null>(null);
  const receipt = useReceipt(receiptId);
  const inputId = useId();
  function submit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!RECEIPT_ID.test(trimmed)) {
      setError('A receipt id is 8–80 letters, digits or dashes.');
      return;
    }
    setError(null);
    void setReceiptId(trimmed);
  }
  const found = receipt.data?.receipt ?? null;
  return (
    <div className='flex flex-col gap-4'>
      <form onSubmit={submit} className='flex flex-col gap-2 sm:flex-row sm:items-end'>
        <div className='flex min-w-0 flex-1 flex-col gap-2 text-sm'>
          <Label htmlFor={inputId} className='text-foreground font-medium'>
            Receipt id
          </Label>
          <Input id={inputId} value={value} onChange={(event) => setValue(event.target.value)} placeholder='e.g. 3f7c…' className={`${FIELD_CLASS} font-mono`} autoComplete='off' spellCheck={false} />
        </div>
        <Button type='submit' variant='action' size='control'>
          <Icons.search /> Look up
        </Button>
      </form>
      {error && <StateMessage kind='error' layout='inline' title={error} />}
      {receiptId && (
        <QueryState query={receipt} label='receipt' isEmpty={(result) => result.receipt === null} emptyTitle='Receipt not found' emptyDescription='No receipt with this id is readable by this operator, or it has expired.'>
          {() =>
            found && (
              <div className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-4'>
                <div className='flex flex-wrap items-center gap-2'>
                  <DataStateChip state={found.dataState ?? found.data_state} />
                  <span className='font-mono text-xs'>{found.id}</span>
                  <span className='text-muted-foreground text-xs'>calculated {whenDateTime(found.calculated_at)}</span>
                </div>
                <dl className='grid grid-cols-[minmax(7rem,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs'>
                  <dt className='text-muted-foreground'>Rows</dt>
                  <dd className='tabular-nums'>{count(found.row_count ?? found.result_rows?.length ?? null)}</dd>
                  <dt className='text-muted-foreground'>Metrics</dt>
                  <dd className='font-mono break-all'>{found.normalized_query && Array.isArray((found.normalized_query as { metricIds?: unknown }).metricIds) ? ((found.normalized_query as { metricIds: string[] }).metricIds.join(', ')) : 'Not recorded'}</dd>
                  <dt className='text-muted-foreground'>Query digest</dt>
                  <dd className='font-mono break-all'>{found.query_digest ?? 'Not recorded'}</dd>
                  <dt className='text-muted-foreground'>Sources</dt>
                  <dd className='font-mono break-all'>{found.source_watermarks ? Object.entries(found.source_watermarks).map(([source, watermark]) => `${source} @ ${whenDateTime(watermark)}`).join(' · ') : 'Not recorded'}</dd>
                </dl>
                <Button variant='glass' size='default' className='self-start' onClick={() => evidence.open({ receiptId: found.id, record: found })}>
                  <Icons.listDetails /> Open evidence drawer
                </Button>
              </div>
            )
          }
        </QueryState>
      )}
      {evidence.drawer}
    </div>
  );
}

function AuditTable() {
  const audit = useAudit();
  const allowed = useCapability('audit.read');
  if (!allowed) return <StateMessage kind='permission' title='The audit log needs audit.read' description='This operator was not granted the audit capability, so no audit request is sent.' />;
  return (
    <QueryState query={audit} label='audit log' isEmpty={(result) => result.events.length === 0} emptyTitle='No audit entries' emptyDescription='Every authorised control request writes one row; none have been recorded in this environment.'>
      {(result) => (
        <div className='flex flex-col gap-2'>
          <p className='text-muted-foreground text-xs'>Latest {count(result.events.length)}{result.limit ? ` of at most ${count(result.limit)}` : ''} entries. Content-free: actions and results only, never bodies.</p>
          <SimpleTable<AuditEvent>
            className='relative'
            rows={result.events}
            rowKey={(row) => row.id}
            caption='Operator audit log'
            columns={[
              { key: 'at', label: 'When', render: (row) => <span className='whitespace-nowrap'>{whenDateTime(row.occurred_at)}</span> },
              { key: 'action', label: 'Action', render: (row) => <span className='font-mono text-xs'>{row.action}</span> },
              { key: 'result', label: 'Result', render: (row) => <StatusChip status={row.result === 'succeeded' ? 'success' : row.result === 'denied' ? 'danger' : 'warning'}>{stateLabel(row.result)}</StatusChip> },
              { key: 'code', label: 'Code', render: (row) => (row.error_code ? <span className='font-mono text-xs'>{row.error_code}</span> : <span className='text-muted-foreground'>—</span>) },
              { key: 'actor', label: 'Actor', render: (row) => <span className='font-mono text-xs'>{row.actor ? `…${row.actor.slice(-8)}` : 'Not recorded'}</span> },
              { key: 'request', label: 'Request', render: (row) => <span className='font-mono text-xs'>{row.request_id ? `…${row.request_id.slice(-8)}` : '—'}</span> },
              { key: 'env', label: 'Environment', render: (row) => stateLabel(row.environment) }
            ]}
          />
        </div>
      )}
    </QueryState>
  );
}

export function AdvancedView() {
  const ask = useAsk();
  const [tab, setTab] = useTabState('advanced', 'audit');
  useFounderPageContext({ section: 'advanced', filters: { tab } });
  return (
    <FounderPage
      eyebrow='Advanced'
      title='Advanced'
      description='Evidence and bookkeeping: what was asked of Control, which receipts back each number, and whether every source is still talking.'
      actions={
        <Button variant='glass' size='control' onClick={() => ask({ prompt: 'Which sources are stale or silent right now, and which recent control requests were denied?' })}>
          <Icons.sparkles /> Ask Rafii
        </Button>
      }
    >
      <Tabs value={tab} onValueChange={(value) => setTab(value)}>
        <div className='scrollbar-hide relative -mx-1 overflow-x-auto px-1'>
          <TabsList variant='line' className='w-max'>
            {TABS.map(([id, label]) => (
              <TabsTrigger key={id} value={id}>
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent value='audit' className='pt-4'>
          <Panel title='Audit log' description='Every control request this operator made, with its result.'>
            <AuditTable />
          </Panel>
        </TabsContent>
        <TabsContent value='receipts' className='pt-4'>
          <Panel title='Receipt lookup' description='Paste a receipt id from any tile, chart or answer to see its query digest, watermarks and masked rows.'>
            <ReceiptLookup />
          </Panel>
        </TabsContent>
        <TabsContent value='data-health' className='pt-4'>
          <Panel title='Data health' description='Every probed source: state, last good read, age and reason.'>
            <DataHealth />
          </Panel>
        </TabsContent>
        <TabsContent value='actions' className='pt-4'>
          <Panel title='Founder actions' description='Every founder action request, newest first, with what the preview showed and what happened, and the account blocks in force.'>
            <FounderActionsLog />
          </Panel>
        </TabsContent>
        <TabsContent value='engineering' className='pt-4'>
          <Panel title='Engineering checks' description='Attested exact-SHA evidence from CI, deployments and error trackers, and the overall state it supports. Read-only.'>
            <EngineeringChecks />
          </Panel>
        </TabsContent>
      </Tabs>
    </FounderPage>
  );
}
