'use client';

import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StateMessage } from '@/components/rafii';
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
    <div className='rafii-glass flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-3 text-sm'>
      <div className='flex flex-col gap-1'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <span className='text-foreground font-medium'>Runner isolation</span>
          <AnimatedBadge size='sm' status={isolation.isolated ? 'success' : 'warning'} contentKey={isolation.isolated ? 'isolated' : 'not-isolated'}>
            {isolation.isolated ? 'Isolated' : 'Not isolated'}
          </AnimatedBadge>
        </div>
        <p className='text-muted-foreground text-xs leading-relaxed'>
          {isolation.detail} <span className='font-mono'>runner: {isolation.runner}</span>
        </p>
      </div>
      <div className='flex flex-col gap-1'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <span className='text-foreground font-medium'>Public invoke</span>
          <AnimatedBadge
            size='sm'
            status={isolation.publicInvokeEnabled ? 'info' : 'neutral'}
            contentKey={isolation.publicInvokeEnabled ? 'invoke-enabled' : 'invoke-blocked'}
          >
            {isolation.publicInvokeEnabled ? 'Enabled' : 'Blocked'}
          </AnimatedBadge>
        </div>
        <p className='text-muted-foreground text-xs leading-relaxed'>
          {isolation.publicInvokeEnabled
            ? 'Tools can be run through the API on this deployment.'
            : 'Invoke is blocked on this deployment: tools are listed but cannot be run through the API.'}
        </p>
      </div>
    </div>
  );
}

/**
 * The versioned tools this deployment lists (`GET /api/tools`) and the runner's two flags. The list
 * is a registry, not a promise that anything runs.
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
        title='Unavailable'
        description='This page cannot read the tool registry yet, so the tools and the runner’s status are not shown.'
      />
    );
  } else if (query.isPending) {
    content = <ToolsSkeleton />;
  } else if (query.isError && !registry) {
    content = (
      <LoadError
        title='The tool registry could not be loaded.'
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
          <StateMessage kind='empty' layout='inline' title='No tools are registered for this deployment.' />
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
                  <p className='text-muted-foreground text-xs'>
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
      title='Tool registry'
      description='Versioned tools this deployment lists for agents. Being listed does not mean a tool can run.'
      className='h-full'
      bodyClassName='flex-1'
      data-tour='api-tools'
    >
      {content}
    </SettingsSection>
  );
}
