'use client';

import { useId, useState, type ReactNode } from 'react';
import { motion, useReducedMotion, type Variants } from 'motion/react';
import { AgentDisclosure } from '@/components/agents/agent-disclosure';
import { Icons } from '@/components/icons';
import { ActionSwapIcon, ActionSwapText } from '@/components/motion/action-swap';
import type { MemoryBinding, Run, SchedulePlan } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';

// On first mount the lines settle in one after another; a line that arrives later (a new warning) fades in on its own.
const STRIP: Variants = { hidden: {}, shown: { transition: { staggerChildren: 0.04 } } };
const LINE: Variants = { hidden: { opacity: 0, y: 3 }, shown: { opacity: 1, y: 0, transition: { duration: 0.22, ease: EASE_OUT } } };

/** One line of the strip. Module scope so its icon keeps its identity across polls and can swap spinner → check. */
function Row({ ok, running, children }: { ok?: boolean; running: boolean; children: ReactNode }) {
  const state = ok === false ? 'warning' : running ? 'running' : 'done';
  return (
    <motion.div variants={LINE} className='text-muted-foreground flex min-h-6 items-start gap-2 text-xs'>
      <ActionSwapIcon value={state} className='mt-0.5 size-3.5'>
        {state === 'warning' ? (
          <Icons.warning className='text-foreground size-3.5' />
        ) : state === 'running' ? (
          <Icons.spinner className='size-3.5 animate-spin' />
        ) : (
          <Icons.check className='text-foreground size-3.5' />
        )}
      </ActionSwapIcon>
      <span className='[&_b]:text-foreground [&_b]:font-medium'>{children}</span>
    </motion.div>
  );
}

/**
 * What the run actually did, from its safe events only: detected intent, sources it was
 * allowed to read, warnings, cost. Lines with no data are omitted rather than faked.
 */
export function ActivityStrip({ run, plan, intent, destinations, skills, memory }: { run: Run; plan?: SchedulePlan | null; intent?: string; destinations?: { platform: string; language: string; account?: string }[]; skills?: string[]; memory?: MemoryBinding | null }) {
  const [open, setOpen] = useState(false);
  const reduce = useReducedMotion();
  const logId = useId();
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

  return (
    <motion.div variants={STRIP} initial={reduce ? false : 'hidden'} animate='shown' className='bg-muted/60 flex flex-col gap-0.5 rounded-lg px-3 py-2'>
      {intent && (
        <Row running={running}>
          Detected <b>{intent.replace('_', ' ')}</b>
          {destinations && destinations.length > 0 && (
            <>
              {' · '}
              {destinations.length} destination{destinations.length === 1 ? '' : 's'} ({destinations.map((d) => (d.account ? `${d.platform} · ${d.account}` : d.platform)).join(', ')})
            </>
          )}
          {plan && <> · times read in <b>{plan.timeZone}</b></>}
        </Row>
      )}
      {skills && skills.length > 0 && (
        <Row running={running}>
          Skills ·{' '}
          {skills.map((id, index) => (
            <span key={id}>
              {index > 0 && ', '}
              <b>{id.replace(/^postriff-/, '')}</b>
            </span>
          ))}
        </Row>
      )}
      {memory && memory.used.length > 0 && (
        <Row running={running}>
          Memory · <b>{memory.used.length}</b> learned rule{memory.used.length === 1 ? '' : 's'} used
          {memory.omitted.length > 0 ? ` · ${memory.omitted.length} left out for space` : ''}: {memory.statements.join(' · ')}
        </Row>
      )}
      <Row running={running}>
        Sources · <b>{sources}</b> approved source{sources === 1 ? '' : 's'} read; nothing else from your workspace
      </Row>
      {warnings.slice(0, 4).map((message, index) => (
        <Row key={index} ok={false} running={running}>
          {message}
        </Row>
      ))}
      {warnings.length > 4 && <Row ok={false} running={running}>{warnings.length - 4} more warnings in the run log</Row>}
      <motion.div variants={LINE} className='text-muted-foreground flex min-h-6 items-center justify-between gap-2 text-xs'>
        <span className='flex items-center gap-2'>
          <Icons.clock className='size-3.5 shrink-0' />
          <span>
            {failed ? <b className='text-foreground font-medium'>{run.status}</b> : running ? 'Running' : `Run ${seconds ?? 0}s`} ·{' '}
            <span className='font-mono'>{run.model}</span>
            {running ? '' : cost}
          </span>
        </span>
        <button type='button' aria-expanded={open} aria-controls={logId} onClick={() => setOpen((v) => !v)}>
          {/* The underline sits on the text itself: decoration does not reach into the swap's inline-block layers. */}
          <ActionSwapText value={open ? 'hide' : 'show'} animation='roll'>
            <span className='underline underline-offset-2'>{open ? 'Hide run log' : 'Show run log'}</span>
          </ActionSwapText>
        </button>
      </motion.div>
      {/* -mt-0.5 cancels the strip's gap while closed; open, the log sits 6px below the status line as before. */}
      <AgentDisclosure id={logId} open={open} className='-mt-0.5'>
        <ol className='mt-1.5 flex flex-col gap-1 border-t pt-2 text-xs'>
          {events.map((event) => (
            <li key={event.id} className='text-muted-foreground'>
              <code className='bg-background rounded px-1'>{event.type}</code>
              {event.message ? ` — ${event.message}` : event.stage ? ` — ${event.stage} ${event.percent ?? ''}%` : event.policy ? ` — ${event.policy}` : event.action ? ` — ${event.action}` : ''}
            </li>
          ))}
        </ol>
      </AgentDisclosure>
    </motion.div>
  );
}
