'use client';

import { useMetric } from '../customers/kit/api';
import { ReceiptChip } from '../customers/kit/evidence';
import { DataStateChip, QueryState } from '../customers/kit/page-frame';
import { opsSpec } from '../operations/ops-model';
import { SourceHealthTable } from '../operations/panels';

/**
 * Advanced → Data health (CONTRACTS §8.D): every source the founder cron probes (cron, consumer and Control databases,
 * the reader role, phone provider, notification outbox, Stripe webhooks, email provider, model settlements) with its
 * state, last good read, age and reason, read through the receipted `source_health` metric. A source with no probe
 * row says so; a stale or silent source is never shown as healthy.
 */
export function DataHealth() {
  const sources = useMetric(opsSpec('sourceHealth', '7d'));
  return (
    <div className='flex flex-col gap-3'>
      {sources.data && (
        <div className='flex flex-wrap items-center gap-2'>
          <DataStateChip state={sources.data.dataState} asOf={sources.data.asOf} />
          {sources.data.queryReceiptId && <ReceiptChip receiptId={sources.data.queryReceiptId} />}
        </div>
      )}
      <QueryState query={sources} label='source health'>
        {(result) => <SourceHealthTable rows={result.rows} />}
      </QueryState>
      <p className='text-muted-foreground text-xs'>
        Probed every minute. A probe older than three minutes reads as stale; event sources (Stripe, email, model settlements) show the time of their latest good event. The independent watchdog checks the cron heartbeat from outside the app.
      </p>
    </div>
  );
}
