'use client';

import { AnimatedBadge } from '@/components/motion/animated-badge';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { formatBytes } from '@/lib/time';
import { LoadError } from './load-error';
import { costLabel, effectLabel, type ToolIsolation, type ToolRegistryState } from './tool-registry';

function ToolsSkeleton() {
  return (
    <div className='flex flex-col gap-3' aria-hidden>
      <Skeleton className='h-14 w-full' />
      <Skeleton className='h-14 w-full' />
      {Array.from({ length: 4 }, (_, index) => (
        <Skeleton key={index} className='h-16 w-full' />
      ))}
    </div>
  );
}

/** Isolation and invoke are two flags in the API; they stay two rows here so one is never read as the other. */
function RunnerFlags({ isolation }: { isolation: ToolIsolation }) {
  return (
    <div className='flex flex-col gap-3 rounded-lg border p-3 text-sm'>
      <div className='flex flex-col gap-1'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <span className='font-medium'>Runner isolation</span>
          <AnimatedBadge
            size='sm'
            status={isolation.isolated ? 'success' : 'warning'}
            contentKey={isolation.isolated ? 'isolated' : 'not-isolated'}
          >
            {isolation.isolated ? 'Isolated' : 'Not isolated'}
          </AnimatedBadge>
        </div>
        <p className='text-muted-foreground text-xs'>
          {isolation.detail} <span className='font-mono'>runner: {isolation.runner}</span>
        </p>
      </div>
      <div className='flex flex-col gap-1'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <span className='font-medium'>Public invoke</span>
          <AnimatedBadge
            size='sm'
            status={isolation.publicInvokeEnabled ? 'info' : 'neutral'}
            contentKey={isolation.publicInvokeEnabled ? 'invoke-enabled' : 'invoke-blocked'}
          >
            {isolation.publicInvokeEnabled ? 'Enabled' : 'Blocked'}
          </AnimatedBadge>
        </div>
        <p className='text-muted-foreground text-xs'>
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
      <div role='status' className='flex flex-col items-start gap-2 rounded-lg border border-dashed p-4 text-sm'>
        <AnimatedBadge size='sm' status='neutral' contentKey='unavailable'>
          Unavailable
        </AnimatedBadge>
        <p className='text-muted-foreground'>
          This page cannot read the tool registry yet, so the tools and the runner&apos;s status are not shown.
        </p>
      </div>
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
          <p className='text-muted-foreground text-sm'>No tools are registered for this deployment.</p>
        ) : (
          <ul className='flex flex-col gap-2' aria-label='Registered tools'>
            {registry.tools.map((tool) => (
              <li key={`${tool.id}@${tool.version}`} className='flex flex-col gap-1.5 rounded-lg border p-3'>
                <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
                  <span className='font-mono text-sm break-all'>{tool.id}</span>
                  <span className='text-muted-foreground font-mono text-xs'>v{tool.version}</span>
                </div>
                <div className='flex flex-wrap gap-1.5'>
                  <Badge variant='outline'>{effectLabel(tool.effect)}</Badge>
                  <Badge variant='outline'>{costLabel(tool.cost)}</Badge>
                </div>
                <p className='text-sm'>{tool.purpose}</p>
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
    <Card data-tour='api-tools' className='h-full'>
      <CardHeader>
        <CardTitle>Tool registry</CardTitle>
        <CardDescription>
          Versioned tools this deployment lists for agents. Being listed does not mean a tool can run.
        </CardDescription>
      </CardHeader>
      <CardContent>{content}</CardContent>
    </Card>
  );
}
