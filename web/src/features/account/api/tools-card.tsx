'use client';

import { AnimatedBadge } from '@/components/motion/animated-badge';
import { InfoTip, StateMessage } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { formatBytes } from '@/lib/time';
import { SettingsSection } from '../settings-section';
import { LoadError } from './load-error';
import { costLabel, effectLabel, type ToolIsolation, type ToolRegistryState } from './tool-registry';

function ToolsSkeleton() {
  return (
    <div className='flex flex-col gap-3' aria-hidden>
      <Skeleton className='h-14 w-full rounded-[var(--rafii-radius-control)]' />
      <Skeleton className='h-14 w-full rounded-[var(--rafii-radius-control)]' />
      {Array.from({ length: 4 }, (_, index) => (
        <Skeleton key={index} className='h-16 w-full rounded-[var(--rafii-radius-control)]' />
      ))}
    </div>
  );
}

/** Isolation and invoke are two flags in the API; they stay two rows here so one is never read as the other. */
function RunnerFlags({ isolation }: { isolation: ToolIsolation }) {
  return (
    <div className='rafii-glass flex flex-col gap-1 rounded-[var(--rafii-radius-control)] px-3 py-1 text-sm'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <span className='text-foreground flex items-center gap-0.5 font-medium'>
          Runner isolation
          <InfoTip label='About runner isolation' className='size-9' description={`${isolation.detail} Runner: ${isolation.runner}.`} />
        </span>
        <AnimatedBadge size='sm' status={isolation.isolated ? 'success' : 'warning'} contentKey={isolation.isolated ? 'isolated' : 'not-isolated'}>
          {isolation.isolated ? 'Isolated' : 'Not isolated'}
        </AnimatedBadge>
      </div>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <span className='text-foreground flex items-center gap-0.5 font-medium'>
          Public invoke
          <InfoTip
            label='About public invoke'
            className='size-9'
            description={isolation.publicInvokeEnabled ? 'Tools can run through the API.' : 'Tools are listed but can’t run through the API.'}
          />
        </span>
        <AnimatedBadge
          size='sm'
          status={isolation.publicInvokeEnabled ? 'info' : 'neutral'}
          contentKey={isolation.publicInvokeEnabled ? 'invoke-enabled' : 'invoke-blocked'}
        >
          {isolation.publicInvokeEnabled ? 'Enabled' : 'Blocked'}
        </AnimatedBadge>
      </div>
    </div>
  );
}

/**
 * The versioned tools the API lists (`GET /api/tools`) and the runner's two flags. The list is a
 * registry, not a promise that anything runs.
 */
export function ToolsCard({ tools }: { tools: ToolRegistryState }) {
  const { available, query } = tools;
  const registry = query.data;

  let content;
  if (!available) {
    content = (
      <StateMessage
        kind='unsupported'
        layout='inline'
        title='Tools aren’t available yet'
      />
    );
  } else if (query.isPending) {
    content = <ToolsSkeleton />;
  } else if (query.isError && !registry) {
    content = (
      <LoadError
        title='Couldn’t load tools'
        error={query.error}
        retrying={query.isFetching}
        onRetry={() => void query.refetch()}
      />
    );
  } else if (registry) {
    content = (
      <div className='flex flex-col gap-4'>
        <RunnerFlags isolation={registry.isolation} />
        {registry.tools.length === 0 ? (
          <StateMessage kind='empty' layout='inline' title='No tools yet' />
        ) : (
          <ul className='flex flex-col gap-4' aria-label='Registered tools'>
            {registry.tools.map((tool) => (
              <li key={`${tool.id}@${tool.version}`} className='flex flex-col gap-1.5'>
                <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
                  <span className='text-foreground font-mono text-sm break-all'>{tool.id}</span>
                  <span className='text-muted-foreground font-mono text-xs'>v{tool.version}</span>
                </div>
                <div className='flex flex-wrap gap-1.5'>
                  <Badge variant='secondary'>{effectLabel(tool.effect)}</Badge>
                  <Badge variant='secondary'>{costLabel(tool.cost)}</Badge>
                </div>
                <p className='text-foreground text-sm leading-relaxed'>{tool.purpose}</p>
                {tool.bounds && (
                  <p className='text-muted-foreground hidden text-xs md:block'>
                    Up to {tool.bounds.maxSeconds}s · {formatBytes(tool.bounds.maxInputBytes)} in · network: {tool.bounds.network}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <SettingsSection
      id='api-tools'
      title='Tools'
      className='h-full'
      bodyClassName='flex-1'
      data-tour='api-tools'
    >
      {content}
    </SettingsSection>
  );
}
