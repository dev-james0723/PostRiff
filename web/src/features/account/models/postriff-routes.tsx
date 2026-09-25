'use client';

import type { ReactNode } from 'react';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { RadioGroup, RadioGroupItem } from '@/components/motion/radio';
import { StateMessage, Surface } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import type { AgentInfo, MemoryEgress, ModelOption } from '@/lib/api/types';
import { KIND_LABEL, costCopy, routeKind, routeReasoning } from './catalog';
import { OPTION_CLASS } from './cli-route-card';
import { ReasoningChips } from './reasoning-chips';

export interface MemoryConsent {
  loading: boolean;
  /** Undefined when the memory endpoint failed or did not include the decision. */
  egress: MemoryEgress | undefined;
}

function Line({ term, children }: { term: string; children: ReactNode }) {
  return (
    <span className='flex flex-col gap-0.5 sm:flex-row sm:gap-2'>
      <span className='text-muted-foreground shrink-0 sm:w-28'>{term}</span>
      <span className='text-foreground min-w-0 break-words'>{children}</span>
    </span>
  );
}

function RowDescription({
  option,
  agents,
  consent
}: {
  option: ModelOption;
  agents: AgentInfo[];
  consent: MemoryConsent;
}) {
  const kind = routeKind(option, agents);
  const reasoning = routeReasoning(option);
  const managedLive = kind === 'managed' && option.qualified;

  return (
    <span className='mt-1 flex flex-col gap-1.5 text-xs'>
      {/* The server's reason an option is unavailable is technical; the badge already says "Not available". */}
      {option.qualified && option.detail && <span className='hidden sm:inline'>{option.detail}</span>}
      <Line term='Cost'>{costCopy(option.costClass).line}</Line>
      {managedLive && (
        <>
          <Line term='Sources'>Only those you allowed for the cloud</Line>
          <Line term='Memory files'>
            {consent.loading ? (
              <span aria-hidden className='t-skel-pulse bg-muted inline-block h-3.5 w-20 rounded-md align-middle' />
            ) : consent.egress ? (
              consent.egress.cloud ? 'Shared' : 'Not shared'
            ) : (
              'Unavailable'
            )}
          </Line>
          {consent.egress && !consent.egress.cloud && (
            <StateMessage kind='partial' layout='inline' title='Drafts won’t use your memory files until an owner turns on sharing in Memory.' className='py-0' />
          )}
        </>
      )}
      {reasoning && (
        <span className='block pt-1'>
          <ReasoningChips levels={reasoning} />
        </span>
      )}
    </span>
  );
}

export interface PostriffRoutesProps {
  loading: boolean;
  /** False when the writer list has not arrived (the request failed), so an empty list is not a fact. */
  listed: boolean;
  options: ModelOption[];
  agents: AgentInfo[];
  current: string;
  onChoose: (id: string) => void;
  consent: MemoryConsent;
}

export function PostriffRoutes({ loading, listed, options, agents, current, onChoose, consent }: PostriffRoutesProps) {
  // Available writers first; the sort is stable, so catalog order holds within each group.
  const rows = options.filter((option) => routeKind(option, agents) !== 'cli').toSorted((a, b) => Number(b.qualified) - Number(a.qualified));
  const liveManagedListed = rows.some((option) => option.qualified && routeKind(option, agents) === 'managed');
  const selectedHere = rows.some((option) => option.id === current);

  return (
    <section data-tour='models-managed' className='flex flex-col gap-3' aria-labelledby='models-postriff-heading'>
      <div className='flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-1'>
        <h2 id='models-postriff-heading' className='text-foreground text-lg font-medium tracking-tight'>
          Built-in writers
        </h2>
      </div>
      <Surface material='quiet' radius='card' padding='md'>
        {loading ? (
          <div className='flex flex-col gap-3'>
            <Skeleton className='h-16 w-full rounded-[var(--rafii-radius-control)]' />
            <Skeleton className='h-16 w-full rounded-[var(--rafii-radius-control)]' />
          </div>
        ) : !listed ? (
          <StateMessage kind='offline' layout='inline' title='Unavailable until writers load' />
        ) : rows.length === 0 ? (
          <StateMessage kind='empty' layout='inline' title='No built-in writers' />
        ) : (
          <div className='flex flex-col gap-3'>
            <RadioGroup value={selectedHere ? current : ''} onValueChange={onChoose} aria-labelledby='models-postriff-heading' className='flex flex-col gap-2'>
              {rows.map((option) => {
                const kind = routeKind(option, agents);
                return (
                  <RadioGroupItem
                    key={option.id}
                    id={`model-${option.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`}
                    value={option.id}
                    disabled={!option.qualified}
                    label={
                      <span className='flex flex-wrap items-center gap-2'>
                        <span className='break-words'>{option.label}</span>
                        <Badge variant='secondary'>{KIND_LABEL[kind]}</Badge>
                        <AnimatedBadge status={option.qualified ? 'success' : 'neutral'} size='sm' contentKey={String(option.qualified)}>
                          {option.qualified ? 'Available' : 'Not available'}
                        </AnimatedBadge>
                      </span>
                    }
                    description={<RowDescription option={option} agents={agents} consent={consent} />}
                    className={OPTION_CLASS}
                  />
                );
              })}
            </RadioGroup>
            {!liveManagedListed && <p className='text-muted-foreground text-xs'>The managed model isn’t available.</p>}
          </div>
        )}
      </Surface>
    </section>
  );
}
