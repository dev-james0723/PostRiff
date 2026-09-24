'use client';

import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { RadioGroup, RadioGroupItem } from '@/components/motion/radio';
import { StateMessage, Surface } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import type { ReactNode } from 'react';
import type { AgentInfo, ModelOption } from '@/lib/api/types';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { KIND_LABEL, aliasLabel, authState, budgetCap, costCopy, hostLabel, probedAt, routeReasoning } from './catalog';
import { ReasoningChips } from './reasoning-chips';

/** A radio option as a quiet row; the chosen one carries the selected glass (DNA §5.2, §11.3). */
export const OPTION_CLASS =
  'rafii-quiet data-[state=checked]:rafii-glass-selected min-h-12 min-w-0 rounded-[var(--rafii-radius-control)] p-3 transition-colors';

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className='flex min-w-0 flex-col gap-0.5 sm:grid sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3'>
      <dt className='text-muted-foreground text-xs sm:text-sm'>{term}</dt>
      <dd className='text-foreground min-w-0 text-sm break-words'>{children}</dd>
    </div>
  );
}

export interface CliRouteCardProps {
  agent: AgentInfo;
  options: ModelOption[];
  current: string;
  onChoose: (id: string) => void;
  /** A "Check again" request is in flight: the badge pulses until the answer arrives. */
  checking: boolean;
  now: number;
}

export function CliRouteCard({ agent, options, current, onChoose, checking, now }: CliRouteCardProps) {
  const mine = options.filter((m) => m.route === agent.id);
  const auth = authState(agent);
  const cap = budgetCap(agent);
  const checkedAt = probedAt(agent);
  const reasoning = routeReasoning(agent);
  const costClasses = Array.from(new Set(mine.map((m) => m.costClass ?? '')));
  const details = Array.from(new Set(mine.map((m) => m.detail).filter(Boolean)));
  const selectedHere = mine.some((m) => m.id === current);
  const execution = agent.execution;

  return (
    <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-4'>
      <div className='flex flex-col gap-1.5'>
        <h3 className='flex flex-wrap items-center gap-2 text-base font-medium'>
          <span className='text-foreground'>{agent.name}</span>
          <Badge variant='secondary'>{KIND_LABEL.cli}</Badge>
          <AnimatedBadge
            status={auth.status}
            size='sm'
            pulse={checking}
            contentKey={`${agent.installed}-${agent.authStatus}`}
            title={`Reported by the API: installed ${agent.installed ? 'yes' : 'no'}, authStatus “${agent.authStatus}”`}
          >
            {auth.label}
          </AnimatedBadge>
        </h3>
        {agent.vendor && <p className='text-muted-foreground text-sm'>{agent.vendor}</p>}
      </div>

      {agent.guidance && <StateMessage kind='partial' layout='inline' title={agent.guidance} />}
      {agent.installed && agent.authStatus === 'expired' && (
        <p className='text-muted-foreground text-xs leading-relaxed'>
          This mark comes from a run the CLI refused. It stays until the PostRiff server restarts, even after you sign in again; Check again cannot clear it yet.
        </p>
      )}

      <dl className='flex flex-col gap-2'>
        <Fact term='Version'>{agent.version ? <span className='font-mono'>{agent.version}</span> : 'Not reported'}</Fact>
        {agent.installed && <Fact term='Signed in with'>{agent.authMethod ? <span className='font-mono'>{agent.authMethod}</span> : 'Not reported'}</Fact>}
        <Fact term='Runs on'>
          {hostLabel(agent.host)}
          {agent.host === 'api-process' && <span className='text-muted-foreground'> · everyone who writes through this PostRiff server shares its sign-in and subscription</span>}
        </Fact>
        <Fact term='Who pays'>
          {costClasses.length === 0 ? 'No models listed' : costClasses.map((costClass) => costCopy(costClass).line).join(' ')}
        </Fact>
        {checkedAt !== null && (
          <Fact term='Checked'>
            <time dateTime={new Date(checkedAt * 1000).toISOString()} title={formatDateTime(checkedAt)}>
              {relativeTime(checkedAt, Math.max(now, checkedAt))}
            </time>
          </Fact>
        )}
      </dl>

      <div className='flex flex-col gap-2'>
        <span className='text-foreground text-sm font-medium' id={`models-${agent.id}-label`}>
          Models{agent.modelsSource === 'aliases' ? ' · the CLI’s own names' : agent.modelsSource === 'configured' ? ' · as configured for this deployment' : ''}
        </span>
        {mine.length === 0 ? (
          <p className='text-muted-foreground text-sm'>{agent.installed ? 'The API listed no models for this CLI.' : 'Models appear once the CLI is installed.'}</p>
        ) : (
          <RadioGroup
            value={selectedHere ? current : ''}
            onValueChange={onChoose}
            aria-labelledby={`models-${agent.id}-label`}
            className='grid gap-2 sm:grid-cols-2'
          >
            {mine.map((model) => (
              <RadioGroupItem
                key={model.id}
                id={`model-${model.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`}
                value={model.id}
                label={aliasLabel(model, agent.name)}
                description={model.qualified ? undefined : `Not available · ${auth.label}`}
                disabled={!model.qualified}
                className={OPTION_CLASS}
              />
            ))}
          </RadioGroup>
        )}
        {details.length === 1 && details[0] !== agent.guidance && <p className='text-muted-foreground text-xs'>{details[0]}</p>}
      </div>

      {reasoning && <ReasoningChips levels={reasoning} />}

      {execution && (
        <Collapsible>
          <CollapsibleTrigger className='group/how rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-9 items-center gap-1 rounded-md text-sm font-medium'>
            <Icons.chevronRight className='size-4 transition-transform duration-(--duration-quick) group-data-[panel-open]/how:rotate-90 motion-reduce:transition-none' />
            How it runs
          </CollapsibleTrigger>
          <CollapsibleContent
            className={cn(
              'pt-3 transition-[opacity,transform] duration-(--duration-fast) ease-(--ease-smooth-out) motion-reduce:transition-none',
              'data-[starting-style]:-translate-y-1 data-[starting-style]:opacity-0',
              'data-[ending-style]:-translate-y-1 data-[ending-style]:opacity-0 data-[ending-style]:duration-(--duration-quick)'
            )}
          >
            <dl className='flex flex-col gap-2'>
              <Fact term='Spending cap per run'>
                {cap !== null ? (
                  <>
                    <span className='font-mono'>${cap.toFixed(2)}</span>
                    <span className='text-muted-foreground'> · {agent.name} stops a run that reaches it</span>
                  </>
                ) : (
                  <span>No cap reported for this CLI · the time limit still applies</span>
                )}
              </Fact>
              <Fact term='Time limit'>
                <span className='font-mono'>{execution.timeoutSeconds}s</span>
              </Fact>
              <Fact term='Tools'>{execution.tools}</Fact>
              <Fact term='MCP servers'>{execution.mcp}</Fact>
              <Fact term='Settings read'>{execution.settingSources}</Fact>
              <Fact term='Saved sessions'>{execution.sessionPersistence ? 'On' : 'Off'}</Fact>
              <Fact term='Environment passed'>
                <span className='font-mono text-xs'>{execution.environment.join(' ')}</span>
              </Fact>
            </dl>
          </CollapsibleContent>
        </Collapsible>
      )}
    </Surface>
  );
}
