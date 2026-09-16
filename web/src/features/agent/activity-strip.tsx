'use client';

import { useState } from 'react';
import { Icons } from '@/components/icons';
import type { Run, SchedulePlan } from '@/lib/api/types';
import { cn } from '@/lib/utils';

/**
 * What the run actually did, from its safe events only: detected intent, sources it was
 * allowed to read, warnings, cost. Lines with no data are omitted rather than faked.
 */
export function ActivityStrip({ run, plan, intent, destinations, skills }: { run: Run; plan?: SchedulePlan | null; intent?: string; destinations?: { platform: string; language: string }[]; skills?: string[] }) {
  const [open, setOpen] = useState(false);
  const events = run.events;
  const sources = events.filter((e) => e.type === 'source.added').length;
  const warnings = events.filter((e) => e.type === 'warning.created').map((e) => e.message ?? '');
  const first = events[0]?.at;
  const last = events[events.length - 1]?.at;
  const seconds = first && last ? Math.max(0, Math.round(last - first)) : null;
  const usage = run.usage as { modelRequests?: number; costUsd?: number; cliCostUsd?: number | null; billing?: string; provenance?: string };
  const running = run.status === 'running';
  const cost = usage?.billing === 'subscription'
    ? ` · your subscription paid${usage.cliCostUsd != null ? ` (CLI reported $${Number(usage.cliCostUsd).toFixed(3)})` : ''} · PostRiff $0`
    : usage?.modelRequests === 0
      ? ' · no model request · $0'
      : usage?.costUsd != null
        ? ` · $${usage.costUsd.toFixed(2)}`
        : '';
  const failed = run.status === 'failed' || run.status === 'cancelled';

  const Row = ({ ok, children }: { ok?: boolean; children: React.ReactNode }) => (
    <div className='text-muted-foreground flex min-h-6 items-start gap-2 text-xs'>
      {ok === false ? (
        <Icons.warning className='mt-0.5 size-3.5 shrink-0 text-amber-500' />
      ) : running ? (
        <Icons.spinner className='mt-0.5 size-3.5 shrink-0 animate-spin' />
      ) : (
        <Icons.check className='mt-0.5 size-3.5 shrink-0 text-emerald-500' />
      )}
      <span className='[&_b]:text-foreground [&_b]:font-medium'>{children}</span>
    </div>
  );

  return (
    <div className='bg-muted/60 flex flex-col gap-0.5 rounded-lg px-3 py-2'>
      {intent && (
        <Row>
          Detected <b>{intent.replace('_', ' ')}</b>
          {destinations && destinations.length > 0 && (
            <>
              {' · '}
              {destinations.length} destination{destinations.length === 1 ? '' : 's'} ({destinations.map((d) => d.platform).join(', ')})
            </>
          )}
          {plan && <> · times read in <b>{plan.timeZone}</b></>}
        </Row>
      )}
      {skills && skills.length > 0 && (
        <Row>
          Skills ·{' '}
          {skills.map((id, index) => (
            <span key={id}>
              {index > 0 && ', '}
              <b>{id.replace(/^postriff-/, '')}</b>
            </span>
          ))}
        </Row>
      )}
      <Row>
        Sources · <b>{sources}</b> approved source{sources === 1 ? '' : 's'} read; nothing else from your workspace
      </Row>
      {warnings.slice(0, 4).map((message, index) => (
        <Row key={index} ok={false}>
          {message}
        </Row>
      ))}
      {warnings.length > 4 && <Row ok={false}>{warnings.length - 4} more warnings in the run log</Row>}
      <div className='text-muted-foreground flex min-h-6 items-center justify-between gap-2 text-xs'>
        <span className='flex items-center gap-2'>
          <Icons.clock className='size-3.5 shrink-0' />
          <span>
            {failed ? <b className='text-foreground font-medium'>{run.status}</b> : running ? 'Running' : `Run ${seconds ?? 0}s`} ·{' '}
            <span className='font-mono'>{run.model}</span>
            {running ? '' : cost}
          </span>
        </span>
        <button type='button' className='underline underline-offset-2' onClick={() => setOpen((v) => !v)}>
          {open ? 'Hide run log' : 'Show run log'}
        </button>
      </div>
      {open && (
        <ol className={cn('mt-1 flex flex-col gap-1 border-t pt-2 text-xs')}>
          {events.map((event) => (
            <li key={event.id} className='text-muted-foreground'>
              <code className='bg-background rounded px-1'>{event.type}</code>
              {event.message ? ` — ${event.message}` : event.stage ? ` — ${event.stage} ${event.percent ?? ''}%` : event.policy ? ` — ${event.policy}` : event.action ? ` — ${event.action}` : ''}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
